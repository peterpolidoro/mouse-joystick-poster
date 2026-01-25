# manifest_tools_addon.py
# Blender Add-on: Manifest Tools (v0.4)
#
# New in v0.4:
#   - Auto-fill Manifest Path and Builder Script Path from Blender command-line args:
#       --python / -P <builder.py>  and  -- --manifest <manifest.json>
#   - "Reload builder on Apply" option (default ON) to avoid stale global caches in builder scripts
#     (fixes: ReferenceError('StructRNA of type Mesh has been removed') when rebuilding repeatedly)
#   - Explicit "Use CLI Paths" operator button
#
# UI locations:
#   - View3D Sidebar (N) -> Tool tab -> Manifest Tools
#   - Properties editor -> Scene tab -> Manifest Tools
#
# Requirements:
#   Your builder script defines:
#     build_scene_from_manifest(manifest: dict, project_root: str, do_render: bool)

bl_info = {
    "name": "Manifest Tools (Boundary/Label)",
    "author": "ChatGPT",
    "version": (0, 4, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Tool ; Properties > Scene",
    "description": "Edit scene manifest in Blender, apply and save for headless renders.",
    "category": "3D View",
}

import bpy
import json
import os
import sys
import importlib.util

from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup, UIList


# -----------------------------
# Globals (debounce + builder cache)
# -----------------------------

_IS_LOADING = False
_UPDATE_TIMER_ACTIVE = False

_BUILDER_CACHE = {
    "path": None,
    "module": None,
    "mod_name": "_manifest_builder_module",
}


# -----------------------------
# Utility
# -----------------------------

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _rgb_to_hex(rgb):
    r = int(_clamp01(rgb[0]) * 255 + 0.5)
    g = int(_clamp01(rgb[1]) * 255 + 0.5)
    b = int(_clamp01(rgb[2]) * 255 + 0.5)
    return "#{:02X}{:02X}{:02X}".format(r, g, b)


def _parse_color_rgb(value, default=(1.0, 1.0, 1.0)):
    if value is None:
        return default
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("#"):
            s = s[1:]
        if len(s) == 6:
            try:
                r = int(s[0:2], 16) / 255.0
                g = int(s[2:4], 16) / 255.0
                b = int(s[4:6], 16) / 255.0
                return (_clamp01(r), _clamp01(g), _clamp01(b))
            except Exception:
                return default
        return default
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        r, g, b = float(value[0]), float(value[1]), float(value[2])
        if max(r, g, b) > 1.0:
            r, g, b = r / 255.0, g / 255.0, b / 255.0
        return (_clamp01(r), _clamp01(g), _clamp01(b))
    return default


def _abspath_from_cwd(p: str) -> str:
    if not p:
        return ""
    p = bpy.path.abspath(p)
    if os.path.isabs(p):
        return os.path.abspath(p)
    # relative: interpret relative to current working directory (matches typical CLI usage)
    return os.path.abspath(os.path.join(os.getcwd(), p))


def _guess_builder_path(manifest_path: str) -> str:
    if not manifest_path:
        return ""
    d = os.path.dirname(os.path.abspath(manifest_path))
    cand = os.path.join(d, "scripts", "setup_scene.py")
    if os.path.exists(cand):
        return cand
    return ""


def _parse_cli_paths() -> tuple[str, str]:
    """
    Extract (builder_path, manifest_path) from Blender's sys.argv.
    We support:
      blender --python path/to/setup_scene.py -- --manifest path/to/manifest.json
      blender -P path/to/setup_scene.py -- --manifest path/to/manifest.json

    Also supports --manifest=... form.
    """
    argv = list(sys.argv)
    builder = ""
    manifest = ""

    # Builder path: --python or -P
    for i, a in enumerate(argv):
        if a in ("--python", "-P"):
            if i + 1 < len(argv):
                builder = argv[i + 1]

    # Manifest path: --manifest or --manifest=...
    for i, a in enumerate(argv):
        if a == "--manifest" and i + 1 < len(argv):
            manifest = argv[i + 1]
        elif a.startswith("--manifest="):
            manifest = a.split("=", 1)[1]

    return builder, manifest


def _load_builder_module(builder_path: str, force_reload: bool = False):
    global _BUILDER_CACHE
    builder_path = os.path.abspath(builder_path)

    mod_name = _BUILDER_CACHE["mod_name"]

    # If same path and cached, reuse unless force_reload
    if (
        not force_reload
        and _BUILDER_CACHE["module"] is not None
        and _BUILDER_CACHE["path"] == builder_path
    ):
        return _BUILDER_CACHE["module"]

    if not os.path.exists(builder_path):
        raise FileNotFoundError(f"Builder script not found: {builder_path}")

    # Remove old module from sys.modules to truly reload and clear its globals (mesh caches, etc.)
    if mod_name in sys.modules:
        try:
            del sys.modules[mod_name]
        except Exception:
            pass

    spec = importlib.util.spec_from_file_location(mod_name, builder_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to import builder module from: {builder_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)  # type: ignore

    _BUILDER_CACHE["path"] = builder_path
    _BUILDER_CACHE["module"] = module
    return module


def _schedule_live_update(context):
    global _UPDATE_TIMER_ACTIVE
    if _IS_LOADING:
        return
    scene = context.scene
    props = scene.manifest_tools
    if not props.live_update:
        return
    if _UPDATE_TIMER_ACTIVE:
        return

    _UPDATE_TIMER_ACTIVE = True

    def _timer():
        global _UPDATE_TIMER_ACTIVE
        _UPDATE_TIMER_ACTIVE = False
        try:
            apply_scene_from_props(bpy.context, safe=True)
        except Exception as e:
            print("[Manifest Tools] Live update failed:", repr(e))
        return None

    bpy.app.timers.register(_timer, first_interval=max(0.05, float(props.live_update_delay)))


def _on_prop_update(self, context):
    _schedule_live_update(context)


# -----------------------------
# Property Groups
# -----------------------------

class MT_BoundaryProps(PropertyGroup):
    name: StringProperty(name="Name", default="boundary", update=_on_prop_update)

    shape_type: EnumProperty(
        name="Shape",
        items=[
            ("icosahedron", "Icosahedron", ""),
            ("icosphere", "Icosphere", ""),
            ("tetrahedron", "Tetrahedron", ""),
            ("cube", "Cube", ""),
            ("octahedron", "Octahedron", ""),
            ("dodecahedron", "Dodecahedron", ""),
        ],
        default="icosahedron",
        update=_on_prop_update,
    )
    subdivisions: IntProperty(name="Subdivisions", default=0, min=0, max=6, update=_on_prop_update)
    radius: FloatProperty(name="Radius", default=1.25, min=0.001, soft_max=10.0, update=_on_prop_update)

    # Edges
    edge_radius: FloatProperty(name="Radius", default=0.05, min=0.0001, soft_max=1.0, update=_on_prop_update)
    edge_color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, default=(0.0, 1.0, 0.4), min=0.0, max=1.0, update=_on_prop_update)
    edge_alpha: FloatProperty(name="Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)

    # Vertices
    vertex_radius: FloatProperty(name="Radius", default=0.08, min=0.0001, soft_max=1.0, update=_on_prop_update)
    vertex_color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, default=(1.0, 0.0, 1.0), min=0.0, max=1.0, update=_on_prop_update)
    vertex_alpha: FloatProperty(name="Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)

    # Faces
    face_thickness: FloatProperty(name="Thickness", default=0.03, min=0.0, soft_max=1.0, update=_on_prop_update)
    face_color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, default=(0.0, 1.0, 1.0), min=0.0, max=1.0, update=_on_prop_update)
    face_alpha: FloatProperty(name="Alpha", default=0.10, min=0.0, max=1.0, update=_on_prop_update)

    # Details
    edge_cylinder_sides: IntProperty(name="Edge Sides", default=24, min=3, max=128, update=_on_prop_update)
    vertex_sphere_segments: IntProperty(name="Sphere Segments", default=32, min=3, max=128, update=_on_prop_update)
    vertex_sphere_rings: IntProperty(name="Sphere Rings", default=16, min=3, max=128, update=_on_prop_update)
    edge_coplanar_dot: FloatProperty(
        name="Coplanar Dot",
        default=0.999999,
        min=0.9,
        max=1.0,
        precision=6,
        update=_on_prop_update,
        description="Remove triangulation diagonals by treating shared triangle edges as internal if normals are coplanar (dot close to 1).",
    )


class MT_CameraProps(PropertyGroup):
    lens_mm: FloatProperty(name="Lens (mm)", default=50.0, min=1.0, max=300.0, update=_on_prop_update)
    distance: FloatProperty(name="Distance", default=4.8, min=0.1, soft_max=50.0, update=_on_prop_update)

    use_location: BoolProperty(name="Explicit Location", default=False, update=_on_prop_update)
    location: FloatVectorProperty(name="Location", size=3, subtype="TRANSLATION", default=(0.0, -4.8, 1.8), update=_on_prop_update)

    target_mode: EnumProperty(
        name="Target",
        items=[
            ("AUTO", "AUTO (Boundary Center)", ""),
            ("CUSTOM", "Custom", ""),
        ],
        default="AUTO",
        update=_on_prop_update,
    )
    target: FloatVectorProperty(name="Target", size=3, subtype="TRANSLATION", default=(0.0, 0.0, 0.0), update=_on_prop_update)


class MT_LabelProps(PropertyGroup):
    name: StringProperty(name="Name", default="label_01", update=_on_prop_update)
    target: StringProperty(name="Target Boundary", default="boundary", update=_on_prop_update)

    attach_face_index: IntProperty(
        name="Face Index",
        default=-1,
        min=-1,
        description="-1 means auto-select a visible face",
        update=_on_prop_update,
    )

    # Cylinder
    cyl_radius: FloatProperty(name="Radius", default=0.03, min=0.0001, soft_max=1.0, update=_on_prop_update)

    cyl_length_mode: EnumProperty(
        name="Length",
        items=[("AUTO", "AUTO", ""), ("FIXED", "Fixed", "")],
        default="AUTO",
        update=_on_prop_update,
    )
    cyl_length: FloatProperty(name="Fixed", default=1.2, min=0.01, soft_max=10.0, update=_on_prop_update)
    cyl_length_min: FloatProperty(name="Min", default=0.6, min=0.01, soft_max=10.0, update=_on_prop_update)
    cyl_length_max: FloatProperty(name="Max", default=2.8, min=0.01, soft_max=20.0, update=_on_prop_update)

    cyl_color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, default=(1.0, 1.0, 1.0), min=0.0, max=1.0, update=_on_prop_update)
    cyl_alpha: FloatProperty(name="Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)

    # Text
    text_value: StringProperty(name="Text", default="Icosahedron", update=_on_prop_update)
    text_size: FloatProperty(name="Size", default=0.30, min=0.01, soft_max=2.0, update=_on_prop_update)
    text_color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, default=(1.0, 1.0, 1.0), min=0.0, max=1.0, update=_on_prop_update)
    text_alpha: FloatProperty(name="Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)
    font_path: StringProperty(name="Font", subtype="FILE_PATH", default="", update=_on_prop_update)

    # Image
    image_filepath: StringProperty(name="Image", subtype="FILE_PATH", default="", update=_on_prop_update)
    image_height: FloatProperty(name="Height", default=0.55, min=0.01, soft_max=5.0, update=_on_prop_update)
    image_alpha: FloatProperty(name="Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)


class MT_ToolsProps(PropertyGroup):
    manifest_path: StringProperty(name="Manifest Path", subtype="FILE_PATH", default="")
    builder_path: StringProperty(
        name="Builder Script",
        subtype="FILE_PATH",
        default="",
        description="Path to setup_scene.py that provides build_scene_from_manifest(). Leave blank to auto-guess relative to manifest.",
    )

    # New in v0.4
    reload_builder_each_apply: BoolProperty(
        name="Reload Builder on Apply",
        default=True,
        description="Reloads the builder python module on every Apply to clear its global caches (recommended).",
    )

    live_update: BoolProperty(
        name="Live Update",
        default=False,
        description="When enabled, applying is triggered automatically (debounced) when you change any property.",
    )
    live_update_delay: FloatProperty(
        name="Delay (s)",
        default=0.25,
        min=0.05,
        max=2.0,
        description="Debounce delay for Live Update",
    )

    raw_manifest_json: StringProperty(name="(internal) raw manifest", default="", options={'HIDDEN'})
    last_good_manifest_json: StringProperty(name="(internal) last good manifest", default="", options={'HIDDEN'})
    last_status: StringProperty(name="(internal) last status", default="", options={'HIDDEN'})

    boundary: PointerProperty(type=MT_BoundaryProps)
    camera: PointerProperty(type=MT_CameraProps)

    labels: CollectionProperty(type=MT_LabelProps)
    active_label_index: IntProperty(name="Active Label", default=0)


# -----------------------------
# Manifest ↔ props conversion
# -----------------------------

def _find_object(manifest: dict, name: str = None, type_name: str = None):
    objs = manifest.get("objects", [])
    if not isinstance(objs, list):
        return None
    for o in objs:
        if not isinstance(o, dict):
            continue
        if name is not None and o.get("name") != name:
            continue
        if type_name is not None and str(o.get("type", "")).lower() != str(type_name).lower():
            continue
        return o
    return None


def _find_objects(manifest: dict, type_name: str):
    objs = manifest.get("objects", [])
    if not isinstance(objs, list):
        return []
    out = []
    for o in objs:
        if isinstance(o, dict) and str(o.get("type", "")).lower() == str(type_name).lower():
            out.append(o)
    return out


def _ensure_object(manifest: dict, name: str, type_name: str) -> dict:
    objs = manifest.setdefault("objects", [])
    if not isinstance(objs, list):
        manifest["objects"] = []
        objs = manifest["objects"]
    for o in objs:
        if isinstance(o, dict) and o.get("name") == name:
            if "type" not in o:
                o["type"] = type_name
            return o
    o = {"name": name, "type": type_name}
    objs.append(o)
    return o


def load_manifest_into_props(manifest: dict, props: MT_ToolsProps):
    global _IS_LOADING
    _IS_LOADING = True
    try:
        b = _find_object(manifest, name=props.boundary.name, type_name="boundary")
        if b is None:
            bs = _find_objects(manifest, "boundary")
            b = bs[0] if bs else None

        if b is not None:
            props.boundary.name = str(b.get("name", props.boundary.name))
            props.boundary.radius = float(b.get("radius", props.boundary.radius))

            shape = b.get("shape", {}) if isinstance(b.get("shape", {}), dict) else {}
            props.boundary.shape_type = str(shape.get("type", props.boundary.shape_type)).lower()
            props.boundary.subdivisions = int(shape.get("subdivisions", props.boundary.subdivisions) or 0)

            edges = b.get("edges", {}) if isinstance(b.get("edges", {}), dict) else {}
            props.boundary.edge_radius = float(edges.get("radius", props.boundary.edge_radius))
            props.boundary.edge_color = _parse_color_rgb(edges.get("color"), props.boundary.edge_color)
            props.boundary.edge_alpha = float(edges.get("alpha", props.boundary.edge_alpha))

            verts = b.get("vertices", b.get("verticies", {}))
            verts = verts if isinstance(verts, dict) else {}
            props.boundary.vertex_radius = float(verts.get("radius", props.boundary.vertex_radius))
            props.boundary.vertex_color = _parse_color_rgb(verts.get("color"), props.boundary.vertex_color)
            props.boundary.vertex_alpha = float(verts.get("alpha", props.boundary.vertex_alpha))

            faces = b.get("faces", {}) if isinstance(b.get("faces", {}), dict) else {}
            props.boundary.face_thickness = float(faces.get("thickness", props.boundary.face_thickness))
            props.boundary.face_color = _parse_color_rgb(faces.get("color"), props.boundary.face_color)
            props.boundary.face_alpha = float(faces.get("alpha", props.boundary.face_alpha))

            detail = b.get("detail", b.get("details", {}))
            detail = detail if isinstance(detail, dict) else {}
            props.boundary.edge_cylinder_sides = int(detail.get("edge_cylinder_sides", props.boundary.edge_cylinder_sides))
            props.boundary.vertex_sphere_segments = int(detail.get("vertex_sphere_segments", props.boundary.vertex_sphere_segments))
            props.boundary.vertex_sphere_rings = int(detail.get("vertex_sphere_rings", props.boundary.vertex_sphere_rings))
            props.boundary.edge_coplanar_dot = float(detail.get("edge_coplanar_dot", props.boundary.edge_coplanar_dot))

        # Camera
        cam = manifest.get("camera", {}) if isinstance(manifest.get("camera", {}), dict) else {}
        props.camera.lens_mm = float(cam.get("lens_mm", props.camera.lens_mm))
        props.camera.distance = float(cam.get("distance", props.camera.distance))

        if isinstance(cam.get("location", None), (list, tuple)) and len(cam.get("location")) >= 3:
            props.camera.use_location = True
            loc = cam.get("location")
            props.camera.location = (float(loc[0]), float(loc[1]), float(loc[2]))
        else:
            props.camera.use_location = False

        tgt = cam.get("target", "AUTO")
        if isinstance(tgt, str) and tgt.upper() == "AUTO":
            props.camera.target_mode = "AUTO"
        elif isinstance(tgt, (list, tuple)) and len(tgt) >= 3:
            props.camera.target_mode = "CUSTOM"
            props.camera.target = (float(tgt[0]), float(tgt[1]), float(tgt[2]))
        else:
            props.camera.target_mode = "AUTO"

        # Labels
        props.labels.clear()
        lbls = _find_objects(manifest, "label")
        for l in lbls:
            item = props.labels.add()
            item.name = str(l.get("name", "label"))
            item.target = str(l.get("target", props.boundary.name))

            attach = l.get("attach", {}) if isinstance(l.get("attach", {}), dict) else {}
            idx = attach.get("index", None)
            item.attach_face_index = int(idx) if idx is not None else -1

            cyl = l.get("cylinder", {}) if isinstance(l.get("cylinder", {}), dict) else {}
            item.cyl_radius = float(cyl.get("radius", item.cyl_radius))
            ln = cyl.get("length", "AUTO")
            if isinstance(ln, (int, float)):
                item.cyl_length_mode = "FIXED"
                item.cyl_length = float(ln)
            else:
                item.cyl_length_mode = "AUTO"
            item.cyl_length_min = float(cyl.get("length_min", item.cyl_length_min))
            item.cyl_length_max = float(cyl.get("length_max", item.cyl_length_max))
            item.cyl_color = _parse_color_rgb(cyl.get("color"), item.cyl_color)
            item.cyl_alpha = float(cyl.get("alpha", item.cyl_alpha))

            txt = l.get("text", {}) if isinstance(l.get("text", {}), dict) else {}
            item.text_value = str(txt.get("value", item.text_value))
            item.text_size = float(txt.get("size", item.text_size))
            item.text_color = _parse_color_rgb(txt.get("color"), item.text_color)
            item.text_alpha = float(txt.get("alpha", item.text_alpha))
            item.font_path = str(txt.get("font", "") or "")

            img = l.get("image", {}) if isinstance(l.get("image", {}), dict) else {}
            item.image_filepath = str(img.get("filepath", "") or "")
            item.image_height = float(img.get("height", item.image_height))
            item.image_alpha = float(img.get("alpha", item.image_alpha))

        props.active_label_index = 0 if len(props.labels) > 0 else -1

    finally:
        _IS_LOADING = False


def update_manifest_from_props(manifest: dict, props: MT_ToolsProps) -> dict:
    # Boundary
    b = _ensure_object(manifest, props.boundary.name, "boundary")
    b["radius"] = float(props.boundary.radius)
    b["shape"] = {"type": props.boundary.shape_type, "subdivisions": int(props.boundary.subdivisions)}
    b["edges"] = {"radius": float(props.boundary.edge_radius), "color": _rgb_to_hex(props.boundary.edge_color), "alpha": float(props.boundary.edge_alpha)}
    b["vertices"] = {"radius": float(props.boundary.vertex_radius), "color": _rgb_to_hex(props.boundary.vertex_color), "alpha": float(props.boundary.vertex_alpha)}
    b["faces"] = {"thickness": float(props.boundary.face_thickness), "color": _rgb_to_hex(props.boundary.face_color), "alpha": float(props.boundary.face_alpha)}
    b["detail"] = {
        "edge_cylinder_sides": int(props.boundary.edge_cylinder_sides),
        "vertex_sphere_segments": int(props.boundary.vertex_sphere_segments),
        "vertex_sphere_rings": int(props.boundary.vertex_sphere_rings),
        "edge_coplanar_dot": float(props.boundary.edge_coplanar_dot),
    }

    # Camera
    cam = manifest.setdefault("camera", {})
    if not isinstance(cam, dict):
        manifest["camera"] = {}
        cam = manifest["camera"]
    cam["lens_mm"] = float(props.camera.lens_mm)
    cam["distance"] = float(props.camera.distance)
    if props.camera.use_location:
        cam["location"] = [float(props.camera.location[0]), float(props.camera.location[1]), float(props.camera.location[2])]
    else:
        if "location" in cam:
            del cam["location"]
    cam["target"] = "AUTO" if props.camera.target_mode == "AUTO" else [float(props.camera.target[0]), float(props.camera.target[1]), float(props.camera.target[2])]

    # Labels
    objs = manifest.get("objects", [])
    if not isinstance(objs, list):
        objs = []
        manifest["objects"] = objs

    existing = {}
    for o in objs:
        if isinstance(o, dict) and str(o.get("type", "")).lower() == "label":
            existing[str(o.get("name", ""))] = o

    for item in props.labels:
        l = existing.get(item.name)
        if l is None:
            l = {"name": item.name, "type": "label"}
            objs.append(l)
            existing[item.name] = l

        l["target"] = str(item.target or props.boundary.name)

        attach = l.setdefault("attach", {})
        if not isinstance(attach, dict):
            l["attach"] = {}
            attach = l["attach"]
        attach["site_type"] = "FACE"
        attach["index"] = None if int(item.attach_face_index) < 0 else int(item.attach_face_index)

        cyl = l.setdefault("cylinder", {})
        if not isinstance(cyl, dict):
            l["cylinder"] = {}
            cyl = l["cylinder"]
        cyl["radius"] = float(item.cyl_radius)
        cyl["color"] = _rgb_to_hex(item.cyl_color)
        cyl["alpha"] = float(item.cyl_alpha)
        cyl.setdefault("sides", 24)
        if item.cyl_length_mode == "FIXED":
            cyl["length"] = float(item.cyl_length)
        else:
            cyl["length"] = "AUTO"
        cyl["length_min"] = float(item.cyl_length_min)
        cyl["length_max"] = float(item.cyl_length_max)

        txt = l.setdefault("text", {})
        if not isinstance(txt, dict):
            l["text"] = {}
            txt = l["text"]
        txt["value"] = str(item.text_value)
        txt["size"] = float(item.text_size)
        txt["color"] = _rgb_to_hex(item.text_color)
        txt["alpha"] = float(item.text_alpha)
        txt["font"] = item.font_path if item.font_path.strip() else None
        txt.setdefault("extrude", 0.0)
        txt.setdefault("align_x", "CENTER")

        img = l.setdefault("image", {})
        if not isinstance(img, dict):
            l["image"] = {}
            img = l["image"]
        img["filepath"] = item.image_filepath if item.image_filepath.strip() else None
        img["height"] = float(item.image_height)
        img["alpha"] = float(item.image_alpha)

        l.setdefault("auto_placement", {"enabled": True})
        l.setdefault("board", {"gap": "AUTO"})
        l.setdefault("layout", {"image_above_text": True, "spacing": 0.05, "padding": 0.04})

    return manifest


# -----------------------------
# Apply + Save
# -----------------------------

def _load_json_str(s: str) -> dict:
    if not s.strip():
        return {"manifest_version": 1, "objects": []}
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return {"manifest_version": 1, "objects": []}


def apply_scene_from_props(context, safe: bool = True):
    scene = context.scene
    props = scene.manifest_tools

    if not props.manifest_path.strip():
        raise RuntimeError("Manifest Path is empty.")

    manifest_path = _abspath_from_cwd(props.manifest_path)
    project_root = os.path.dirname(manifest_path)

    builder_path = props.builder_path.strip()
    builder_path = _abspath_from_cwd(builder_path) if builder_path else ""
    if not builder_path:
        builder_path = _guess_builder_path(manifest_path)
    if not builder_path:
        raise RuntimeError("Builder Script not set, and auto-guess failed. Set it in the panel.")

    base_manifest = _load_json_str(props.raw_manifest_json)
    new_manifest = update_manifest_from_props(base_manifest, props)

    props.raw_manifest_json = json.dumps(new_manifest, indent=2)

    last_good = _load_json_str(props.last_good_manifest_json) if props.last_good_manifest_json.strip() else None

    def _run_build(manifest_obj: dict, force_reload: bool):
        module = _load_builder_module(builder_path, force_reload=force_reload)
        if not hasattr(module, "build_scene_from_manifest"):
            raise RuntimeError(f"Builder {builder_path} does not define build_scene_from_manifest().")
        module.build_scene_from_manifest(manifest_obj, project_root=project_root, do_render=False)

    force_reload = bool(props.reload_builder_each_apply)

    try:
        _run_build(new_manifest, force_reload=force_reload)
        props.last_good_manifest_json = props.raw_manifest_json
        props.last_status = "Applied OK"
    except ReferenceError as e:
        # Very common when builder caches meshes and then deletes them on rebuild.
        # Retry once with a forced reload (clears builder globals).
        props.last_status = f"Apply FAILED (ReferenceError): {e!r} — retrying with reload"
        try:
            _run_build(new_manifest, force_reload=True)
            props.last_good_manifest_json = props.raw_manifest_json
            props.last_status = "Applied OK (after reload retry)"
            return
        except Exception as e2:
            props.last_status = f"Apply FAILED after reload retry: {e2!r}"
            if safe and last_good is not None:
                try:
                    _run_build(last_good, force_reload=True)
                    props.last_status += " (restored last good)"
                except Exception as e3:
                    props.last_status += f" (restore failed: {e3!r})"
            raise
    except Exception as e:
        props.last_status = f"Apply FAILED: {e!r}"
        if safe and last_good is not None:
            try:
                _run_build(last_good, force_reload=True)
                props.last_status += " (restored last good)"
            except Exception as e2:
                props.last_status += f" (restore failed: {e2!r})"
        raise


def save_manifest_from_props(context):
    scene = context.scene
    props = scene.manifest_tools
    if not props.manifest_path.strip():
        raise RuntimeError("Manifest Path is empty.")

    manifest_path = _abspath_from_cwd(props.manifest_path)

    base_manifest = _load_json_str(props.raw_manifest_json)
    manifest = update_manifest_from_props(base_manifest, props)

    txt = json.dumps(manifest, indent=2)
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(txt)

    props.raw_manifest_json = txt
    props.last_good_manifest_json = txt
    props.last_status = "Saved"


# -----------------------------
# CLI fill
# -----------------------------

def fill_paths_from_cli(props: MT_ToolsProps) -> bool:
    builder_cli, manifest_cli = _parse_cli_paths()
    changed = False

    if manifest_cli and not props.manifest_path.strip():
        props.manifest_path = _abspath_from_cwd(manifest_cli)
        changed = True

    if builder_cli and not props.builder_path.strip():
        props.builder_path = _abspath_from_cwd(builder_cli)
        changed = True

    # If manifest is set but builder isn't, try guessing
    if props.manifest_path.strip() and not props.builder_path.strip():
        guess = _guess_builder_path(_abspath_from_cwd(props.manifest_path))
        if guess:
            props.builder_path = guess
            changed = True

    return changed


# -----------------------------
# Operators
# -----------------------------

class MT_OT_UseCLIPaths(Operator):
    bl_idname = "mt.use_cli_paths"
    bl_label = "Use CLI Paths"
    bl_description = "Fill Manifest/Builder paths from Blender command-line args (--python/-P and -- --manifest ...)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.manifest_tools
        ok = fill_paths_from_cli(props)
        props.last_status = "Filled paths from CLI" if ok else "No CLI paths found / nothing changed"
        return {'FINISHED'}


class MT_OT_LoadManifest(Operator):
    bl_idname = "mt.load_manifest"
    bl_label = "Load"
    bl_description = "Load manifest.json into UI properties"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.manifest_tools

        # if user hasn't set paths yet, try CLI fill
        fill_paths_from_cli(props)

        if not props.manifest_path.strip():
            self.report({'ERROR'}, "Manifest Path is empty.")
            return {'CANCELLED'}

        path = _abspath_from_cwd(props.manifest_path)
        if not os.path.exists(path):
            self.report({'ERROR'}, f"Manifest not found: {path}")
            return {'CANCELLED'}

        try:
            with open(path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            props.raw_manifest_json = json.dumps(manifest, indent=2)
            props.last_good_manifest_json = props.raw_manifest_json
            props.last_status = "Loaded"
            if not props.builder_path.strip():
                guess = _guess_builder_path(path)
                if guess:
                    props.builder_path = guess
            load_manifest_into_props(manifest, props)
        except Exception as e:
            props.last_status = f"Load FAILED: {e!r}"
            self.report({'ERROR'}, f"Failed to load manifest: {e!r}")
            return {'CANCELLED'}

        return {'FINISHED'}


class MT_OT_ApplyScene(Operator):
    bl_idname = "mt.apply_scene"
    bl_label = "Apply"
    bl_description = "Rebuild scene from current UI properties (via builder script)"
    bl_options = {'REGISTER', 'UNDO'}

    safe: BoolProperty(
        name="Safe Apply",
        default=True,
        description="If Apply fails and the scene was cleared, restore the last good build.",
    )

    def execute(self, context):
        try:
            apply_scene_from_props(context, safe=bool(self.safe))
        except Exception as e:
            self.report({'ERROR'}, f"Apply failed: {e!r} (see Status)")
            return {'CANCELLED'}
        self.report({'INFO'}, "Applied.")
        return {'FINISHED'}


class MT_OT_SaveManifest(Operator):
    bl_idname = "mt.save_manifest"
    bl_label = "Save"
    bl_description = "Write current UI properties back into manifest.json"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            save_manifest_from_props(context)
        except Exception as e:
            self.report({'ERROR'}, f"Save failed: {e!r}")
            return {'CANCELLED'}
        self.report({'INFO'}, "Manifest saved.")
        return {'FINISHED'}


class MT_OT_CaptureCameraLocation(Operator):
    bl_idname = "mt.capture_camera_location"
    bl_label = "Capture Camera Location"
    bl_description = "Copy current scene camera location into UI (enables explicit location)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.manifest_tools
        cam = context.scene.camera
        if cam is None:
            self.report({'ERROR'}, "Scene has no active camera.")
            return {'CANCELLED'}

        props.camera.use_location = True
        props.camera.location = (cam.location.x, cam.location.y, cam.location.z)
        props.last_status = "Captured camera location"
        return {'FINISHED'}


class MT_OT_AddLabel(Operator):
    bl_idname = "mt.add_label"
    bl_label = "Add Label"
    bl_description = "Add a new label to the manifest UI"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.manifest_tools
        idx = len(props.labels) + 1
        item = props.labels.add()
        item.name = f"label_{idx:02d}"
        item.target = props.boundary.name
        props.active_label_index = len(props.labels) - 1
        props.last_status = f"Added {item.name}"
        return {'FINISHED'}


class MT_OT_RemoveLabel(Operator):
    bl_idname = "mt.remove_label"
    bl_label = "Remove Label"
    bl_description = "Remove selected label from UI"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.manifest_tools
        i = props.active_label_index
        if i < 0 or i >= len(props.labels):
            return {'CANCELLED'}
        name = props.labels[i].name
        props.labels.remove(i)
        props.active_label_index = min(max(0, i - 1), len(props.labels) - 1)
        props.last_status = f"Removed {name}"
        return {'FINISHED'}


# -----------------------------
# UI List + Panels
# -----------------------------

class MT_UL_LabelList(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.prop(item, "name", text="", emboss=False, icon='OUTLINER_OB_FONT')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="")


def _draw_header(layout, props):
    row = layout.row(align=True)
    row.operator("mt.use_cli_paths", icon="IMPORT")

    row.separator()

    row.operator("mt.load_manifest", icon="FILE_REFRESH")
    row.operator("mt.save_manifest", icon="FILE_TICK")
    op = row.operator("mt.apply_scene", icon="PLAY")
    op.safe = True

    if props.last_status:
        box = layout.box()
        box.label(text=f"Status: {props.last_status}")


class MT_PT_ManifestToolsRoot(Panel):
    bl_label = "Manifest Tools"
    bl_idname = "MT_PT_manifest_tools_root"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"

    def draw(self, context):
        layout = self.layout
        props = context.scene.manifest_tools
        layout.use_property_split = True
        layout.use_property_decorate = False

        _draw_header(layout, props)

        box = layout.box()
        box.label(text="Files", icon="FILE_FOLDER")
        box.prop(props, "manifest_path")
        box.prop(props, "builder_path")
        box.prop(props, "reload_builder_each_apply")

        row = layout.row(align=True)
        row.prop(props, "live_update")
        row.prop(props, "live_update_delay")


class MT_PT_Boundary(Panel):
    bl_label = "Boundary"
    bl_idname = "MT_PT_manifest_tools_boundary"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"
    bl_parent_id = "MT_PT_manifest_tools_root"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.manifest_tools
        b = props.boundary

        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(b, "name")
        layout.prop(b, "shape_type")
        layout.prop(b, "subdivisions")
        layout.prop(b, "radius")

        col = layout.column(align=True)
        col.separator()
        col.label(text="Edges")
        col.prop(b, "edge_radius")
        col.prop(b, "edge_color")
        col.prop(b, "edge_alpha")

        col = layout.column(align=True)
        col.separator()
        col.label(text="Vertices")
        col.prop(b, "vertex_radius")
        col.prop(b, "vertex_color")
        col.prop(b, "vertex_alpha")

        col = layout.column(align=True)
        col.separator()
        col.label(text="Faces")
        col.prop(b, "face_thickness")
        col.prop(b, "face_color")
        col.prop(b, "face_alpha")

        col = layout.column(align=True)
        col.separator()
        col.label(text="Detail")
        col.prop(b, "edge_cylinder_sides")
        col.prop(b, "vertex_sphere_segments")
        col.prop(b, "vertex_sphere_rings")
        col.prop(b, "edge_coplanar_dot")


class MT_PT_Camera(Panel):
    bl_label = "Camera"
    bl_idname = "MT_PT_manifest_tools_camera"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"
    bl_parent_id = "MT_PT_manifest_tools_root"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.manifest_tools
        c = props.camera

        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(c, "lens_mm")
        layout.prop(c, "distance")
        layout.prop(c, "use_location")

        if c.use_location:
            layout.prop(c, "location")
            layout.operator("mt.capture_camera_location", icon="OUTLINER_OB_CAMERA")

        layout.prop(c, "target_mode")
        if c.target_mode == "CUSTOM":
            layout.prop(c, "target")


class MT_PT_Labels(Panel):
    bl_label = "Labels"
    bl_idname = "MT_PT_manifest_tools_labels"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"
    bl_parent_id = "MT_PT_manifest_tools_root"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.manifest_tools

        layout.use_property_split = True
        layout.use_property_decorate = False

        row = layout.row()
        row.template_list("MT_UL_LabelList", "", props, "labels", props, "active_label_index", rows=3)
        col = row.column(align=True)
        col.operator("mt.add_label", icon="ADD", text="")
        col.operator("mt.remove_label", icon="REMOVE", text="")

        i = props.active_label_index
        if 0 <= i < len(props.labels):
            l = props.labels[i]
            layout.separator()
            layout.prop(l, "name")
            layout.prop(l, "target")
            layout.prop(l, "attach_face_index")

            box = layout.box()
            box.label(text="Cylinder")
            box.prop(l, "cyl_radius")
            box.prop(l, "cyl_color")
            box.prop(l, "cyl_alpha")
            box.prop(l, "cyl_length_mode")
            if l.cyl_length_mode == "FIXED":
                box.prop(l, "cyl_length")
            box.prop(l, "cyl_length_min")
            box.prop(l, "cyl_length_max")

            box = layout.box()
            box.label(text="Text")
            box.prop(l, "text_value")
            box.prop(l, "text_size")
            box.prop(l, "text_color")
            box.prop(l, "text_alpha")
            box.prop(l, "font_path")

            box = layout.box()
            box.label(text="Image")
            box.prop(l, "image_filepath")
            box.prop(l, "image_height")
            box.prop(l, "image_alpha")


class MT_PT_ManifestToolsScene(Panel):
    bl_label = "Manifest Tools"
    bl_idname = "MT_PT_manifest_tools_scene"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    def draw(self, context):
        layout = self.layout
        props = context.scene.manifest_tools
        layout.use_property_split = True
        layout.use_property_decorate = False
        _draw_header(layout, props)

        box = layout.box()
        box.label(text="Files", icon="FILE_FOLDER")
        box.prop(props, "manifest_path")
        box.prop(props, "builder_path")
        box.prop(props, "reload_builder_each_apply")


# -----------------------------
# Register / Unregister
# -----------------------------

classes = (
    MT_BoundaryProps,
    MT_CameraProps,
    MT_LabelProps,
    MT_ToolsProps,

    MT_OT_UseCLIPaths,
    MT_OT_LoadManifest,
    MT_OT_SaveManifest,
    MT_OT_ApplyScene,
    MT_OT_CaptureCameraLocation,
    MT_OT_AddLabel,
    MT_OT_RemoveLabel,

    MT_UL_LabelList,

    MT_PT_ManifestToolsRoot,
    MT_PT_Boundary,
    MT_PT_Camera,
    MT_PT_Labels,
    MT_PT_ManifestToolsScene,
)


def _post_register_init():
    # Fill paths for all scenes if empty.
    for scn in bpy.data.scenes:
        if not hasattr(scn, "manifest_tools"):
            continue
        props = scn.manifest_tools
        fill_paths_from_cli(props)
    return None  # run once


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.manifest_tools = PointerProperty(type=MT_ToolsProps)

    # After registration, schedule one-shot init to fill CLI paths.
    bpy.app.timers.register(_post_register_init, first_interval=0.1)


def unregister():
    if hasattr(bpy.types.Scene, "manifest_tools"):
        del bpy.types.Scene.manifest_tools
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
