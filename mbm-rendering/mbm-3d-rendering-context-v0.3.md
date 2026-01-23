# MBM 3D Rendering Context (Polyhedron Wireframes + Rays + Blender Import) — v0.3

This file teaches an LLM how to generate a **single JSON manifest** that can be imported into **Blender** to automatically build a 3D scene and render a **clean 2D documentation image** for the **Mechatronic Boundary Model (MBM)**.

## Goals

1) **Boundary as a wireframe polyhedron** (hollow, visible in 2D): edges are **cylinders**, vertices are **spheres**.  
2) **Ports as radial cylinders** emitted from **polyhedron vertices**:
   - **Power** → solid cylinder
   - **Information** → dashed cylinder (3D dash segments)
3) **Face label rays** emitted from **polyhedron face centers** (radial / face-normal direction).
4) **Endcap “callouts”** at the end of any ray: can include **text**, **image**, and/or **3D model** (STL preferred; STEP supported only if a STEP importer is installed).
5) **Readability contract:** endcap planes are perpendicular to rays and rotated so their in-plane X/Y align to the camera right/up directions.

---

## 1) MBM semantics (what the geometry means)

This renderer visualizes MBM’s core discipline:

- **Entity** → represented by a boundary polyhedron.
- **Boundary crossings are only through ports** (rays).
- Every port crossing is classified as **Power** and/or **Information**.
- Unknowns/TBD must be explicit in the manifest (status fields).

(These are core MBM rules; the diagram is a visualization of the MBM-IS table.)  

---

## 2) Coordinate conventions

- The boundary polyhedron is centered at world origin: **(0, 0, 0)**.
- **Radial direction** for a vertex port is `dir = normalize(vertex_position)`.
- **Face label direction** is the outward face normal. For regular polyhedra centered at origin, `normalize(face_center)` is also acceptable, but the canonical is the face normal.

---

## 3) Visual primitives (renderer contract)

### 3.1 Boundary polyhedron (wireframe)
Represent the polyhedron with:
- spheres at vertices
- cylinders along edges

All thickness is physical 3D radius so it survives 2D rendering.

**Manifest fields (required):**
- `boundary.polyhedron.type` (e.g., `"tetrahedron"`, `"cube"`, `"octahedron"`, `"dodecahedron"`, `"icosahedron"`)
- `boundary.polyhedron.radius.kind` = `"circumradius"` or `"inradius"`
- `boundary.polyhedron.radius.value` = number (world units)
- `boundary.polyhedron.wire_radius` = number (world units)

Notes:
- `circumradius` = distance from center to any vertex
- `inradius` = distance from center to any face plane
- If the renderer uses internal unit geometry, it must scale the polyhedron to match the requested radius kind.

### 3.2 Port rays (power/info)
A port ray is a cylinder starting at a vertex and extending outward radially.

- `flow = "power"` → solid
- `flow = "information"` → dashed
- `flow = "both"` → two parallel rays (power + info) with a small perpendicular offset

Suggested defaults:
- `ray.radius = 0.8 * wire_radius`
- `ray.length = "auto"` → `1.6 * boundary_circumradius` (renderer may extend to reduce overlap)
- `information` dashed segments: `dash_length ≈ 4*ray_radius`, `dash_gap ≈ 2.5*ray_radius`

### 3.3 Face label rays
Face label rays start at the **center of a face** and go outward along the face normal.

Use these to label internal entities, subcomponents, or important internal functions without cluttering the inside volume.

---

## 4) Endcap callouts (text / image / 3D model)

At the end of any ray, you may attach an endcap plane and assets.

### 4.1 Endcap plane placement
- `ray_end = ray_start + ray_dir * ray_length`
- A plane is placed at `ray_end`, with its **normal parallel to ray_dir**.
- The plane normal may be flipped so it faces the camera:
  - choose `n = ray_dir` or `n = -ray_dir` such that `dot(n, camera_pos - ray_end) > 0`

### 4.2 Endcap plane rotation (upright text)
The plane must be rotated so that:
- plane **up axis** aligns with the camera up axis, projected into the plane
- plane **right axis** aligns with the camera right axis, projected into the plane

This makes text/images “upright” in the 2D render.

### 4.3 Text rendering
- Text must be **3D extruded letters** (Blender text object or converted mesh).
- Place text slightly in front of the plane along the plane normal to avoid z-fighting.
- Center-align by default unless manifest overrides.

### 4.4 Images
- Images are mapped as textures onto the endcap plane (emissive/unlit preferred).
- If both image and text exist, default layout is:
  - image centered as background, text overlaid (or image left, text right if `layout="icon_left"`)

### 4.5 3D models (STL / STEP)
- STL should be imported and placed near the endcap (slightly in front of the plane).
- STEP import is **optional** and requires an installed STEP importer add-on.
- If STEP import is unavailable, the renderer should either:
  - skip the model and add a warning in logs, or
  - request a converted mesh file (STL/OBJ/GLB).

---

## 5) Readability heuristics (minimum viable)

- Default camera: orthographic-ish isometric view.
- Prefer assigning high-priority ports to “front-facing” vertices (closest to camera direction).
- Prefer extending ray length to reduce label overlap.

The Blender importer provided with this context implements a simple, deterministic auto placement:
- if `vertex` is missing, it auto-assigns using camera-facing score.

---

## 6) Manifest schema (informal)

The LLM should output a single JSON object like:

```json
{
  "manifest_version": "mbm_render@0.3",
  "style": {
    "colors": {
      "boundary": "#2B2F36",
      "power": "#E07A1F",
      "information": "#2A9D8F",
      "label": "#6C757D",
      "plane": "#FFFFFF",
      "text": "#111111"
    }
  },

  "render": {
    "engine": "BLENDER_EEVEE",
    "output": {"width_px": 2000, "height_px": 1400, "background": "white"},
    "camera": {
      "mode": "auto_isometric",
      "projection": "ORTHO",
      "ortho_scale": 6.0,
      "location": [3.0, -3.0, 2.2],
      "look_at": [0.0, 0.0, 0.0]
    },
    "lights": {"mode": "simple_3point"}
  },

  "boundary": {
    "entity": {"id": "E1", "name": "Entity Name"},
    "polyhedron": {
      "type": "icosahedron",
      "radius": {"kind": "circumradius", "value": 1.0},
      "wire_radius": 0.03
    },

    "ports": [
      {
        "id": "vin",
        "flow": "power",
        "direction": "in",
        "vertex": 0,
        "ray": {"length": "auto", "radius": 0.02},

        "endcap": {
          "plane": {"size": [0.75, 0.42]},
          "assets": [
            {"type": "text", "text": "24V IN", "size": 0.18, "extrude": 0.02},
            {"type": "image", "file": "dc_icon.png"}
          ]
        },

        "status": "specified",
        "priority": 0
      }
    ],

    "face_labels": [
      {
        "id": "mcu",
        "face": "auto",
        "ray": {"length": 0.9, "radius": 0.015},
        "endcap": {"assets": [{"type": "text", "text": "MCU + FW", "size": 0.16, "extrude": 0.02}]},
        "status": "specified",
        "priority": 10
      }
    ]
  }
}
```

### 6.1 Required fields
- `manifest_version`
- `boundary.polyhedron.type`
- `boundary.polyhedron.radius.kind`
- `boundary.polyhedron.radius.value`
- `boundary.polyhedron.wire_radius`

Everything else is optional with defaults.

### 6.2 Asset path rules
All `file` paths are relative to the manifest JSON file’s directory (unless absolute).

### 6.3 Status rules
Use:
- `status="specified"` when the contract is known
- `status="tbd"` when unknown (must still be present)

---

## 7) LLM output rules
When asked to create a renderable figure:

1) Output **only** the JSON manifest (no prose).  
2) Ensure every port has:
   - `flow`, `direction`, `status`
   - `endcap.assets` if the user provided text/image/model
3) Keep ray lengths modest and readable; prefer `ray.length="auto"` unless the user demands numeric.

---

## 8) Blender importer
Use the provided Blender add-on script `mbm_blender_manifest_importer_v0.1.py`:

- Install it in Blender (Preferences → Add-ons → Install… → enable)
- In the 3D Viewport Sidebar (N-panel) open **MBM** tab
- Click **Build from Manifest**, pick the JSON file, and it will build the scene

