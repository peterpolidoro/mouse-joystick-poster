# Blender manifest + automatic cylinder placement (template)

This file is meant to be **copied into your Blender manifest/Python development chat**.  
It contains:

1. A **manifest.json template** for a platonic solid + automatically placed radial cylinders.
2. A **Blender Python implementation plan** (code snippets) to:
   - enumerate candidate attachment sites (face centers + vertices),
   - filter to those **visible** in the camera,
   - select a subset that are **well-separated in screen space**,
   - spawn cylinders pointing **radially outward**.

---

## 1) `manifest.json` template (auto-first)

> The schema is designed so cylinders are auto-placed by default, but later you can add a manual override by filling in `attach.site_type` and `attach.index` per cylinder.

```json
{
  "manifest_version": 1,
  "seed": 1337,

  "render": {
    "resolution": [1024, 1024],
    "resolution_percentage": 100,
    "filepath": "out/render.png",
    "engine": "CYCLES",
    "samples": 128
  },

  "camera": {
    "type": "PERSP",
    "location": [2.7, -2.7, 1.9],
    "look_at": [0.0, 0.0, 0.0],
    "lens_mm": 50,
    "clip_start": 0.01,
    "clip_end": 100.0
  },

  "solid": {
    "name": "Solid",
    "type": "ICOSAHEDRON",
    "radius": 1.0,
    "location": [0.0, 0.0, 0.0],
    "rotation_euler_deg": [0.0, 0.0, 0.0]
  },

  "cylinders": {
    "defaults": {
      "radius": 0.06,
      "length": 0.9,
      "sides": 24,

      "base_offset": "AUTO",

      "material": "CylMaterial",

      "attach": {
        "site_type": null,
        "index": null
      }
    },

    "instances": [
      { "id": "cyl_00" },
      { "id": "cyl_01" },
      { "id": "cyl_02" },
      { "id": "cyl_03" },
      { "id": "cyl_04" },
      { "id": "cyl_05" },
      { "id": "cyl_06" },
      { "id": "cyl_07" },
      { "id": "cyl_08" },
      { "id": "cyl_09" }
    ],

    "auto_placement": {
      "enabled": true,

      "allowed_site_types": ["FACE", "VERT"],

      "unique_sites": true,

      "require_visible_base": true,
      "require_tip_in_frame": true,

      "min_base_separation_px": 90,
      "min_segment_separation_px": 25,

      "bias_silhouette": 1.0,

      "restarts": 30,

      "fallback": {
        "relax_separation_steps": 6,
        "min_relaxed_factor": 0.55,
        "allow_occluded_if_insufficient": false
      }
    }
  }
}
```

### Manifest notes

- `cylinders.instances[]` is the list of cylinders you want. Each item can override defaults, e.g.:

```json
{ "id": "cyl_big", "radius": 0.09, "length": 1.2 }
```

- Later, manual override is simply:

```json
{ "id": "cyl_03", "attach": { "site_type": "FACE", "index": 7 } }
```

If `attach.site_type` and `attach.index` are both non-null, the auto-placement code should **respect them**.

---

## 2) Auto-placement strategy (what you implement)

Attachment sites are **discrete**:

- Faces → **center of polygon**
- Vertices → **vertex coordinate**

To choose good-looking sites automatically:

1. Enumerate all face centers + vertices on the solid.
2. Filter candidates:
   - base point is inside camera frame,
   - base point is visible (ray from camera hits the solid at that point first),
   - (optionally) cylinder tip also stays in frame.
3. Select N sites for N cylinders that maximize:
   - **2D spacing** between cylinder bases (in pixels),
   - **2D spacing** between projected cylinder segments (to reduce overlaps),
   - **silhouette preference** (bases farther from projected center tend to look better).

Because a platonic solid has a tiny number of candidates (≈ 14–32), you can do multiple randomized greedy passes (**restarts**) very cheaply.

---

## 3) Blender Python code snippets

> Copy these into your builder script. They are written to be “drop-in-ish”: you still need to plug them into your existing `load manifest → setup scene → render` flow.

### 3.1 Expand cylinder instances from defaults

```python
def expand_cylinders(manifest: dict) -> list[dict]:
    cyl = manifest["cylinders"]
    defaults = cyl.get("defaults", {})
    instances = cyl.get("instances", [])

    out = []
    for inst in instances:
        spec = dict(defaults)
        spec.update(inst)

        # ensure attach dict exists and has keys
        spec.setdefault("attach", {})
        spec["attach"].setdefault("site_type", None)
        spec["attach"].setdefault("index", None)

        out.append(spec)
    return out
```

### 3.2 Enumerate candidate attachment sites on the solid

```python
def gather_candidates(solid_obj):
    mw = solid_obj.matrix_world
    mesh = solid_obj.data

    # Face centers
    for poly in mesh.polygons:
        yield ("FACE", poly.index, mw @ poly.center)

    # Vertices
    for v in mesh.vertices:
        yield ("VERT", v.index, mw @ v.co)
```

### 3.3 Camera projection helpers

```python
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

def ndc_and_in_frame(scene, cam_obj, world_pt):
    ndc = world_to_camera_view(scene, cam_obj, world_pt)
    in_frame = (0.0 <= ndc.x <= 1.0 and 0.0 <= ndc.y <= 1.0 and ndc.z >= 0.0)
    return ndc, in_frame

def ndc_to_px(scene, ndc):
    r = scene.render
    W = r.resolution_x * (r.resolution_percentage / 100.0)
    H = r.resolution_y * (r.resolution_percentage / 100.0)
    return Vector((ndc.x * W, ndc.y * H)), W, H
```

### 3.4 BVH visibility test against ONLY the solid

```python
import bpy
from mathutils.bvhtree import BVHTree

def build_solid_bvh(solid_obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return BVHTree.FromObject(solid_obj, depsgraph, epsilon=1e-6)

def visible_on_solid_from_camera(scene, cam_obj, solid_obj, solid_bvh, world_pt, eps=1e-3):
    cam_origin_w = cam_obj.matrix_world.translation
    vec = world_pt - cam_origin_w
    dist_w = vec.length
    if dist_w < 1e-9:
        return False

    # BVH expects object space, so transform the ray into object space
    mw = solid_obj.matrix_world
    inv = mw.inverted()

    origin_o = inv @ cam_origin_w
    target_o = inv @ world_pt

    dir_o = target_o - origin_o
    dist_o = dir_o.length
    if dist_o < 1e-9:
        return False
    dir_o.normalize()

    hit_o, normal_o, face_i, hit_dist = solid_bvh.ray_cast(origin_o, dir_o, dist_o)
    if hit_o is None:
        return False

    hit_w = mw @ hit_o
    return (hit_w - world_pt).length <= eps
```

### 3.5 2D segment spacing helpers (to reduce overlaps)

```python
def clamp01(t): 
    return 0.0 if t < 0.0 else 1.0 if t > 1.0 else t

def dist_point_segment(p, a, b):
    ab = b - a
    denom = ab.dot(ab)
    if denom < 1e-9:
        return (p - a).length
    t = clamp01((p - a).dot(ab) / denom)
    proj = a + t * ab
    return (p - proj).length

def dist_segment_segment(a0, a1, b0, b1):
    return min(
        dist_point_segment(a0, b0, b1),
        dist_point_segment(a1, b0, b1),
        dist_point_segment(b0, a0, a1),
        dist_point_segment(b1, a0, a1),
    )
```

### 3.6 Build visible base candidates once

```python
def make_base_candidates(scene, cam_obj, solid_obj, solid_bvh, placement_cfg):
    solid_center = solid_obj.matrix_world.translation

    # projected center (for silhouette bias)
    center_ndc, _ = ndc_and_in_frame(scene, cam_obj, solid_center)
    center_px, _, _ = ndc_to_px(scene, center_ndc)

    allowed_types = set(placement_cfg.get("allowed_site_types", ["FACE", "VERT"]))

    out = []
    for site_type, idx, p_w in gather_candidates(solid_obj):
        if site_type not in allowed_types:
            continue

        base_ndc, base_in = ndc_and_in_frame(scene, cam_obj, p_w)
        if not base_in:
            continue

        if placement_cfg.get("require_visible_base", True):
            if not visible_on_solid_from_camera(scene, cam_obj, solid_obj, solid_bvh, p_w):
                continue

        d = (p_w - solid_center)
        if d.length < 1e-9:
            continue
        d.normalize()

        base_px, _, _ = ndc_to_px(scene, base_ndc)
        silhouette = (base_px - center_px).length

        out.append({
            "site_type": site_type,
            "index": idx,
            "p_w": p_w,
            "d_w": d,
            "base_ndc": base_ndc,
            "base_px": base_px,
            "silhouette": silhouette
        })

    # Sort by silhouette (desc) so greedy tends to pick “outer” points
    out.sort(key=lambda c: c["silhouette"], reverse=True)
    return out
```

### 3.7 Select sites for all cylinders (greedy with restarts)

This version:
- respects per-cylinder `attach.site_type` / `attach.index` if provided,
- otherwise chooses automatically,
- enforces base + segment separation in **pixels**.

```python
import random

def pick_sites_for_cylinders(scene, cam_obj, solid_obj, cyl_specs, base_candidates, placement_cfg, seed):
    rng = random.Random(seed)

    min_base = float(placement_cfg.get("min_base_separation_px", 80))
    min_seg  = float(placement_cfg.get("min_segment_separation_px", 25))
    unique_sites = bool(placement_cfg.get("unique_sites", True))

    bias_sil = float(placement_cfg.get("bias_silhouette", 1.0))
    require_tip = bool(placement_cfg.get("require_tip_in_frame", True))

    restarts = int(placement_cfg.get("restarts", 20))
    jitter = 0.05

    # place larger cylinders first (packing heuristic)
    order = sorted(range(len(cyl_specs)), key=lambda i: cyl_specs[i].get("radius", 0.05), reverse=True)

    best = None
    best_obj = -1e18

    for r in range(restarts):
        used = set()
        placed_segments = []  # list of dicts with base_px, tip_px
        chosen = [None] * len(cyl_specs)

        ok_restart = True

        for i in order:
            spec = cyl_specs[i]

            # If user explicitly provided a site, force it.
            forced_type = spec.get("attach", {}).get("site_type")
            forced_idx  = spec.get("attach", {}).get("index")

            best_c = None
            best_val = -1e18

            for c in base_candidates:
                if forced_type is not None and c["site_type"] != forced_type:
                    continue
                if forced_idx is not None and c["index"] != forced_idx:
                    continue

                key = (c["site_type"], c["index"])
                if unique_sites and key in used:
                    continue

                # compute tip for THIS cylinder length
                L = float(spec.get("length", 1.0))
                tip_w = c["p_w"] + c["d_w"] * L
                tip_ndc, tip_in = ndc_and_in_frame(scene, cam_obj, tip_w)
                if require_tip and not tip_in:
                    continue
                tip_px, _, _ = ndc_to_px(scene, tip_ndc)

                # enforce spacing vs already placed
                base_px = c["base_px"]
                seg_ok = True
                for p in placed_segments:
                    if (base_px - p["base_px"]).length < min_base:
                        seg_ok = False
                        break
                    if dist_segment_segment(base_px, tip_px, p["base_px"], p["tip_px"]) < min_seg:
                        seg_ok = False
                        break
                if not seg_ok:
                    continue

                # score: silhouette + projected segment length
                proj_len = (tip_px - base_px).length
                score = bias_sil * c["silhouette"] + 0.25 * proj_len

                val = score * (1.0 + rng.uniform(-jitter, jitter))
                if val > best_val:
                    best_val = val
                    best_c = dict(c)
                    best_c["tip_w"] = tip_w
                    best_c["tip_px"] = tip_px
                    best_c["score"] = score

                # If forced, we can break early once matched (optional)
                if forced_type is not None and forced_idx is not None and best_c is not None:
                    break

            if best_c is None:
                ok_restart = False
                break

            chosen[i] = best_c
            placed_segments.append({"base_px": best_c["base_px"], "tip_px": best_c["tip_px"]})
            if unique_sites:
                used.add((best_c["site_type"], best_c["index"]))

        if not ok_restart:
            continue

        obj = sum(chosen[i]["score"] for i in range(len(cyl_specs)))
        if obj > best_obj:
            best_obj = obj
            best = chosen

    return best
```

### 3.8 Fallback: relax spacing if placement fails

```python
def auto_pick_sites(scene, cam_obj, solid_obj, cyl_specs, placement_cfg, seed):
    solid_bvh = build_solid_bvh(solid_obj)
    base_candidates = make_base_candidates(scene, cam_obj, solid_obj, solid_bvh, placement_cfg)

    if not base_candidates:
        raise RuntimeError("No valid visible base sites found (try a different camera angle or allow occluded bases).")

    fb = placement_cfg.get("fallback", {})
    steps = int(fb.get("relax_separation_steps", 0))
    min_factor = float(fb.get("min_relaxed_factor", 1.0))

    base0 = float(placement_cfg.get("min_base_separation_px", 80))
    seg0  = float(placement_cfg.get("min_segment_separation_px", 25))

    for s in range(max(1, steps + 1)):
        if steps == 0:
            factor = 1.0
        else:
            t = s / steps
            factor = (1.0 - t) + t * min_factor

        cfg_try = dict(placement_cfg)
        cfg_try["min_base_separation_px"] = base0 * factor
        cfg_try["min_segment_separation_px"] = seg0 * factor

        chosen = pick_sites_for_cylinders(scene, cam_obj, solid_obj, cyl_specs, base_candidates, cfg_try, seed + 1000 * s)
        if chosen is not None:
            return chosen, cfg_try

    raise RuntimeError(
        "Could not place all cylinders with the given constraints. "
        "Try fewer cylinders, rotate the solid/camera, or relax min_*_separation_px."
    )
```

### 3.9 Create cylinders from chosen sites

This keeps cylinders **radial**. The cylinder primitive is aligned to local **Z**, so we rotate it so Z aligns with the radial direction.

```python
import bpy

def add_cylinder_object(spec, center_w, direction_w):
    radius = float(spec.get("radius", 0.05))
    length = float(spec.get("length", 1.0))
    sides  = int(spec.get("sides", 24))

    bpy.ops.mesh.primitive_cylinder_add(
        vertices=sides,
        radius=radius,
        depth=length,
        location=center_w
    )
    obj = bpy.context.active_object
    obj.name = spec.get("id", obj.name)

    # orient local Z axis along direction
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = direction_w.to_track_quat("Z", "Y")
    return obj

def place_cylinder_from_site(solid_obj, cyl_spec, site):
    solid_center = solid_obj.matrix_world.translation

    p = site["p_w"]
    d = site["d_w"]

    L = float(cyl_spec.get("length", 1.0))
    r = float(cyl_spec.get("radius", 0.05))

    base_offset = cyl_spec.get("base_offset", "AUTO")
    if base_offset == "AUTO":
        # slight cushion so you don't see intersection with the solid
        base_offset = r * 1.05
    base_offset = float(base_offset)

    # Cylinder primitive is centered at its origin, so place the origin at:
    # (base + offset) + direction*(L/2)
    center = (p + d * base_offset) + d * (L * 0.5)
    return add_cylinder_object(cyl_spec, center, d)
```

### 3.10 Update cylinder specs with resolved attach info

```python
def write_resolved_attachments_into_specs(cyl_specs, chosen_sites):
    for spec, site in zip(cyl_specs, chosen_sites):
        spec.setdefault("attach", {})
        spec["attach"]["site_type"] = site["site_type"]
        spec["attach"]["index"] = int(site["index"])
```

---

## 4) How to connect everything in your build script

> This shows only the placement & cylinder creation pipeline. You already have scene setup.

```python
def build_scene_from_manifest(manifest: dict):
    scene = bpy.context.scene

    # 1) Create solid (you plug in your existing code)
    solid_obj = create_platonic_solid_from_manifest(manifest["solid"])

    # 2) Create/position camera (you plug in your existing code)
    cam_obj = create_camera_from_manifest(manifest["camera"])

    # 3) Expand cylinders
    cyl_specs = expand_cylinders(manifest)

    # 4) Respect explicitly attached cylinders first (optional)
    # The picker already respects per-cylinder attach if provided.

    # 5) Auto-place if enabled
    ap = manifest["cylinders"].get("auto_placement", {})
    if ap.get("enabled", True):
        chosen_sites, cfg_used = auto_pick_sites(scene, cam_obj, solid_obj, cyl_specs, ap, manifest.get("seed", 0))
        write_resolved_attachments_into_specs(cyl_specs, chosen_sites)
    else:
        # if not auto, you’d expect attach indices to already be present
        chosen_sites = resolve_sites_from_attach_indices(solid_obj, cyl_specs)

    # 6) Create cylinders
    cylinder_objects = []
    for spec, site in zip(cyl_specs, chosen_sites):
        cylinder_objects.append(place_cylinder_from_site(solid_obj, spec, site))

    # 7) (Optional) Write out a resolved manifest file for reproducibility
    # export_resolved_manifest(manifest, cyl_specs, out_path="out/resolved_manifest.json")
```

---

## 5) Practical tuning tips

- If cylinders overlap a lot:
  - raise `min_base_separation_px` to ~120,
  - raise `min_segment_separation_px` to ~40.
- If placement often fails:
  - reduce `min_*` values,
  - increase `fallback.min_relaxed_factor` closer to 0.4,
  - rotate the solid or move the camera slightly.
- If cylinders keep landing behind the solid:
  - ensure `require_visible_base` is `true`,
  - check your camera `look_at` is correct.

---

## 6) Next step later: manual rearrangement

When you want manual edits later, you already have everything you need:
- each cylinder has `attach.site_type` and `attach.index` stored,
- a GUI picker would simply update those fields and rebuild.

(You can add the picker operator later without changing the manifest schema.)

---

**End of template.**
