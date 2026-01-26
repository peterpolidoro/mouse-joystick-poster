# mbm_tools_addon.py
# Blender Add-on: MBM Tools (Boundary + Ports + Labels) v0.1
#
# Goals:
#   - Load a manifest.json (CLI --manifest or UI path) into editable UI properties
#   - Apply changes by calling a "builder" script's build_scene_from_manifest(manifest, project_root, do_render=False)
#   - Provide interactive picking:
#       * Labels attach to FACE indices (Pick Face)
#       * Ports attach to VERTEX indices (Pick Vertex)
#   - Support reproducible documentation renders by saving everything back to the manifest.
#
# CLI usage patterns supported:
#   blender -P /path/to/mbm_setup_scene.py -- --manifest /path/to/manifest.json
#   blender --python /path/to/mbm_setup_scene.py -- --manifest /path/to/manifest.json
#
# The add-on will auto-fill paths from CLI and (optionally) auto-load the manifest on startup.

bl_info = {
    "name": "MBM Tools (Boundary/Ports/Labels)",
    "author": "ChatGPT",
    "version": (0, 6, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Tool ; Properties > Scene",
    "description": "Edit MBM manifest (boundary + ports + labels) in Blender, apply and save for reproducible renders.",
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

from mathutils import Vector, Euler
from mathutils.bvhtree import BVHTree
from bpy_extras import view3d_utils
from bpy_extras.object_utils import world_to_camera_view


# -----------------------------
# Globals
# -----------------------------

_IS_LOADING = False
_UPDATE_TIMER_ACTIVE = False

_BUILDER_CACHE = {
    "path": None,
    "module": None,
    "mod_name": "_mbm_builder_module",
}


# -----------------------------
# Utility
# -----------------------------

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _as_float(value, default: float) -> float:
    """Parse a float from JSON-ish values (handles None and 'AUTO')."""
    try:
        if value is None:
            return float(default)
        if isinstance(value, str) and value.strip().upper() == "AUTO":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


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
    return os.path.abspath(os.path.join(os.getcwd(), p))


def _guess_builder_path(manifest_path: str) -> str:
    """Try a few common builder-script locations relative to the manifest."""
    if not manifest_path:
        return ""
    d = os.path.dirname(os.path.abspath(manifest_path))
    candidates = [
        os.path.join(d, "scripts", "mbm_setup_scene.py"),
        os.path.join(d, "scripts", "setup_scene.py"),
        os.path.join(d, "mbm_setup_scene.py"),
        os.path.join(d, "setup_scene.py"),
    ]
    for cand in candidates:
        if os.path.exists(cand):
            return cand
    return ""


def _parse_cli_paths() -> tuple[str, str]:
    """
    Extract (builder_path, manifest_path) from Blender's sys.argv.
    Supports:
      blender --python path/to/mbm_setup_scene.py -- --manifest path/to/manifest.json
      blender -P path/to/mbm_setup_scene.py -- --manifest path/to/manifest.json
    Also supports --manifest=... form.
    """
    argv = list(sys.argv)
    builder = ""
    manifest = ""

    for i, a in enumerate(argv):
        if a in ("--python", "-P"):
            if i + 1 < len(argv):
                builder = argv[i + 1]

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

    if (not force_reload and _BUILDER_CACHE["module"] is not None and _BUILDER_CACHE["path"] == builder_path):
        return _BUILDER_CACHE["module"]

    if not os.path.exists(builder_path):
        raise FileNotFoundError(f"Builder script not found: {builder_path}")

    # hard reload: remove from sys.modules to clear globals (mesh caches)
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
    if context is None or not hasattr(context, "scene"):
        return
    if _IS_LOADING:
        return
    props = context.scene.mbm_tools
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
            print("[MBM Tools] Live update failed:", repr(e))
        return None

    bpy.app.timers.register(_timer, first_interval=max(0.05, float(props.live_update_delay)))


def _on_prop_update(self, context):
    _schedule_live_update(context)


# -----------------------------
# Property Groups
# -----------------------------

class MBM_BoundaryProps(PropertyGroup):
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
    edge_color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, default=(0.2, 0.2, 0.2), min=0.0, max=1.0, update=_on_prop_update)
    edge_alpha: FloatProperty(name="Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)

    # Vertices
    vertex_radius: FloatProperty(name="Radius", default=0.08, min=0.0001, soft_max=1.0, update=_on_prop_update)
    vertex_color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, default=(0.2235, 1.0, 0.0784), min=0.0, max=1.0, update=_on_prop_update)
    vertex_alpha: FloatProperty(name="Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)

    # Faces
    face_thickness: FloatProperty(name="Thickness", default=0.03, min=0.0, soft_max=1.0, update=_on_prop_update)
    face_color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, default=(1.0, 0.0, 1.0), min=0.0, max=1.0, update=_on_prop_update)
    face_alpha: FloatProperty(name="Alpha", default=0.10, min=0.0, max=1.0, update=_on_prop_update)

    # Details
    edge_cylinder_sides: IntProperty(name="Edge Sides", default=24, min=3, max=128, update=_on_prop_update)
    vertex_sphere_segments: IntProperty(name="Sphere Segments", default=32, min=3, max=128, update=_on_prop_update)
    vertex_sphere_rings: IntProperty(name="Sphere Rings", default=16, min=3, max=128, update=_on_prop_update)
    edge_coplanar_dot: FloatProperty(name="Coplanar Dot", default=0.999999, min=0.9, max=1.0, precision=6, update=_on_prop_update)


class MBM_CameraProps(PropertyGroup):
    lens_mm: FloatProperty(name="Lens (mm)", default=50.0, min=1.0, max=300.0, update=_on_prop_update)
    distance: FloatProperty(name="Distance", default=4.8, min=0.1, soft_max=50.0, update=_on_prop_update)

    use_location: BoolProperty(name="Explicit Location", default=False, update=_on_prop_update)
    location: FloatVectorProperty(name="Location", size=3, subtype="TRANSLATION", default=(0.0, -4.8, 1.8), update=_on_prop_update)

    target_mode: EnumProperty(
        name="Target",
        items=[("AUTO", "AUTO (Boundary Center)", ""), ("CUSTOM", "Custom", "")],
        default="AUTO",
        update=_on_prop_update,
    )
    target: FloatVectorProperty(name="Target", size=3, subtype="TRANSLATION", default=(0.0, 0.0, 0.0), update=_on_prop_update)

    use_rotation: BoolProperty(
        name="Explicit Rotation (Quaternion)",
        default=False,
        description="If enabled, the builder uses camera.rotation_quat from the manifest and will not override it with look-at.",
        update=_on_prop_update,
    )
    rotation_quat: FloatVectorProperty(
        name="Rotation (wxyz)",
        size=4,
        subtype="QUATERNION",
        default=(1.0, 0.0, 0.0, 0.0),
        update=_on_prop_update,
    )


class MBM_LabelProps(PropertyGroup):
    name: StringProperty(name="Name", default="label_01", update=_on_prop_update)
    target: StringProperty(name="Target Boundary", default="boundary", update=_on_prop_update)

    attach_face_index: IntProperty(name="Face Index", default=-1, min=-1, description="-1 means auto-select", update=_on_prop_update)

    direction: EnumProperty(
        name="Direction",
        items=[("OUT", "Out (outside callout)", ""), ("IN", "In (inside label)", "")],
        default="OUT",
        update=_on_prop_update,
    )

    cyl_radius: FloatProperty(name="Radius", default=0.03, min=0.0001, soft_max=1.0, update=_on_prop_update)

    cyl_length_mode: EnumProperty(name="Length", items=[("AUTO", "AUTO", ""), ("FIXED", "Fixed", "")], default="AUTO", update=_on_prop_update)
    cyl_length: FloatProperty(name="Fixed", default=1.2, min=0.01, soft_max=10.0, update=_on_prop_update)
    cyl_length_min: FloatProperty(name="Min", default=0.6, min=0.01, soft_max=10.0, update=_on_prop_update)
    cyl_length_max: FloatProperty(name="Max", default=2.8, min=0.01, soft_max=20.0, update=_on_prop_update)

    cyl_color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, default=(1.0, 1.0, 1.0), min=0.0, max=1.0, update=_on_prop_update)
    cyl_alpha: FloatProperty(name="Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)

    text_value: StringProperty(name="Text", default="Label", update=_on_prop_update)
    text_offset_y: FloatProperty(name="Text Offset Y", default=0.0, soft_min=-1.0, soft_max=1.0, description="Move text up/down in its board plane (local Y).", update=_on_prop_update)
    text_size: FloatProperty(name="Size", default=0.30, min=0.01, soft_max=2.0, update=_on_prop_update)
    text_extrude: FloatProperty(name="Extrude", default=0.02, min=0.0, soft_max=0.2, description="Text thickness (curve extrude).", update=_on_prop_update)
    text_color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, default=(1.0, 1.0, 1.0), min=0.0, max=1.0, update=_on_prop_update)
    text_alpha: FloatProperty(name="Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)
    font_path: StringProperty(name="Font", subtype="FILE_PATH", default="", update=_on_prop_update)

    image_filepath: StringProperty(name="Image", subtype="FILE_PATH", default="", update=_on_prop_update)
    image_height: FloatProperty(name="Height", default=0.55, min=0.01, soft_max=5.0, update=_on_prop_update)
    image_alpha: FloatProperty(name="Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)
    image_scale: FloatProperty(name="Scale", default=1.0, min=0.01, soft_max=10.0, description="Per-item image size multiplier (applied on top of global style + global scale).", update=_on_prop_update)


class MBM_PortProps(PropertyGroup):
    name: StringProperty(name="Name", default="port_01", update=_on_prop_update)
    target: StringProperty(name="Target Boundary", default="boundary", update=_on_prop_update)

    attach_vertex_index: IntProperty(name="Vertex Index", default=-1, min=-1, description="-1 means auto-select", update=_on_prop_update)

    flow_kind: EnumProperty(
        name="Kind",
        items=[("POWER", "Power", ""), ("INFO", "Information", ""), ("BOTH", "Power+Info", "")],
        default="POWER",
        update=_on_prop_update,
    )
    flow_direction: EnumProperty(
        name="Direction",
        items=[("IN", "In", ""), ("OUT", "Out", ""), ("BIDIR", "Bidirectional", "")],
        default="OUT",
        update=_on_prop_update,
    )

    cyl_radius: FloatProperty(name="Radius", default=0.03, min=0.0001, soft_max=1.0, update=_on_prop_update)

    cyl_length_mode: EnumProperty(name="Length", items=[("AUTO", "AUTO", ""), ("FIXED", "Fixed", "")], default="AUTO", update=_on_prop_update)
    cyl_length: FloatProperty(name="Fixed", default=1.2, min=0.01, soft_max=10.0, update=_on_prop_update)
    cyl_length_min: FloatProperty(name="Min", default=0.6, min=0.01, soft_max=10.0, update=_on_prop_update)
    cyl_length_max: FloatProperty(name="Max", default=2.8, min=0.01, soft_max=20.0, update=_on_prop_update)

    cyl_color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, default=(1.0, 1.0, 0.2), min=0.0, max=1.0, update=_on_prop_update)
    cyl_alpha: FloatProperty(name="Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)

    arrow_enabled: BoolProperty(name="Arrowheads", default=True, update=_on_prop_update)
    arrow_length: FloatProperty(name="Arrow Length", default=0.18, min=0.001, soft_max=2.0, update=_on_prop_update)
    arrow_radius: FloatProperty(name="Arrow Radius", default=0.07, min=0.001, soft_max=2.0, update=_on_prop_update)

    text_value: StringProperty(name="Text", default="Port", update=_on_prop_update)
    text_offset_y: FloatProperty(name="Text Offset Y", default=0.0, soft_min=-1.0, soft_max=1.0, description="Move text up/down in its board plane (local Y).", update=_on_prop_update)
    text_size: FloatProperty(name="Size", default=0.30, min=0.01, soft_max=2.0, update=_on_prop_update)
    text_extrude: FloatProperty(name="Extrude", default=0.02, min=0.0, soft_max=0.2, description="Text thickness (curve extrude).", update=_on_prop_update)
    text_color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, default=(1.0, 1.0, 1.0), min=0.0, max=1.0, update=_on_prop_update)
    text_alpha: FloatProperty(name="Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)
    font_path: StringProperty(name="Font", subtype="FILE_PATH", default="", update=_on_prop_update)

    image_filepath: StringProperty(name="Image", subtype="FILE_PATH", default="", update=_on_prop_update)
    image_height: FloatProperty(name="Height", default=0.55, min=0.01, soft_max=5.0, update=_on_prop_update)
    image_alpha: FloatProperty(name="Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)
    image_scale: FloatProperty(name="Scale", default=1.0, min=0.01, soft_max=10.0, description="Per-item image size multiplier (applied on top of global style + global scale).", update=_on_prop_update)



class MBM_PowerPortStyleProps(PropertyGroup):
    """Global style preset for POWER ports."""

    cyl_radius: FloatProperty(name="Radius", default=0.03, min=0.0001, soft_max=1.0, update=_on_prop_update)
    cyl_length_min: FloatProperty(name="Min Length", default=0.6, min=0.01, soft_max=10.0, update=_on_prop_update)
    cyl_length_max: FloatProperty(name="Max Length", default=2.8, min=0.01, soft_max=20.0, update=_on_prop_update)
    cyl_color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, default=(1.0, 0.0, 0.0), min=0.0, max=1.0, update=_on_prop_update)
    cyl_alpha: FloatProperty(name="Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)

    arrow_enabled: BoolProperty(name="Arrowheads", default=True, update=_on_prop_update)
    arrow_length: FloatProperty(name="Arrow Length", default=0.18, min=0.001, soft_max=2.0, update=_on_prop_update)
    arrow_radius: FloatProperty(name="Arrow Radius", default=0.07, min=0.001, soft_max=2.0, update=_on_prop_update)
    board_gap: FloatProperty(name="Board Gap", default=0.08, min=0.0, soft_max=10.0, description="Distance from cylinder tip to board center. 0 = board at tip.", update=_on_prop_update)

    text_size: FloatProperty(name="Text Size", default=0.28, min=0.01, soft_max=2.0, update=_on_prop_update)
    text_extrude: FloatProperty(name="Text Extrude", default=0.02, min=0.0, soft_max=0.2, description="Text thickness (curve extrude).", update=_on_prop_update)
    text_color: FloatVectorProperty(name="Text Color", subtype="COLOR", size=3, default=(1.0, 0.0, 0.0), min=0.0, max=1.0, update=_on_prop_update)
    text_alpha: FloatProperty(name="Text Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)

    image_height: FloatProperty(name="Image Height", default=0.50, min=0.01, soft_max=5.0, update=_on_prop_update)
    image_alpha: FloatProperty(name="Image Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)

    layout_image_above_text: BoolProperty(name="Image Above Text", default=True, update=_on_prop_update)
    layout_spacing: FloatProperty(name="Spacing", default=0.05, min=0.0, soft_max=1.0, update=_on_prop_update)
    layout_padding: FloatProperty(name="Padding", default=0.04, min=0.0, soft_max=1.0, update=_on_prop_update)


class MBM_InfoPortStyleProps(PropertyGroup):
    """Global style preset for INFO ports."""

    cyl_radius: FloatProperty(name="Radius", default=0.02, min=0.0001, soft_max=1.0, update=_on_prop_update)
    cyl_length_min: FloatProperty(name="Min Length", default=0.6, min=0.01, soft_max=10.0, update=_on_prop_update)
    cyl_length_max: FloatProperty(name="Max Length", default=2.2, min=0.01, soft_max=20.0, update=_on_prop_update)
    cyl_color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, default=(0.0, 1.0, 1.0), min=0.0, max=1.0, update=_on_prop_update)
    cyl_alpha: FloatProperty(name="Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)

    arrow_enabled: BoolProperty(name="Arrowheads", default=True, update=_on_prop_update)
    arrow_length: FloatProperty(name="Arrow Length", default=0.16, min=0.001, soft_max=2.0, update=_on_prop_update)
    arrow_radius: FloatProperty(name="Arrow Radius", default=0.06, min=0.001, soft_max=2.0, update=_on_prop_update)
    board_gap: FloatProperty(name="Board Gap", default=0.08, min=0.0, soft_max=10.0, description="Distance from cylinder tip to board center. 0 = board at tip.", update=_on_prop_update)

    text_size: FloatProperty(name="Text Size", default=0.26, min=0.01, soft_max=2.0, update=_on_prop_update)
    text_extrude: FloatProperty(name="Text Extrude", default=0.02, min=0.0, soft_max=0.2, description="Text thickness (curve extrude).", update=_on_prop_update)
    text_color: FloatVectorProperty(name="Text Color", subtype="COLOR", size=3, default=(0.0, 1.0, 1.0), min=0.0, max=1.0, update=_on_prop_update)
    text_alpha: FloatProperty(name="Text Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)

    image_height: FloatProperty(name="Image Height", default=0.45, min=0.01, soft_max=5.0, update=_on_prop_update)
    image_alpha: FloatProperty(name="Image Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)

    layout_image_above_text: BoolProperty(name="Image Above Text", default=True, update=_on_prop_update)
    layout_spacing: FloatProperty(name="Spacing", default=0.05, min=0.0, soft_max=1.0, update=_on_prop_update)
    layout_padding: FloatProperty(name="Padding", default=0.04, min=0.0, soft_max=1.0, update=_on_prop_update)


class MBM_LabelStyleProps(PropertyGroup):
    """Global style preset for labels."""

    cyl_radius: FloatProperty(name="Radius", default=0.02, min=0.0001, soft_max=1.0, update=_on_prop_update)
    cyl_length_min: FloatProperty(name="Min Length", default=0.35, min=0.01, soft_max=10.0, update=_on_prop_update)
    cyl_length_max: FloatProperty(name="Max Length", default=0.95, min=0.01, soft_max=20.0, update=_on_prop_update)
    cyl_color: FloatVectorProperty(name="Color", subtype="COLOR", size=3, default=(1.0, 0.478, 0.0), min=0.0, max=1.0, update=_on_prop_update)
    cyl_alpha: FloatProperty(name="Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)
    board_gap: FloatProperty(name="Board Gap", default=0.08, min=0.0, soft_max=10.0, description="Distance from cylinder tip to board center. 0 = board at tip.", update=_on_prop_update)

    text_size: FloatProperty(name="Text Size", default=0.34, min=0.01, soft_max=2.0, update=_on_prop_update)
    text_extrude: FloatProperty(name="Text Extrude", default=0.02, min=0.0, soft_max=0.2, description="Text thickness (curve extrude).", update=_on_prop_update)
    text_color: FloatVectorProperty(name="Text Color", subtype="COLOR", size=3, default=(1.0, 0.478, 0.0), min=0.0, max=1.0, update=_on_prop_update)
    text_alpha: FloatProperty(name="Text Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)

    image_height: FloatProperty(name="Image Height", default=0.40, min=0.01, soft_max=5.0, update=_on_prop_update)
    image_alpha: FloatProperty(name="Image Alpha", default=1.0, min=0.0, max=1.0, update=_on_prop_update)

    layout_image_above_text: BoolProperty(name="Image Above Text", default=True, update=_on_prop_update)
    layout_spacing: FloatProperty(name="Spacing", default=0.05, min=0.0, soft_max=1.0, update=_on_prop_update)
    layout_padding: FloatProperty(name="Padding", default=0.04, min=0.0, soft_max=1.0, update=_on_prop_update)


class MBM_StylesProps(PropertyGroup):
    """Global styles written to manifest['styles'].

    This is the *one place* to adjust sizes/colors for:
      - Power ports
      - Info ports
      - Labels
    """

    enforce_global: BoolProperty(
        name="Enforce Global Styles",
        default=True,
        description="If enabled, the builder overwrites per-object style fields (cylinder/text/image sizes/colors) using these global presets.",
        update=_on_prop_update,
    )

    global_scale: FloatProperty(name="Global Scale", default=1.0, min=0.001, soft_max=100.0, description="One knob to scale the entire MBM diagram (boundary, ports, labels, text, images) to match other Blender objects.", update=_on_prop_update)

    port_power: PointerProperty(type=MBM_PowerPortStyleProps)
    port_info: PointerProperty(type=MBM_InfoPortStyleProps)
    label: PointerProperty(type=MBM_LabelStyleProps)


class MBM_VisibleIndexItem(PropertyGroup):
    """An index (vertex or face) that is visible in the active camera view."""

    index: IntProperty(name="Index", default=0)
    x_px: FloatProperty(name="X (px)", default=0.0)
    y_px: FloatProperty(name="Y (px)", default=0.0)
    ndc_z: FloatProperty(name="Depth", default=0.0)


class MBM_ToolsProps(PropertyGroup):
    manifest_path: StringProperty(name="Manifest Path", subtype="FILE_PATH", default="")
    builder_path: StringProperty(name="Builder Script", subtype="FILE_PATH", default="")

    auto_load_manifest_on_startup: BoolProperty(
        name="Auto-load Manifest",
        default=True,
        description="If CLI args provide --manifest, load it automatically into the UI on startup.",
    )

    reload_builder_each_apply: BoolProperty(
        name="Reload Builder on Apply",
        default=True,
        description="Reload builder module on every Apply to clear its globals (prevents removed-mesh errors).",
    )

    # Picking behavior
    pick_auto_apply: BoolProperty(
        name="Auto Apply after Pick",
        default=True,
        description="After picking a face/vertex, automatically Apply to rebuild that object.",
    )

    # Global board orientation
    board_plane_mode: EnumProperty(
        name="Board Plane",
        items=[("CAMERA", "Camera (billboard)", ""), ("AXIS", "Perpendicular to ray", "")],
        default="CAMERA",
        update=_on_prop_update,
    )

    live_update: BoolProperty(name="Live Update", default=False, description="Auto-apply after changes (debounced)")
    live_update_delay: FloatProperty(name="Delay (s)", default=0.25, min=0.05, max=2.0)

    raw_manifest_json: StringProperty(name="(internal) raw manifest", default="", options={'HIDDEN'})
    last_good_manifest_json: StringProperty(name="(internal) last good", default="", options={'HIDDEN'})
    last_status: StringProperty(name="(internal) status", default="", options={'HIDDEN'})

    boundary: PointerProperty(type=MBM_BoundaryProps)
    camera: PointerProperty(type=MBM_CameraProps)
    styles: PointerProperty(type=MBM_StylesProps)

    labels: CollectionProperty(type=MBM_LabelProps)
    active_label_index: IntProperty(name="Active Label", default=0)

    ports: CollectionProperty(type=MBM_PortProps)
    active_port_index: IntProperty(name="Active Port", default=0)

    # Camera-visible indices helper (computed from boundary solid + active camera)
    visible_vertices: CollectionProperty(type=MBM_VisibleIndexItem)
    active_visible_vertex_index: IntProperty(name="Active Visible Vertex", default=0)

    visible_faces: CollectionProperty(type=MBM_VisibleIndexItem)
    active_visible_face_index: IntProperty(name="Active Visible Face", default=0)


# -----------------------------
# Manifest ↔ props conversion
# -----------------------------

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
        if isinstance(o, dict) and o.get("name") == name and str(o.get("type", "")).lower() == str(type_name).lower():
            return o
    o = {"name": name, "type": type_name}
    objs.append(o)
    return o


def load_manifest_into_props(manifest: dict, props: MBM_ToolsProps):
    global _IS_LOADING
    _IS_LOADING = True
    try:
        # Global board plane mode
        boards = manifest.get("boards", {}) if isinstance(manifest.get("boards", {}), dict) else {}
        labels_cfg = manifest.get("labels", {}) if isinstance(manifest.get("labels", {}), dict) else {}
        src = boards if boards else labels_cfg
        pm = str(src.get("plane_mode", src.get("plane", manifest.get("label_plane_mode", props.board_plane_mode)))).upper()
        props.board_plane_mode = pm if pm in {"CAMERA", "AXIS"} else props.board_plane_mode


        # Global styles (optional) — this is the *one place* to adjust sizes/colors
        styles = manifest.get("styles", {}) if isinstance(manifest.get("styles", {}), dict) else {}
        props.styles.enforce_global = bool(styles.get("enforce_global", props.styles.enforce_global))
        props.styles.global_scale = _as_float(styles.get("global_scale", props.styles.global_scale), props.styles.global_scale)

        # ---- Label style
        l_style = styles.get("label", {}) if isinstance(styles.get("label", {}), dict) else {}
        l_cyl = l_style.get("cylinder", {}) if isinstance(l_style.get("cylinder", {}), dict) else {}
        props.styles.label.cyl_radius = float(l_cyl.get("radius", props.styles.label.cyl_radius))
        props.styles.label.cyl_length_min = float(l_cyl.get("length_min", props.styles.label.cyl_length_min))
        props.styles.label.cyl_length_max = float(l_cyl.get("length_max", props.styles.label.cyl_length_max))
        props.styles.label.cyl_color = _parse_color_rgb(l_cyl.get("color", None), default=tuple(props.styles.label.cyl_color))
        props.styles.label.cyl_alpha = float(l_cyl.get("alpha", props.styles.label.cyl_alpha))

        l_board = l_style.get("board", {}) if isinstance(l_style.get("board", {}), dict) else {}
        props.styles.label.board_gap = _as_float(l_board.get("gap", props.styles.label.board_gap), props.styles.label.board_gap)

        l_txt = l_style.get("text", {}) if isinstance(l_style.get("text", {}), dict) else {}
        props.styles.label.text_size = float(l_txt.get("size", props.styles.label.text_size))
        props.styles.label.text_extrude = float(l_txt.get("extrude", props.styles.label.text_extrude))
        props.styles.label.text_color = _parse_color_rgb(l_txt.get("color", None), default=tuple(props.styles.label.text_color))
        props.styles.label.text_alpha = float(l_txt.get("alpha", props.styles.label.text_alpha))

        l_img = l_style.get("image", {}) if isinstance(l_style.get("image", {}), dict) else {}
        props.styles.label.image_height = float(l_img.get("height", props.styles.label.image_height))
        props.styles.label.image_alpha = float(l_img.get("alpha", props.styles.label.image_alpha))

        l_layout = l_style.get("layout", {}) if isinstance(l_style.get("layout", {}), dict) else {}
        props.styles.label.layout_image_above_text = bool(l_layout.get("image_above_text", props.styles.label.layout_image_above_text))
        props.styles.label.layout_spacing = float(l_layout.get("spacing", props.styles.label.layout_spacing))
        props.styles.label.layout_padding = float(l_layout.get("padding", props.styles.label.layout_padding))

        # ---- Port styles
        p_style = styles.get("port", {}) if isinstance(styles.get("port", {}), dict) else {}

        def _apply_port_style(dst, src):
            src = src if isinstance(src, dict) else {}
            cyl = src.get("cylinder", {}) if isinstance(src.get("cylinder", {}), dict) else {}
            dst.cyl_radius = float(cyl.get("radius", dst.cyl_radius))
            dst.cyl_length_min = float(cyl.get("length_min", dst.cyl_length_min))
            dst.cyl_length_max = float(cyl.get("length_max", dst.cyl_length_max))
            dst.cyl_color = _parse_color_rgb(cyl.get("color", None), default=tuple(dst.cyl_color))
            dst.cyl_alpha = float(cyl.get("alpha", dst.cyl_alpha))

            arrow = src.get("arrow", {}) if isinstance(src.get("arrow", {}), dict) else {}
            dst.arrow_enabled = bool(arrow.get("enabled", dst.arrow_enabled))
            dst.arrow_length = float(arrow.get("length", dst.arrow_length))
            dst.arrow_radius = float(arrow.get("radius", dst.arrow_radius))

            board = src.get("board", {}) if isinstance(src.get("board", {}), dict) else {}
            dst.board_gap = _as_float(board.get("gap", dst.board_gap), dst.board_gap)

            txt = src.get("text", {}) if isinstance(src.get("text", {}), dict) else {}
            dst.text_size = float(txt.get("size", dst.text_size))
            dst.text_extrude = float(txt.get("extrude", dst.text_extrude))
            dst.text_color = _parse_color_rgb(txt.get("color", None), default=tuple(dst.text_color))
            dst.text_alpha = float(txt.get("alpha", dst.text_alpha))

            img = src.get("image", {}) if isinstance(src.get("image", {}), dict) else {}
            dst.image_height = float(img.get("height", dst.image_height))
            dst.image_alpha = float(img.get("alpha", dst.image_alpha))

            layout = src.get("layout", {}) if isinstance(src.get("layout", {}), dict) else {}
            dst.layout_image_above_text = bool(layout.get("image_above_text", dst.layout_image_above_text))
            dst.layout_spacing = float(layout.get("spacing", dst.layout_spacing))
            dst.layout_padding = float(layout.get("padding", dst.layout_padding))

        _apply_port_style(props.styles.port_power, p_style.get("power", {}))
        _apply_port_style(props.styles.port_info, p_style.get("info", {}))

        # Boundary: first boundary object
        b_list = _find_objects(manifest, "boundary")
        if b_list:
            b = b_list[0]
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

        # Explicit rotation (optional)
        props.camera.use_rotation = False
        rq = cam.get("rotation_quat", cam.get("rotation_quaternion", None))
        re_deg = cam.get("rotation_euler_deg", cam.get("rotation_deg", None))
        if isinstance(rq, (list, tuple)) and len(rq) >= 4:
            props.camera.use_rotation = True
            props.camera.rotation_quat = (float(rq[0]), float(rq[1]), float(rq[2]), float(rq[3]))
        elif isinstance(re_deg, (list, tuple)) and len(re_deg) >= 3:
            try:
                e = Euler((float(re_deg[0]) * 0.017453292519943295,
                           float(re_deg[1]) * 0.017453292519943295,
                           float(re_deg[2]) * 0.017453292519943295), 'XYZ')
                q = e.to_quaternion()
                props.camera.use_rotation = True
                props.camera.rotation_quat = (float(q.w), float(q.x), float(q.y), float(q.z))
            except Exception:
                props.camera.use_rotation = False

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

            item.direction = str(l.get("direction", item.direction) or item.direction).upper()
            if item.direction not in {"OUT", "IN"}:
                item.direction = "OUT"

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
            item.text_offset_y = float(txt.get("offset_y", item.text_offset_y))
            item.font_path = str(txt.get("font", "") or "")
            ex = txt.get("extrude", None)
            if isinstance(ex, (int, float)):
                item.text_extrude = float(ex)
            else:
                # Default thickness relative to size (3D but not chunky)
                item.text_extrude = max(0.001, float(item.text_size) * 0.07)
            if float(item.text_extrude) <= 1e-6:
                item.text_extrude = max(0.001, float(item.text_size) * 0.07)

            img = l.get("image", {}) if isinstance(l.get("image", {}), dict) else {}
            item.image_filepath = str(img.get("filepath", "") or "")
            item.image_height = float(img.get("height", item.image_height))
            item.image_alpha = float(img.get("alpha", item.image_alpha))
            item.image_scale = _as_float(img.get("scale", item.image_scale), item.image_scale)

        props.active_label_index = 0 if len(props.labels) else -1

        # Ports
        props.ports.clear()
        ports = _find_objects(manifest, "port")
        for p in ports:
            item = props.ports.add()
            item.name = str(p.get("name", "port"))
            item.target = str(p.get("target", props.boundary.name))

            attach = p.get("attach", {}) if isinstance(p.get("attach", {}), dict) else {}
            idx = attach.get("index", None)
            item.attach_vertex_index = int(idx) if idx is not None else -1

            flow = p.get("flow", {}) if isinstance(p.get("flow", {}), dict) else {}
            item.flow_kind = str(flow.get("kind", item.flow_kind) or item.flow_kind).upper()
            if item.flow_kind not in {"POWER", "INFO", "BOTH"}:
                item.flow_kind = "POWER"
            item.flow_direction = str(flow.get("direction", item.flow_direction) or item.flow_direction).upper()
            if item.flow_direction not in {"IN", "OUT", "BIDIR"}:
                item.flow_direction = "OUT"

            cyl = p.get("cylinder", {}) if isinstance(p.get("cylinder", {}), dict) else {}
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

            arrow = p.get("arrow", {}) if isinstance(p.get("arrow", {}), dict) else {}
            item.arrow_enabled = bool(arrow.get("enabled", item.arrow_enabled))
            item.arrow_length = float(arrow.get("length", item.arrow_length))
            item.arrow_radius = float(arrow.get("radius", item.arrow_radius))

            txt = p.get("text", {}) if isinstance(p.get("text", {}), dict) else {}
            item.text_value = str(txt.get("value", item.text_value))
            item.text_size = float(txt.get("size", item.text_size))
            item.text_color = _parse_color_rgb(txt.get("color"), item.text_color)
            item.text_alpha = float(txt.get("alpha", item.text_alpha))
            item.text_offset_y = float(txt.get("offset_y", item.text_offset_y))
            item.font_path = str(txt.get("font", "") or "")
            ex = txt.get("extrude", None)
            if isinstance(ex, (int, float)):
                item.text_extrude = float(ex)
            else:
                # Default thickness relative to size (3D but not chunky)
                item.text_extrude = max(0.001, float(item.text_size) * 0.07)
            if float(item.text_extrude) <= 1e-6:
                item.text_extrude = max(0.001, float(item.text_size) * 0.07)

            img = p.get("image", {}) if isinstance(p.get("image", {}), dict) else {}
            item.image_filepath = str(img.get("filepath", "") or "")
            item.image_height = float(img.get("height", item.image_height))
            item.image_alpha = float(img.get("alpha", item.image_alpha))
            item.image_scale = _as_float(img.get("scale", item.image_scale), item.image_scale)

        props.active_port_index = 0 if len(props.ports) else -1

    finally:
        _IS_LOADING = False


def update_manifest_from_props(manifest: dict, props: MBM_ToolsProps) -> dict:
    # Global board settings
    boards = manifest.setdefault("boards", {})
    if not isinstance(boards, dict):
        manifest["boards"] = {}
        boards = manifest["boards"]
    boards["plane_mode"] = str(props.board_plane_mode)

    # Backward compatibility for older builders that read labels.plane_mode
    labels_cfg = manifest.setdefault("labels", {})
    if isinstance(labels_cfg, dict):
        labels_cfg["plane_mode"] = str(props.board_plane_mode)


    # Global styles (ports + labels)
    styles = manifest.setdefault("styles", {})
    if not isinstance(styles, dict):
        manifest["styles"] = {}
        styles = manifest["styles"]

    styles["enforce_global"] = bool(props.styles.enforce_global)

    styles["global_scale"] = float(props.styles.global_scale)

    # Label style
    styles["label"] = {
        "cylinder": {
            "radius": float(props.styles.label.cyl_radius),
            "length": "AUTO",
            "length_min": float(props.styles.label.cyl_length_min),
            "length_max": float(props.styles.label.cyl_length_max),
            "sides": 20,
            "base_offset": "AUTO",
            "color": _rgb_to_hex(props.styles.label.cyl_color),
            "alpha": float(props.styles.label.cyl_alpha),
        },
        "board": {"gap": float(props.styles.label.board_gap)},
        "text": {
            "size": float(props.styles.label.text_size),
            "extrude": float(props.styles.label.text_extrude),
            "color": _rgb_to_hex(props.styles.label.text_color),
            "alpha": float(props.styles.label.text_alpha),
            "align_x": "CENTER",
            "align_y": "CENTER",
        },
        "image": {
            "height": float(props.styles.label.image_height),
            "alpha": float(props.styles.label.image_alpha),
        },
        "layout": {
            "image_above_text": bool(props.styles.label.layout_image_above_text),
            "spacing": float(props.styles.label.layout_spacing),
            "padding": float(props.styles.label.layout_padding),
        },
    }

    # Port styles
    port_styles = styles.setdefault("port", {})
    if not isinstance(port_styles, dict):
        styles["port"] = {}
        port_styles = styles["port"]

    port_styles["power"] = {
        "cylinder": {
            "radius": float(props.styles.port_power.cyl_radius),
            "length": "AUTO",
            "length_min": float(props.styles.port_power.cyl_length_min),
            "length_max": float(props.styles.port_power.cyl_length_max),
            "sides": 24,
            "base_offset": "AUTO",
            "color": _rgb_to_hex(props.styles.port_power.cyl_color),
            "alpha": float(props.styles.port_power.cyl_alpha),
        },
        "board": {"gap": float(props.styles.port_power.board_gap)},
        "arrow": {
            "enabled": bool(props.styles.port_power.arrow_enabled),
            "length": float(props.styles.port_power.arrow_length),
            "radius": float(props.styles.port_power.arrow_radius),
        },
        "text": {
            "size": float(props.styles.port_power.text_size),
            "extrude": float(props.styles.port_power.text_extrude),
            "color": _rgb_to_hex(props.styles.port_power.text_color),
            "alpha": float(props.styles.port_power.text_alpha),
            "align_x": "CENTER",
            "align_y": "CENTER",
        },
        "image": {
            "height": float(props.styles.port_power.image_height),
            "alpha": float(props.styles.port_power.image_alpha),
        },
        "layout": {
            "image_above_text": bool(props.styles.port_power.layout_image_above_text),
            "spacing": float(props.styles.port_power.layout_spacing),
            "padding": float(props.styles.port_power.layout_padding),
        },
    }

    port_styles["info"] = {
        "cylinder": {
            "radius": float(props.styles.port_info.cyl_radius),
            "length": "AUTO",
            "length_min": float(props.styles.port_info.cyl_length_min),
            "length_max": float(props.styles.port_info.cyl_length_max),
            "sides": 24,
            "base_offset": "AUTO",
            "color": _rgb_to_hex(props.styles.port_info.cyl_color),
            "alpha": float(props.styles.port_info.cyl_alpha),
        },
        "board": {"gap": float(props.styles.port_info.board_gap)},
        "arrow": {
            "enabled": bool(props.styles.port_info.arrow_enabled),
            "length": float(props.styles.port_info.arrow_length),
            "radius": float(props.styles.port_info.arrow_radius),
        },
        "text": {
            "size": float(props.styles.port_info.text_size),
            "extrude": float(props.styles.port_info.text_extrude),
            "color": _rgb_to_hex(props.styles.port_info.text_color),
            "alpha": float(props.styles.port_info.text_alpha),
            "align_x": "CENTER",
            "align_y": "CENTER",
        },
        "image": {
            "height": float(props.styles.port_info.image_height),
            "alpha": float(props.styles.port_info.image_alpha),
        },
        "layout": {
            "image_above_text": bool(props.styles.port_info.layout_image_above_text),
            "spacing": float(props.styles.port_info.layout_spacing),
            "padding": float(props.styles.port_info.layout_padding),
        },
    }


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

    if props.camera.use_location or props.camera.use_rotation:
        cam["location"] = [float(props.camera.location[0]), float(props.camera.location[1]), float(props.camera.location[2])]
    else:
        if "location" in cam:
            del cam["location"]

    cam["target"] = "AUTO" if props.camera.target_mode == "AUTO" else [float(props.camera.target[0]), float(props.camera.target[1]), float(props.camera.target[2])]

    if props.camera.use_rotation:
        cam["mode"] = "EXPLICIT"
        cam["rotation_quat"] = [
            float(props.camera.rotation_quat[0]),
            float(props.camera.rotation_quat[1]),
            float(props.camera.rotation_quat[2]),
            float(props.camera.rotation_quat[3]),
        ]
    else:
        # preserve a non-explicit mode if it exists, but never keep EXPLICIT without a rotation
        if str(cam.get("mode", "LOOK_AT")).upper() == "EXPLICIT":
            cam["mode"] = "LOOK_AT"
        if "rotation_quat" in cam:
            del cam["rotation_quat"]
        if "rotation_quaternion" in cam:
            del cam["rotation_quaternion"]

    # Objects list
    objs = manifest.get("objects", [])
    if not isinstance(objs, list):
        objs = []
        manifest["objects"] = objs

    # Remove label/port objects not present in UI (keeps other unknown objects)
    ui_label_names = {str(it.name) for it in props.labels}
    ui_port_names = {str(it.name) for it in props.ports}

    filtered = []
    for o in objs:
        if not isinstance(o, dict):
            continue
        t = str(o.get("type", "")).lower()
        nm = str(o.get("name", ""))
        if t == "label" and nm and nm not in ui_label_names:
            continue
        if t == "port" and nm and nm not in ui_port_names:
            continue
        filtered.append(o)
    objs[:] = filtered

    # Update/create labels
    for item in props.labels:
        l = _ensure_object(manifest, item.name, "label")
        l["target"] = str(item.target or props.boundary.name)

        attach = l.setdefault("attach", {})
        if not isinstance(attach, dict):
            l["attach"] = {}
            attach = l["attach"]
        attach["site_type"] = "FACE"
        attach["index"] = None if int(item.attach_face_index) < 0 else int(item.attach_face_index)

        l["direction"] = str(item.direction)

        # Per-label style is global (manifest['styles']['label']). Keep only per-label content here.
        l.pop("cylinder", None)
        l.pop("layout", None)

        txt = l.setdefault("text", {})
        if not isinstance(txt, dict):
            l["text"] = {}
            txt = l["text"]
        # Keep only value/font here; sizes/colors come from styles.label.text
        txt.clear()
        txt["value"] = str(item.text_value)
        txt["font"] = item.font_path if item.font_path.strip() else None
        txt["offset_y"] = float(item.text_offset_y)

        img = l.setdefault("image", {})
        if not isinstance(img, dict):
            l["image"] = {}
            img = l["image"]
        # Keep only filepath here; size/alpha come from styles.label.image
        img.clear()
        img["filepath"] = item.image_filepath if item.image_filepath.strip() else None
        img["scale"] = float(item.image_scale)

        l.setdefault("auto_placement", {"enabled": True})
        l.setdefault("board", {"gap": "AUTO"})
        l.setdefault("layout", {"image_above_text": True, "spacing": 0.05, "padding": 0.04})

    # Update/create ports
    for item in props.ports:
        p = _ensure_object(manifest, item.name, "port")
        p["target"] = str(item.target or props.boundary.name)

        attach = p.setdefault("attach", {})
        if not isinstance(attach, dict):
            p["attach"] = {}
            attach = p["attach"]
        attach["site_type"] = "VERTEX"
        attach["index"] = None if int(item.attach_vertex_index) < 0 else int(item.attach_vertex_index)

        flow = p.setdefault("flow", {})
        if not isinstance(flow, dict):
            p["flow"] = {}
            flow = p["flow"]
        flow["kind"] = str(item.flow_kind)
        flow["direction"] = str(item.flow_direction)

        # Per-port style is global (manifest['styles']['port']). Keep only per-port content here.
        p.pop("cylinder", None)
        p.pop("arrow", None)
        p.pop("layout", None)

        txt = p.setdefault("text", {})
        if not isinstance(txt, dict):
            p["text"] = {}
            txt = p["text"]
        # Keep only value/font here; sizes/colors come from styles.port.*.text
        txt.clear()
        txt["value"] = str(item.text_value)
        txt["font"] = item.font_path if item.font_path.strip() else None
        txt["offset_y"] = float(item.text_offset_y)

        img = p.setdefault("image", {})
        if not isinstance(img, dict):
            p["image"] = {}
            img = p["image"]
        # Keep only filepath here; size/alpha come from styles.port.*.image
        img.clear()
        img["filepath"] = item.image_filepath if item.image_filepath.strip() else None
        img["scale"] = float(item.image_scale)

        p.setdefault("auto_placement", {"enabled": True})
        p.setdefault("board", {"gap": "AUTO"})
        p.setdefault("layout", {"image_above_text": True, "spacing": 0.05, "padding": 0.04})

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


def fill_paths_from_cli(props: MBM_ToolsProps) -> bool:
    builder_cli, manifest_cli = _parse_cli_paths()
    changed = False

    if manifest_cli and not props.manifest_path.strip():
        props.manifest_path = _abspath_from_cwd(manifest_cli)
        changed = True

    if builder_cli and not props.builder_path.strip():
        props.builder_path = _abspath_from_cwd(builder_cli)
        changed = True

    if props.manifest_path.strip() and not props.builder_path.strip():
        guess = _guess_builder_path(_abspath_from_cwd(props.manifest_path))
        if guess:
            props.builder_path = guess
            changed = True

    return changed


def _run_build(props: MBM_ToolsProps, manifest_obj: dict, force_reload: bool):
    manifest_path = _abspath_from_cwd(props.manifest_path)
    project_root = os.path.dirname(manifest_path)

    builder_path = props.builder_path.strip()
    builder_path = _abspath_from_cwd(builder_path) if builder_path else ""
    if not builder_path:
        builder_path = _guess_builder_path(manifest_path)
    if not builder_path:
        raise RuntimeError("Builder Script path is empty; set it in the panel.")

    module = _load_builder_module(builder_path, force_reload=force_reload)
    if not hasattr(module, "build_scene_from_manifest"):
        raise RuntimeError(f"Builder {builder_path} does not define build_scene_from_manifest().")

    module.build_scene_from_manifest(manifest_obj, project_root=project_root, do_render=False)


def apply_scene_from_props(context, safe: bool = True):
    props = context.scene.mbm_tools

    if not props.manifest_path.strip():
        raise RuntimeError("Manifest Path is empty.")

    base_manifest = _load_json_str(props.raw_manifest_json)
    new_manifest = update_manifest_from_props(base_manifest, props)
    props.raw_manifest_json = json.dumps(new_manifest, indent=2)

    last_good = _load_json_str(props.last_good_manifest_json) if props.last_good_manifest_json.strip() else None

    force_reload = bool(props.reload_builder_each_apply)

    try:
        _run_build(props, new_manifest, force_reload=force_reload)
        props.last_good_manifest_json = props.raw_manifest_json
        props.last_status = "Applied OK"
    except ReferenceError as e:
        # Retry with reload, and then restore last_good on failure
        props.last_status = f"Apply FAILED (ReferenceError): {e!r} — retrying with reload"
        try:
            _run_build(props, new_manifest, force_reload=True)
            props.last_good_manifest_json = props.raw_manifest_json
            props.last_status = "Applied OK (after reload retry)"
            return
        except Exception as e2:
            props.last_status = f"Apply FAILED after reload retry: {e2!r}"
            if safe and last_good is not None:
                try:
                    _run_build(props, last_good, force_reload=True)
                    props.last_status += " (restored last good)"
                except Exception as e3:
                    props.last_status += f" (restore failed: {e3!r})"
            raise
    except Exception as e:
        props.last_status = f"Apply FAILED: {e!r}"
        if safe and last_good is not None:
            try:
                _run_build(props, last_good, force_reload=True)
                props.last_status += " (restored last good)"
            except Exception as e2:
                props.last_status += f" (restore failed: {e2!r})"
        raise


def save_manifest_from_props(context):
    props = context.scene.mbm_tools
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


def load_manifest_file_into_props(props: MBM_ToolsProps) -> bool:
    if not props.manifest_path.strip():
        return False
    path = _abspath_from_cwd(props.manifest_path)
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        props.raw_manifest_json = json.dumps(manifest, indent=2)
        props.last_good_manifest_json = props.raw_manifest_json
        props.last_status = "Loaded"
        load_manifest_into_props(manifest, props)
        return True
    except Exception as e:
        props.last_status = f"Auto-load FAILED: {e!r}"
        return False


# -----------------------------
# Picking helpers
# -----------------------------

def _get_view3d_window_region_and_rv3d(context):
    area = context.area
    if area is None or area.type != 'VIEW_3D':
        return None, None
    region_win = None
    for r in area.regions:
        if r.type == 'WINDOW':
            region_win = r
            break
    rv3d = area.spaces.active.region_3d if area.spaces and hasattr(area.spaces.active, "region_3d") else None
    return region_win, rv3d


def _build_bvh_for_solid(solid_obj):
    me = solid_obj.data
    verts = [v.co.copy() for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons]
    if not polys:
        return None
    return BVHTree.FromPolygons(verts, polys, all_triangles=False)


def _resolved_attach_index(obj_name: str) -> str:
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        return ""
    try:
        if "attach_index" in obj:
            return str(int(obj["attach_index"]))
    except Exception:
        return ""
    return ""


# -----------------------------
# Operators
# -----------------------------

class MBM_OT_UseCLIPaths(Operator):
    bl_idname = "mbm.use_cli_paths"
    bl_label = "Use CLI Paths"
    bl_description = "Fill Manifest/Builder paths from command-line args"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.mbm_tools
        ok = fill_paths_from_cli(props)
        props.last_status = "Filled paths from CLI" if ok else "No CLI paths found / nothing changed"
        return {'FINISHED'}


class MBM_OT_LoadManifest(Operator):
    bl_idname = "mbm.load_manifest"
    bl_label = "Load"
    bl_description = "Load manifest.json into UI"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.mbm_tools
        fill_paths_from_cli(props)
        ok = load_manifest_file_into_props(props)
        if not ok:
            self.report({'ERROR'}, "Failed to load manifest (check Manifest Path).")
            return {'CANCELLED'}
        return {'FINISHED'}


class MBM_OT_ApplyScene(Operator):
    bl_idname = "mbm.apply_scene"
    bl_label = "Apply"
    bl_description = "Rebuild scene from UI (via builder script)"
    bl_options = {'REGISTER', 'UNDO'}

    safe: BoolProperty(name="Safe Apply", default=True)

    def execute(self, context):
        try:
            apply_scene_from_props(context, safe=bool(self.safe))
        except Exception as e:
            self.report({'ERROR'}, f"Apply failed: {e!r} (see Status)")
            return {'CANCELLED'}
        self.report({'INFO'}, "Applied.")
        return {'FINISHED'}


class MBM_OT_SaveManifest(Operator):
    bl_idname = "mbm.save_manifest"
    bl_label = "Save"
    bl_description = "Save UI values back to manifest.json"
    bl_options = {'REGISTER'}

    def execute(self, context):
        try:
            save_manifest_from_props(context)
        except Exception as e:
            self.report({'ERROR'}, f"Save failed: {e!r}")
            return {'CANCELLED'}
        self.report({'INFO'}, "Manifest saved.")
        return {'FINISHED'}


class MBM_OT_CaptureCamera(Operator):
    bl_idname = "mbm.capture_camera"
    bl_label = "Capture Camera"
    bl_description = "Copy current scene camera Location + Rotation into the UI (sets camera to EXPLICIT rotation mode)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.mbm_tools
        cam_obj = context.scene.camera or bpy.data.objects.get("Camera")
        if cam_obj is None:
            self.report({'ERROR'}, "No camera found (scene.camera is None). Apply once to create it.")
            return {'CANCELLED'}

        props.camera.use_location = True
        props.camera.location = (float(cam_obj.location.x), float(cam_obj.location.y), float(cam_obj.location.z))

        # Store quaternion (wxyz)
        q = cam_obj.rotation_quaternion if cam_obj.rotation_mode == "QUATERNION" else cam_obj.rotation_euler.to_quaternion()
        props.camera.use_rotation = True
        props.camera.rotation_quat = (float(q.w), float(q.x), float(q.y), float(q.z))

        props.last_status = "Captured camera transform (explicit rotation enabled)"
        return {'FINISHED'}


class MBM_OT_ClearCameraRotation(Operator):
    bl_idname = "mbm.clear_camera_rotation"
    bl_label = "Clear Explicit Rotation"
    bl_description = "Disable explicit camera rotation (builder will go back to look-at behavior)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.mbm_tools
        props.camera.use_rotation = False
        props.last_status = "Camera explicit rotation disabled"
        return {'FINISHED'}


class MBM_OT_SetBoardPlaneMode(Operator):
    bl_idname = "mbm.set_board_plane_mode"
    bl_label = "Set Board Plane"
    bl_description = "Set global board plane mode (CAMERA or AXIS). Optionally apply immediately."
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(items=[("CAMERA", "CAMERA", ""), ("AXIS", "AXIS", "")], default="CAMERA")
    apply_now: BoolProperty(default=True)

    def execute(self, context):
        props = context.scene.mbm_tools
        props.board_plane_mode = str(self.mode)
        props.last_status = f"Board plane mode set to {self.mode}"
        if self.apply_now:
            try:
                apply_scene_from_props(context, safe=True)
            except Exception as e:
                self.report({'ERROR'}, f"Apply failed: {e!r}")
                return {'CANCELLED'}
        return {'FINISHED'}



class MBM_OT_BakeCameraAndApply(Operator):
    bl_idname = "mbm.bake_camera_and_apply"
    bl_label = "Bake Camera + Apply"
    bl_description = "Capture current camera Location/Rotation into the manifest, set board plane mode, and rebuild scene."
    bl_options = {'REGISTER', 'UNDO'}

    plane_mode: EnumProperty(items=[("CAMERA", "CAMERA", ""), ("AXIS", "AXIS", "")], default="CAMERA")

    def execute(self, context):
        props = context.scene.mbm_tools
        cam_obj = context.scene.camera or bpy.data.objects.get("Camera")
        if cam_obj is None:
            self.report({'ERROR'}, "No camera found. Apply once to create it.")
            return {'CANCELLED'}

        # Capture camera location
        props.camera.use_location = True
        props.camera.location = (float(cam_obj.location.x), float(cam_obj.location.y), float(cam_obj.location.z))

        # Capture camera rotation as quaternion (wxyz)
        q = cam_obj.rotation_quaternion if cam_obj.rotation_mode == "QUATERNION" else cam_obj.rotation_euler.to_quaternion()
        props.camera.use_rotation = True
        props.camera.rotation_quat = (float(q.w), float(q.x), float(q.y), float(q.z))

        # Set board plane mode and apply
        props.board_plane_mode = str(self.plane_mode)

        try:
            apply_scene_from_props(context, safe=True)
        except Exception as e:
            self.report({'ERROR'}, f"Apply failed: {e!r}")
            return {'CANCELLED'}

        props.last_status = f"Baked camera + applied (board plane: {self.plane_mode})"
        return {'FINISHED'}



# -----------------------------
# Label ops
# -----------------------------

class MBM_OT_AddLabel(Operator):
    bl_idname = "mbm.add_label"
    bl_label = "Add Label"
    bl_description = "Add a label entry to the UI"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.mbm_tools
        idx = len(props.labels) + 1
        item = props.labels.add()
        item.name = f"label_{idx:02d}"
        item.target = props.boundary.name
        props.active_label_index = len(props.labels) - 1
        props.last_status = f"Added {item.name}"
        return {'FINISHED'}


class MBM_OT_RemoveLabel(Operator):
    bl_idname = "mbm.remove_label"
    bl_label = "Remove Label"
    bl_description = "Remove selected label entry"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.mbm_tools
        i = props.active_label_index
        if i < 0 or i >= len(props.labels):
            return {'CANCELLED'}
        name = props.labels[i].name
        props.labels.remove(i)
        props.active_label_index = min(max(0, i - 1), len(props.labels) - 1)
        props.last_status = f"Removed {name}"
        return {'FINISHED'}


class MBM_OT_SetLabelAutoFace(Operator):
    bl_idname = "mbm.set_label_auto_face"
    bl_label = "Set Auto Face"
    bl_description = "Set Face Index to -1 (auto select a good visible face)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.mbm_tools
        i = props.active_label_index
        if 0 <= i < len(props.labels):
            props.labels[i].attach_face_index = -1
            props.last_status = f"{props.labels[i].name}: Face Index set to AUTO (-1)"
        return {'FINISHED'}


class MBM_OT_PickLabelFace(Operator):
    bl_idname = "mbm.pick_label_face"
    bl_label = "Pick Face"
    bl_description = "Click a face in the viewport to attach the active label to that face"
    bl_options = {'REGISTER', 'UNDO'}

    label_index: IntProperty(default=-1)

    def invoke(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            self.report({'ERROR'}, "Pick Face must be started from a 3D View area.")
            return {'CANCELLED'}

        props = context.scene.mbm_tools
        if len(props.labels) == 0:
            self.report({'ERROR'}, "No labels in UI. Load manifest or Add Label first.")
            return {'CANCELLED'}

        i = int(self.label_index if self.label_index >= 0 else props.active_label_index)
        if i < 0 or i >= len(props.labels):
            self.report({'ERROR'}, "No active label selected.")
            return {'CANCELLED'}

        self._label_index = i
        lbl = props.labels[i]
        boundary_name = lbl.target or props.boundary.name
        solid_name = f"{boundary_name}_Solid"
        solid_obj = bpy.data.objects.get(solid_name)
        if solid_obj is None:
            self.report({'ERROR'}, f"Boundary solid not found: {solid_name}. Apply once to build it.")
            return {'CANCELLED'}

        self._solid_obj = solid_obj
        self._inv_mw = solid_obj.matrix_world.inverted()
        self._inv_mw_3 = solid_obj.matrix_world.to_3x3().inverted()

        bvh = _build_bvh_for_solid(solid_obj)
        if bvh is None:
            self.report({'ERROR'}, f"Boundary solid mesh has no faces: {solid_name}")
            return {'CANCELLED'}
        self._bvh = bvh

        context.window_manager.modal_handler_add(self)
        props.last_status = "Pick Face: Left-click a face; Esc/Right-click cancels"
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            context.scene.mbm_tools.last_status = "Pick Face cancelled"
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            region_win, rv3d = _get_view3d_window_region_and_rv3d(context)
            if region_win is None or rv3d is None:
                self.report({'ERROR'}, "Could not access View3D window region.")
                return {'CANCELLED'}

            coord = (event.mouse_x - region_win.x, event.mouse_y - region_win.y)

            origin = view3d_utils.region_2d_to_origin_3d(region_win, rv3d, coord)
            direction = view3d_utils.region_2d_to_vector_3d(region_win, rv3d, coord)
            if origin is None or direction is None:
                self.report({'ERROR'}, "Failed to compute pick ray.")
                return {'CANCELLED'}

            origin_l = self._inv_mw @ origin
            dir_l = (self._inv_mw_3 @ direction).normalized()

            hit = self._bvh.ray_cast(origin_l, dir_l, 1.0e9)
            if hit is None or hit[0] is None:
                context.scene.mbm_tools.last_status = "Pick Face: no hit (click closer to the boundary)"
                return {'RUNNING_MODAL'}

            face_index = int(hit[2])

            props = context.scene.mbm_tools
            lbl = props.labels[self._label_index]
            lbl.attach_face_index = face_index
            props.active_label_index = self._label_index
            props.last_status = f"Picked face {face_index} for {lbl.name}"

            if props.pick_auto_apply:
                def _apply_later():
                    try:
                        apply_scene_from_props(bpy.context, safe=True)
                    except Exception as e:
                        bpy.context.scene.mbm_tools.last_status = f"Auto-apply after pick FAILED: {e!r}"
                    return None
                bpy.app.timers.register(_apply_later, first_interval=0.01)

            return {'FINISHED'}

        return {'RUNNING_MODAL'}


# -----------------------------
# Port ops
# -----------------------------

class MBM_OT_AddPort(Operator):
    bl_idname = "mbm.add_port"
    bl_label = "Add Port"
    bl_description = "Add a port entry to the UI"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.mbm_tools
        idx = len(props.ports) + 1
        item = props.ports.add()
        item.name = f"port_{idx:02d}"
        item.target = props.boundary.name
        props.active_port_index = len(props.ports) - 1
        props.last_status = f"Added {item.name}"
        return {'FINISHED'}


class MBM_OT_RemovePort(Operator):
    bl_idname = "mbm.remove_port"
    bl_label = "Remove Port"
    bl_description = "Remove selected port entry"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.mbm_tools
        i = props.active_port_index
        if i < 0 or i >= len(props.ports):
            return {'CANCELLED'}
        name = props.ports[i].name
        props.ports.remove(i)
        props.active_port_index = min(max(0, i - 1), len(props.ports) - 1)
        props.last_status = f"Removed {name}"
        return {'FINISHED'}


class MBM_OT_SetPortAutoVertex(Operator):
    bl_idname = "mbm.set_port_auto_vertex"
    bl_label = "Set Auto Vertex"
    bl_description = "Set Vertex Index to -1 (auto select a good visible vertex)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.mbm_tools
        i = props.active_port_index
        if 0 <= i < len(props.ports):
            props.ports[i].attach_vertex_index = -1
            props.last_status = f"{props.ports[i].name}: Vertex Index set to AUTO (-1)"
        return {'FINISHED'}


class MBM_OT_PickPortVertex(Operator):
    bl_idname = "mbm.pick_port_vertex"
    bl_label = "Pick Vertex"
    bl_description = "Click near a vertex in the viewport to attach the active port to that vertex"
    bl_options = {'REGISTER', 'UNDO'}

    port_index: IntProperty(default=-1)

    def invoke(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            self.report({'ERROR'}, "Pick Vertex must be started from a 3D View area.")
            return {'CANCELLED'}

        props = context.scene.mbm_tools
        if len(props.ports) == 0:
            self.report({'ERROR'}, "No ports in UI. Load manifest or Add Port first.")
            return {'CANCELLED'}

        i = int(self.port_index if self.port_index >= 0 else props.active_port_index)
        if i < 0 or i >= len(props.ports):
            self.report({'ERROR'}, "No active port selected.")
            return {'CANCELLED'}

        self._port_index = i
        port = props.ports[i]
        boundary_name = port.target or props.boundary.name
        solid_name = f"{boundary_name}_Solid"
        solid_obj = bpy.data.objects.get(solid_name)
        if solid_obj is None:
            self.report({'ERROR'}, f"Boundary solid not found: {solid_name}. Apply once to build it.")
            return {'CANCELLED'}

        self._solid_obj = solid_obj
        self._inv_mw = solid_obj.matrix_world.inverted()
        self._inv_mw_3 = solid_obj.matrix_world.to_3x3().inverted()

        bvh = _build_bvh_for_solid(solid_obj)
        if bvh is None:
            self.report({'ERROR'}, f"Boundary solid mesh has no faces: {solid_name}")
            return {'CANCELLED'}
        self._bvh = bvh

        context.window_manager.modal_handler_add(self)
        props.last_status = "Pick Vertex: Left-click near a vertex; Esc/Right-click cancels"
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            context.scene.mbm_tools.last_status = "Pick Vertex cancelled"
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            region_win, rv3d = _get_view3d_window_region_and_rv3d(context)
            if region_win is None or rv3d is None:
                self.report({'ERROR'}, "Could not access View3D window region.")
                return {'CANCELLED'}

            coord = (event.mouse_x - region_win.x, event.mouse_y - region_win.y)
            origin = view3d_utils.region_2d_to_origin_3d(region_win, rv3d, coord)
            direction = view3d_utils.region_2d_to_vector_3d(region_win, rv3d, coord)
            if origin is None or direction is None:
                self.report({'ERROR'}, "Failed to compute pick ray.")
                return {'CANCELLED'}

            origin_l = self._inv_mw @ origin
            dir_l = (self._inv_mw_3 @ direction).normalized()

            hit = self._bvh.ray_cast(origin_l, dir_l, 1.0e9)
            if hit is None or hit[0] is None:
                context.scene.mbm_tools.last_status = "Pick Vertex: no hit (click closer to the boundary)"
                return {'RUNNING_MODAL'}

            hit_loc = hit[0]
            face_index = int(hit[2])

            me = self._solid_obj.data
            if face_index < 0 or face_index >= len(me.polygons):
                context.scene.mbm_tools.last_status = "Pick Vertex: invalid face hit"
                return {'RUNNING_MODAL'}

            poly = me.polygons[face_index]
            verts = list(poly.vertices)
            if not verts:
                context.scene.mbm_tools.last_status = "Pick Vertex: face has no vertices"
                return {'RUNNING_MODAL'}

            # Choose closest vertex on the hit face to the hit point
            best_vi = verts[0]
            best_d2 = (me.vertices[best_vi].co - hit_loc).length_squared
            for vi in verts[1:]:
                d2 = (me.vertices[vi].co - hit_loc).length_squared
                if d2 < best_d2:
                    best_d2 = d2
                    best_vi = vi

            props = context.scene.mbm_tools
            port = props.ports[self._port_index]
            port.attach_vertex_index = int(best_vi)
            props.active_port_index = self._port_index
            props.last_status = f"Picked vertex {best_vi} for {port.name}"

            if props.pick_auto_apply:
                def _apply_later():
                    try:
                        apply_scene_from_props(bpy.context, safe=True)
                    except Exception as e:
                        bpy.context.scene.mbm_tools.last_status = f"Auto-apply after pick FAILED: {e!r}"
                    return None
                bpy.app.timers.register(_apply_later, first_interval=0.01)

            return {'FINISHED'}

        return {'RUNNING_MODAL'}



# -----------------------------
# Visibility helper ops (list camera-visible vertex/face indices)
# -----------------------------

class MBM_OT_RefreshVisibleIndices(Operator):
    bl_idname = "mbm.refresh_visible_indices"
    bl_label = "Refresh Visible Indices"
    bl_description = "Compute which boundary vertices/faces are visible in the active camera image"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.mbm_tools
        scene = context.scene

        cam = scene.camera
        if cam is None or cam.type != 'CAMERA':
            self.report({'ERROR'}, "No active scene camera set (Scene Properties > Camera).")
            return {'CANCELLED'}

        boundary_name = props.boundary.name or "boundary"
        solid_name = f"{boundary_name}_Solid"
        solid_obj = bpy.data.objects.get(solid_name)
        if solid_obj is None:
            self.report({'ERROR'}, f"Boundary solid not found: {solid_name}. Click Apply once to build it.")
            return {'CANCELLED'}

        bvh = _build_bvh_for_solid(solid_obj)
        if bvh is None:
            self.report({'ERROR'}, f"Boundary solid has no faces: {solid_name}")
            return {'CANCELLED'}

        # Clear previous results
        props.visible_vertices.clear()
        props.visible_faces.clear()

        render = scene.render
        W = int(render.resolution_x * render.resolution_percentage / 100)
        H = int(render.resolution_y * render.resolution_percentage / 100)

        mw = solid_obj.matrix_world
        inv = mw.inverted()
        cam_w = cam.matrix_world.translation
        cam_l = inv @ cam_w

        me = solid_obj.data

        # Epsilon for the "ray hits the vertex" check.
        eps = max(0.01, float(props.boundary.vertex_radius) * 0.75)

        vis_verts = []
        for v in me.vertices:
            w = mw @ v.co
            ndc = world_to_camera_view(scene, cam, w)
            if ndc.z < 0.0:
                continue
            if not (0.0 <= ndc.x <= 1.0 and 0.0 <= ndc.y <= 1.0):
                continue

            dir_l = v.co - cam_l
            dist = dir_l.length
            if dist < 1e-9:
                continue
            dir_l.normalize()

            hit = bvh.ray_cast(cam_l, dir_l, dist + 1.0e-6)
            if hit is None or hit[0] is None:
                continue

            # Visible if the first hit along the ray is at (or very near) the vertex.
            if (hit[0] - v.co).length <= eps:
                vis_verts.append((int(v.index), float(ndc.x) * W, float(ndc.y) * H, float(ndc.z)))

        vis_verts.sort(key=lambda t: t[0])
        for idx, x, y, z in vis_verts:
            it = props.visible_vertices.add()
            it.index = int(idx)
            it.x_px = float(x)
            it.y_px = float(y)
            it.ndc_z = float(z)

        vis_faces = []
        for p in me.polygons:
            c_l = p.center
            c_w = mw @ c_l
            ndc = world_to_camera_view(scene, cam, c_w)
            if ndc.z < 0.0:
                continue
            if not (0.0 <= ndc.x <= 1.0 and 0.0 <= ndc.y <= 1.0):
                continue

            dir_l = c_l - cam_l
            dist = dir_l.length
            if dist < 1e-9:
                continue
            dir_l.normalize()

            hit = bvh.ray_cast(cam_l, dir_l, dist + 1.0e-6)
            if hit is None or hit[0] is None:
                continue
            face_i = int(hit[2])

            # A face is considered visible if the first hit to its center is that face.
            if face_i == int(p.index):
                vis_faces.append((int(p.index), float(ndc.x) * W, float(ndc.y) * H, float(ndc.z)))

        vis_faces.sort(key=lambda t: t[0])
        for idx, x, y, z in vis_faces:
            it = props.visible_faces.add()
            it.index = int(idx)
            it.x_px = float(x)
            it.y_px = float(y)
            it.ndc_z = float(z)

        props.active_visible_vertex_index = 0
        props.active_visible_face_index = 0
        props.last_status = f"Visible indices refreshed: {len(vis_verts)} verts, {len(vis_faces)} faces"
        return {'FINISHED'}


class MBM_OT_UseVisibleVertexForActivePort(Operator):
    bl_idname = "mbm.use_visible_vertex_for_port"
    bl_label = "Use Selected Visible Vertex"
    bl_description = "Set the active port's Vertex Index to the selected visible vertex"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.mbm_tools
        if len(props.visible_vertices) == 0:
            self.report({'ERROR'}, "No visible vertices listed. Click Refresh Visible Indices first.")
            return {'CANCELLED'}
        if not (0 <= props.active_visible_vertex_index < len(props.visible_vertices)):
            self.report({'ERROR'}, "No visible vertex selected.")
            return {'CANCELLED'}
        if not (0 <= props.active_port_index < len(props.ports)):
            self.report({'ERROR'}, "No active port selected.")
            return {'CANCELLED'}

        vi = int(props.visible_vertices[props.active_visible_vertex_index].index)
        port = props.ports[props.active_port_index]
        port.attach_vertex_index = vi
        props.last_status = f"{port.name}: Vertex Index set to {vi}"

        if props.pick_auto_apply:
            def _apply_later():
                try:
                    apply_scene_from_props(bpy.context, safe=True)
                except Exception as e:
                    bpy.context.scene.mbm_tools.last_status = f"Auto-apply FAILED: {e!r}"
                return None
            bpy.app.timers.register(_apply_later, first_interval=0.01)

        return {'FINISHED'}


class MBM_OT_UseVisibleFaceForActiveLabel(Operator):
    bl_idname = "mbm.use_visible_face_for_label"
    bl_label = "Use Selected Visible Face"
    bl_description = "Set the active label's Face Index to the selected visible face"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.mbm_tools
        if len(props.visible_faces) == 0:
            self.report({'ERROR'}, "No visible faces listed. Click Refresh Visible Indices first.")
            return {'CANCELLED'}
        if not (0 <= props.active_visible_face_index < len(props.visible_faces)):
            self.report({'ERROR'}, "No visible face selected.")
            return {'CANCELLED'}
        if not (0 <= props.active_label_index < len(props.labels)):
            self.report({'ERROR'}, "No active label selected.")
            return {'CANCELLED'}

        fi = int(props.visible_faces[props.active_visible_face_index].index)
        lab = props.labels[props.active_label_index]
        lab.attach_face_index = fi
        props.last_status = f"{lab.name}: Face Index set to {fi}"

        if props.pick_auto_apply:
            def _apply_later():
                try:
                    apply_scene_from_props(bpy.context, safe=True)
                except Exception as e:
                    bpy.context.scene.mbm_tools.last_status = f"Auto-apply FAILED: {e!r}"
                return None
            bpy.app.timers.register(_apply_later, first_interval=0.01)

        return {'FINISHED'}


# -----------------------------
# UI lists
# -----------------------------

class MBM_UL_LabelList(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.prop(item, "name", text="", emboss=False, icon='OUTLINER_OB_FONT')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="")


class MBM_UL_PortList(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.prop(item, "name", text="", emboss=False, icon='EMPTY_ARROWS')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="")



class MBM_UL_VisibleVertexList(UIList):
    bl_idname = "MBM_UL_VisibleVertexList"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=f"V{item.index}  ({item.x_px:.0f}, {item.y_px:.0f})", icon='VERTEXSEL')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=str(item.index))


class MBM_UL_VisibleFaceList(UIList):
    bl_idname = "MBM_UL_VisibleFaceList"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=f"F{item.index}  ({item.x_px:.0f}, {item.y_px:.0f})", icon='FACESEL')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=str(item.index))


# -----------------------------
# Panels
# -----------------------------

def _draw_header(layout, props):
    row = layout.row(align=True)
    row.operator("mbm.use_cli_paths", icon="IMPORT")
    row.operator("mbm.load_manifest", icon="FILE_REFRESH")
    row.operator("mbm.save_manifest", icon="FILE_TICK")
    op = row.operator("mbm.apply_scene", icon="PLAY")
    op.safe = True

    if props.last_status:
        box = layout.box()
        box.label(text=f"Status: {props.last_status}")


class MBM_PT_Root(Panel):
    bl_label = "MBM Tools"
    bl_idname = "MBM_PT_mbm_tools_root"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"

    def draw(self, context):
        layout = self.layout
        props = context.scene.mbm_tools
        layout.use_property_split = True
        layout.use_property_decorate = False

        _draw_header(layout, props)

        box = layout.box()
        box.label(text="Files", icon="FILE_FOLDER")
        box.prop(props, "manifest_path")
        box.prop(props, "builder_path")
        box.prop(props, "auto_load_manifest_on_startup")
        box.prop(props, "reload_builder_each_apply")

        box = layout.box()
        box.label(text="Interaction", icon="PREFERENCES")
        box.prop(props, "pick_auto_apply")
        row = box.row(align=True)
        row.prop(props, "live_update")
        row.prop(props, "live_update_delay")


class MBM_PT_Boards(Panel):
    bl_label = "Boards"
    bl_idname = "MBM_PT_mbm_tools_boards"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"
    bl_parent_id = "MBM_PT_mbm_tools_root"
    bl_options = set()

    def draw(self, context):
        layout = self.layout
        props = context.scene.mbm_tools
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(props, "board_plane_mode")

        row = layout.row(align=True)
        op = row.operator("mbm.set_board_plane_mode", text="Align to Camera", icon="CAMERA_DATA")
        
        row2 = layout.row(align=True)
        opb = row2.operator("mbm.bake_camera_and_apply", text="Bake Camera + Align", icon="CAMERA_DATA")
        opb.plane_mode = "CAMERA"
        opb2 = row2.operator("mbm.bake_camera_and_apply", text="Bake Camera + Perp", icon="CON_ROTLIKE")
        opb2.plane_mode = "AXIS"

        op.mode = "CAMERA"
        op.apply_now = True
        op2 = row.operator("mbm.set_board_plane_mode", text="Perp to Ray", icon="CON_ROTLIKE")
        op2.mode = "AXIS"
        op2.apply_now = True


class MBM_PT_Styles(Panel):
    bl_label = "Styles"
    bl_idname = "MBM_PT_mbm_tools_styles"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"
    bl_parent_id = "MBM_PT_mbm_tools_root"
    bl_options = set()

    def draw(self, context):
        layout = self.layout
        props = context.scene.mbm_tools
        st = props.styles

        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(st, "enforce_global")
        layout.prop(st, "global_scale")

        col = layout.column(align=True)
        col.label(text="Port + Label sizes/colors are set here (not per-item).", icon="INFO")

        # Power ports
        box = layout.box()
        box.label(text="Power Ports")
        box.prop(st.port_power, "cyl_radius")
        box.prop(st.port_power, "cyl_length_min")
        box.prop(st.port_power, "cyl_length_max")
        box.prop(st.port_power, "cyl_color")
        box.prop(st.port_power, "cyl_alpha")
        box.prop(st.port_power, "arrow_enabled")
        if st.port_power.arrow_enabled:
            box.prop(st.port_power, "arrow_length")
            box.prop(st.port_power, "arrow_radius")
        box.prop(st.port_power, "board_gap")
        box.separator()
        box.prop(st.port_power, "text_size")
        box.prop(st.port_power, "text_extrude")
        box.prop(st.port_power, "text_color")
        box.prop(st.port_power, "text_alpha")
        box.separator()
        box.prop(st.port_power, "image_height")
        box.prop(st.port_power, "image_alpha")
        box.separator()
        box.prop(st.port_power, "layout_image_above_text")
        box.prop(st.port_power, "layout_spacing")
        box.prop(st.port_power, "layout_padding")

        # Info ports
        box = layout.box()
        box.label(text="Info Ports")
        box.prop(st.port_info, "cyl_radius")
        box.prop(st.port_info, "cyl_length_min")
        box.prop(st.port_info, "cyl_length_max")
        box.prop(st.port_info, "cyl_color")
        box.prop(st.port_info, "cyl_alpha")
        box.prop(st.port_info, "arrow_enabled")
        if st.port_info.arrow_enabled:
            box.prop(st.port_info, "arrow_length")
            box.prop(st.port_info, "arrow_radius")
        box.prop(st.port_info, "board_gap")
        box.separator()
        box.prop(st.port_info, "text_size")
        box.prop(st.port_info, "text_extrude")
        box.prop(st.port_info, "text_color")
        box.prop(st.port_info, "text_alpha")
        box.separator()
        box.prop(st.port_info, "image_height")
        box.prop(st.port_info, "image_alpha")
        box.separator()
        box.prop(st.port_info, "layout_image_above_text")
        box.prop(st.port_info, "layout_spacing")
        box.prop(st.port_info, "layout_padding")

        # Labels
        box = layout.box()
        box.label(text="Labels")
        box.prop(st.label, "cyl_radius")
        box.prop(st.label, "cyl_length_min")
        box.prop(st.label, "cyl_length_max")
        box.prop(st.label, "cyl_color")
        box.prop(st.label, "cyl_alpha")
        box.prop(st.label, "board_gap")
        box.separator()
        box.prop(st.label, "text_size")
        box.prop(st.label, "text_extrude")
        box.prop(st.label, "text_color")
        box.prop(st.label, "text_alpha")
        box.separator()
        box.prop(st.label, "image_height")
        box.prop(st.label, "image_alpha")
        box.separator()
        box.prop(st.label, "layout_image_above_text")
        box.prop(st.label, "layout_spacing")
        box.prop(st.label, "layout_padding")


class MBM_PT_Boundary(Panel):
    bl_label = "Boundary"
    bl_idname = "MBM_PT_mbm_tools_boundary"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"
    bl_parent_id = "MBM_PT_mbm_tools_root"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        b = context.scene.mbm_tools.boundary
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


class MBM_PT_Camera(Panel):
    bl_label = "Camera"
    bl_idname = "MBM_PT_mbm_tools_camera"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"
    bl_parent_id = "MBM_PT_mbm_tools_root"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        c = context.scene.mbm_tools.camera
        props = context.scene.mbm_tools
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(c, "lens_mm")
        layout.prop(c, "distance")
        layout.prop(c, "use_location")
        if c.use_location:
            layout.prop(c, "location")
        layout.prop(c, "target_mode")
        if c.target_mode == "CUSTOM":
            layout.prop(c, "target")

        box = layout.box()
        box.label(text="Reproducible framing")
        box.prop(c, "use_rotation")
        if c.use_rotation:
            box.prop(c, "rotation_quat")
        row = box.row(align=True)
        row.operator("mbm.capture_camera", icon="OUTLINER_OB_CAMERA")
        row.operator("mbm.clear_camera_rotation", icon="X")



class MBM_PT_Visibility(Panel):
    bl_label = "Visible Indices"
    bl_idname = "MBM_PT_mbm_tools_visibility"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"
    bl_parent_id = "MBM_PT_mbm_tools_root"
    bl_options = set()

    def draw(self, context):
        layout = self.layout
        props = context.scene.mbm_tools
        layout.use_property_split = False
        layout.use_property_decorate = False

        row = layout.row(align=True)
        row.operator("mbm.refresh_visible_indices", icon="VIEW_CAMERA", text="Refresh (Camera-visible indices)")
        if context.scene.camera is None:
            layout.label(text="No active camera set in Scene Properties.", icon="ERROR")

        boxv = layout.box()
        boxv.label(text=f"Visible Vertices ({len(props.visible_vertices)})")
        boxv.template_list("MBM_UL_VisibleVertexList", "", props, "visible_vertices", props, "active_visible_vertex_index", rows=6)
        if 0 <= props.active_port_index < len(props.ports):
            boxv.label(text=f"Active Port: {props.ports[props.active_port_index].name}", icon="DOT")
        boxv.operator("mbm.use_visible_vertex_for_port", icon="CHECKMARK", text="Use selected vertex for active port")

        boxf = layout.box()
        boxf.label(text=f"Visible Faces ({len(props.visible_faces)})")
        boxf.template_list("MBM_UL_VisibleFaceList", "", props, "visible_faces", props, "active_visible_face_index", rows=6)
        if 0 <= props.active_label_index < len(props.labels):
            boxf.label(text=f"Active Label: {props.labels[props.active_label_index].name}", icon="DOT")
        boxf.operator("mbm.use_visible_face_for_label", icon="CHECKMARK", text="Use selected face for active label")



class MBM_PT_Ports(Panel):
    bl_label = "Ports"
    bl_idname = "MBM_PT_mbm_tools_ports"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"
    bl_parent_id = "MBM_PT_mbm_tools_root"
    bl_options = set()

    def draw(self, context):
        layout = self.layout
        props = context.scene.mbm_tools
        layout.use_property_split = True
        layout.use_property_decorate = False

        row = layout.row()
        row.template_list("MBM_UL_PortList", "", props, "ports", props, "active_port_index", rows=3)
        col = row.column(align=True)
        col.operator("mbm.add_port", icon="ADD", text="")
        col.operator("mbm.remove_port", icon="REMOVE", text="")

        i = props.active_port_index
        if 0 <= i < len(props.ports):
            p = props.ports[i]
            layout.separator()
            layout.prop(p, "name")
            layout.prop(p, "target")

            box = layout.box()
            box.label(text="Attach")
            box.prop(p, "attach_vertex_index")
            rr = _resolved_attach_index(p.name)
            if rr:
                box.label(text=f"Resolved Vertex (last apply): {rr}", icon="INFO")
            row2 = box.row(align=True)
            row2.operator("mbm.set_port_auto_vertex", icon="RECOVER_AUTO", text="Auto")
            op = row2.operator("mbm.pick_port_vertex", icon="RESTRICT_SELECT_OFF", text="Pick Vertex")
            op.port_index = i

            box = layout.box()
            box.label(text="Flow")
            box.prop(p, "flow_kind")
            box.prop(p, "flow_direction")

            box = layout.box()
            box.label(text="Style")
            box.label(text="Sizes/colors are controlled in the Styles panel.", icon="INFO")

            box = layout.box()
            box.label(text="Content")
            box.prop(p, "text_value")
            box.prop(p, "text_offset_y")
            box.prop(p, "font_path")
            box.prop(p, "image_filepath")
            box.prop(p, "image_scale")
        else:
            layout.label(text="No ports loaded. Click Load, or Add Port.", icon="INFO")


class MBM_PT_Labels(Panel):
    bl_label = "Labels"
    bl_idname = "MBM_PT_mbm_tools_labels"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tool"
    bl_parent_id = "MBM_PT_mbm_tools_root"
    bl_options = set()

    def draw(self, context):
        layout = self.layout
        props = context.scene.mbm_tools
        layout.use_property_split = True
        layout.use_property_decorate = False

        row = layout.row()
        row.template_list("MBM_UL_LabelList", "", props, "labels", props, "active_label_index", rows=3)
        col = row.column(align=True)
        col.operator("mbm.add_label", icon="ADD", text="")
        col.operator("mbm.remove_label", icon="REMOVE", text="")

        i = props.active_label_index
        if 0 <= i < len(props.labels):
            l = props.labels[i]
            layout.separator()
            layout.prop(l, "name")
            layout.prop(l, "target")

            box = layout.box()
            box.label(text="Attach")
            box.prop(l, "attach_face_index")
            rr = _resolved_attach_index(l.name)
            if rr:
                box.label(text=f"Resolved Face (last apply): {rr}", icon="INFO")
            row2 = box.row(align=True)
            row2.operator("mbm.set_label_auto_face", icon="RECOVER_AUTO", text="Auto")
            op = row2.operator("mbm.pick_label_face", icon="RESTRICT_SELECT_OFF", text="Pick Face")
            op.label_index = i

            box = layout.box()
            box.label(text="Direction")
            box.prop(l, "direction")

            box = layout.box()
            box.label(text="Style")
            box.label(text="Sizes/colors are controlled in the Styles panel.", icon="INFO")

            box = layout.box()
            box.label(text="Content")
            box.prop(l, "text_value")
            box.prop(l, "text_offset_y")
            box.prop(l, "font_path")
            box.prop(l, "image_filepath")
            box.prop(l, "image_scale")
        else:
            layout.label(text="No labels loaded. Click Load, or Add Label.", icon="INFO")


# Properties editor -> Scene tab (mirrors root header + file paths)
class MBM_PT_Scene(Panel):
    bl_label = "MBM Tools"
    bl_idname = "MBM_PT_mbm_tools_scene"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"

    def draw(self, context):
        layout = self.layout
        props = context.scene.mbm_tools
        layout.use_property_split = True
        layout.use_property_decorate = False

        _draw_header(layout, props)

        box = layout.box()
        box.label(text="Files", icon="FILE_FOLDER")
        box.prop(props, "manifest_path")
        box.prop(props, "builder_path")
        box.prop(props, "auto_load_manifest_on_startup")
        box.prop(props, "reload_builder_each_apply")


# -----------------------------
# Register
# -----------------------------

classes = (
    MBM_BoundaryProps,
    MBM_CameraProps,
    MBM_LabelProps,
    MBM_PortProps,

    MBM_PowerPortStyleProps,
    MBM_InfoPortStyleProps,
    MBM_LabelStyleProps,
    MBM_StylesProps,

    MBM_VisibleIndexItem,
    MBM_ToolsProps,

    MBM_OT_UseCLIPaths,
    MBM_OT_LoadManifest,
    MBM_OT_SaveManifest,
    MBM_OT_ApplyScene,
    MBM_OT_CaptureCamera,
    MBM_OT_ClearCameraRotation,
    MBM_OT_SetBoardPlaneMode,
    MBM_OT_BakeCameraAndApply,

    MBM_OT_AddLabel,
    MBM_OT_RemoveLabel,
    MBM_OT_SetLabelAutoFace,
    MBM_OT_PickLabelFace,

    MBM_OT_AddPort,
    MBM_OT_RemovePort,
    MBM_OT_SetPortAutoVertex,
    MBM_OT_PickPortVertex,

    MBM_OT_RefreshVisibleIndices,
    MBM_OT_UseVisibleVertexForActivePort,
    MBM_OT_UseVisibleFaceForActiveLabel,

    MBM_UL_LabelList,
    MBM_UL_PortList,
    MBM_UL_VisibleVertexList,
    MBM_UL_VisibleFaceList,

    MBM_PT_Root,
    MBM_PT_Boards,
    MBM_PT_Styles,
    MBM_PT_Boundary,
    MBM_PT_Camera,
    MBM_PT_Visibility,
    MBM_PT_Ports,
    MBM_PT_Labels,
    MBM_PT_Scene,
)


def _post_register_init():
    # Fill paths, optionally auto-load manifest
    for scn in bpy.data.scenes:
        if not hasattr(scn, "mbm_tools"):
            continue
        props = scn.mbm_tools
        fill_paths_from_cli(props)
        if props.auto_load_manifest_on_startup and not props.raw_manifest_json.strip():
            load_manifest_file_into_props(props)
    return None


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.mbm_tools = PointerProperty(type=MBM_ToolsProps)

    bpy.app.timers.register(_post_register_init, first_interval=0.1)


def unregister():
    if hasattr(bpy.types.Scene, "mbm_tools"):
        del bpy.types.Scene.mbm_tools
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
