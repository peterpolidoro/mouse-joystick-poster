# scripts/setup_scene.py
#
# Scene builder for: boundary + label objects
# - "boundary" renders a triangulated solid as:
#     - cylinders for edges
#     - spheres for vertices
#     - (optional) thick face plates (Solidify)
# - "label" attaches a cylinder to a visible boundary FACE center,
#   then places a billboarded (camera-facing) text and/or image at the tip.
#
# This script avoids bpy.context.object and avoids mesh-add operators for geometry creation,
# which improves reliability in --background renders.

import argparse
import copy
import json
import math
import os
import random
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from bpy_extras.object_utils import world_to_camera_view
# ----------------------------
# Data structs
# ----------------------------

@dataclass
class BoundaryInfo:
    """Information about a built boundary object (used for labels/camera auto-placement)."""
    name: str
    collection: bpy.types.Collection
    root: bpy.types.Object
    solid: bpy.types.Object
    radius: float
    # Radius of the visible vertex spheres (useful for auto offsets on vertex-attached ports).
    vertex_radius: float = 0.0

# ----------------------------
# Basic helpers
# ----------------------------

def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def parse_color_rgb(value: Any, default=(1.0, 1.0, 1.0)) -> Tuple[float, float, float]:
    """
    Accepts:
      - [r,g,b] floats 0..1
      - [r,g,b] ints 0..255
      - "#RRGGBB" hex string
    """
    if value is None:
        return default

    if isinstance(value, str):
        s = value.strip()
        if s.startswith("#"):
            s = s[1:]
        if len(s) == 6:
            r = int(s[0:2], 16) / 255.0
            g = int(s[2:4], 16) / 255.0
            b = int(s[4:6], 16) / 255.0
            return (r, g, b)
        return default

    if isinstance(value, (list, tuple)) and len(value) >= 3:
        r, g, b = float(value[0]), float(value[1]), float(value[2])
        if max(r, g, b) > 1.0:  # assume 0..255
            r, g, b = r / 255.0, g / 255.0, b / 255.0
        return (clamp01(r), clamp01(g), clamp01(b))

    return default



# ----------------------------
# Styles (global look for ports/labels)
# ----------------------------

def _deep_merge_defaults(dst: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively fill missing keys in dst using defaults (does not overwrite existing values)."""
    for k, v in (defaults or {}).items():
        if isinstance(v, dict):
            cur = dst.get(k, None)
            if not isinstance(cur, dict):
                dst[k] = copy.deepcopy(v)
            else:
                _deep_merge_defaults(cur, v)
        else:
            if k not in dst or dst[k] is None:
                dst[k] = v
    return dst


def _apply_style_to_spec(spec: Dict[str, Any], style: Dict[str, Any], enforce: bool, *, is_port: bool) -> Dict[str, Any]:
    """Apply a style dict onto an object spec.

    - If enforce=False: style acts as defaults (fills only missing).
    - If enforce=True: style overwrites cylinder/arrow/layout/etc, but preserves object-specific
      text.value, text.font, and image.filepath.
    """
    if not isinstance(style, dict) or not style:
        return spec

    out = copy.deepcopy(spec) if isinstance(spec, dict) else {}
    if not enforce:
        return _deep_merge_defaults(out, style)

    # Enforced: override selected sections wholesale, while preserving per-object content.
    preserve_text_value = None
    preserve_text_font = None
    preserve_text_offset_x = None
    preserve_text_offset_y = None
    preserve_image_filepath = None
    preserve_image_scale = None
    if isinstance(out.get("text"), dict):
        preserve_text_value = out["text"].get("value", None)
        preserve_text_font = out["text"].get("font", None)
        preserve_text_offset_x = out["text"].get("offset_x", None)
        preserve_text_offset_y = out["text"].get("offset_y", None)
    if isinstance(out.get("image"), dict):
        preserve_image_filepath = out["image"].get("filepath", None)
        preserve_image_scale = out["image"].get("scale", None)

    for section in ("cylinder", "arrow", "layout", "board"):
        if isinstance(style.get(section), dict):
            out[section] = copy.deepcopy(style[section])

    # Text: preserve value/font
    if isinstance(style.get("text"), dict):
        out["text"] = copy.deepcopy(style["text"])
        if preserve_text_value is not None:
            out["text"]["value"] = preserve_text_value
        if preserve_text_font is not None:
            out["text"]["font"] = preserve_text_font
        # Placement tweaks should remain per-object even when global styles are enforced.
        if preserve_text_offset_x is not None and "offset_x" not in out["text"]:
            out["text"]["offset_x"] = preserve_text_offset_x
        if preserve_text_offset_y is not None and "offset_y" not in out["text"]:
            out["text"]["offset_y"] = preserve_text_offset_y

    # Image: preserve filepath
    if isinstance(style.get("image"), dict):
        out["image"] = copy.deepcopy(style["image"])
        if preserve_image_filepath is not None:
            out["image"]["filepath"] = preserve_image_filepath
        if preserve_image_scale is not None and "scale" not in out["image"]:
            out["image"]["scale"] = preserve_image_scale

    return out


def _get_port_kind(spec: Dict[str, Any]) -> str:
    flow_cfg = spec.get("flow", {}) if isinstance(spec.get("flow", {}), dict) else {}
    return str(flow_cfg.get("kind", spec.get("flow_kind", "POWER")) or "POWER").upper()


def _get_global_scale(manifest: Dict[str, Any]) -> float:
    """Return a positive global scale factor (defaults to 1.0).

    Stored at manifest["styles"]["global_scale"] (preferred), with fallback to manifest["global_scale"].
    """
    styles_cfg = manifest.get("styles", {}) if isinstance(manifest.get("styles", {}), dict) else {}
    gs = styles_cfg.get("global_scale", manifest.get("global_scale", 1.0))
    try:
        gs_f = float(gs)
        return gs_f if gs_f > 0.0 else 1.0
    except Exception:
        return 1.0


def _apply_global_scale_to_spec(spec: Dict[str, Any], s: float) -> Dict[str, Any]:
    """Multiply all *length-like* numeric fields in a port/label spec by s."""
    if s is None:
        s = 1.0
    try:
        s = float(s)
    except Exception:
        s = 1.0
    if abs(s - 1.0) < 1e-12:
        return spec

    out = copy.deepcopy(spec) if isinstance(spec, dict) else {}

    def _scale(d: Any, keys: Sequence[str]):
        if not isinstance(d, dict):
            return
        for k in keys:
            if k in d and isinstance(d[k], (int, float)):
                d[k] = float(d[k]) * s

    _scale(out.get("cylinder"), ("radius", "length", "length_min", "length_max", "base_offset"))
    _scale(out.get("arrow"), ("length", "radius", "size", "width"))
    _scale(out.get("board"), ("gap",))
    _scale(out.get("layout"), ("spacing", "padding"))
    # Text + text placement offsets in the board plane
    _scale(out.get("text"), ("size", "extrude", "bevel_depth", "offset_x", "offset_y"))
    # Image height is base size; image.scale is a *multiplier* and should not be scaled.
    _scale(out.get("image"), ("height",))

    return out



def rad(deg: float) -> float:
    return float(deg) * math.pi / 180.0


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    p = argparse.ArgumentParser(description="Set up a Blender scene from a JSON manifest.")
    p.add_argument("--manifest", default="manifest.json", help="Path to manifest.json")
    p.add_argument("--render", action="store_true", help="Render a still image and quit")
    return p.parse_args(argv)


def load_manifest(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("manifest.json must contain a JSON object at the top level.")
    return data


# ----------------------------
# Scene + collection utilities
# ----------------------------

def scene_and_root_collection():
    scn = getattr(bpy.context, "scene", None) or (bpy.data.scenes[0] if bpy.data.scenes else None)
    if scn is None:
        raise RuntimeError("No Blender scene available.")
    return scn, scn.collection


def clear_scene_data():
    # Clear in-module caches that may hold references to datablocks we are about to delete.
    # This prevents errors like: ReferenceError('StructRNA of type Mesh has been removed')
    try:
        _mesh_cache.clear()
        _mesh_mat_cache.clear()
    except Exception:
        pass
    # Remove objects
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    # Remove datablocks we create
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh, do_unlink=True)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat, do_unlink=True)
    for cam in list(bpy.data.cameras):
        bpy.data.cameras.remove(cam, do_unlink=True)
    for light in list(bpy.data.lights):
        bpy.data.lights.remove(light, do_unlink=True)
    for img in list(bpy.data.images):
        # don't delete builtin generated images
        if img.users == 0 and img.source != 'GENERATED':
            bpy.data.images.remove(img, do_unlink=True)
    for font in list(bpy.data.fonts):
        # keep default fonts
        pass


def ensure_collection(name: str, parent: bpy.types.Collection) -> bpy.types.Collection:
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
    # bpy_prop_collection containment expects strings; use .get()
    if parent.children.get(coll.name) is None:
        parent.children.link(coll)
    return coll


def create_empty(name: str, collection: bpy.types.Collection) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "PLAIN_AXES"
    collection.objects.link(obj)
    return obj


def parent_keep_world(child: bpy.types.Object, parent: bpy.types.Object):
    """Parent child to parent while keeping its world transform stable (no direct matrix_world write)."""
    if parent is None:
        child.parent = None
        return
    child.parent = parent
    # Using parent's inverse here is typically enough to preserve world transform in Blender,
    # and avoids decomposing/rewriting matrices that can introduce shear in some setups.
    child.matrix_parent_inverse = parent.matrix_world.inverted()


def parent_inherit(child: bpy.types.Object, parent: bpy.types.Object):
    """Parent child to parent so child inherits parent's transform (local coords are in parent space)."""
    child.parent = parent
    # Identity parent-inverse means: child's local transforms are expressed directly in parent space.
    child.matrix_parent_inverse = Matrix.Identity(4)


# ----------------------------
# Materials
# ----------------------------

def make_transparent_material(
    name: str,
    color_rgb: Tuple[float, float, float],
    alpha: float,
    roughness: float = 0.35,
    emission_strength: float = 0.0,
) -> bpy.types.Material:
    """
    Mix Transparent BSDF with Principled (and optional Emission) using alpha.
    alpha=0 => invisible, alpha=1 => opaque
    """
    alpha = clamp01(alpha)

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (700, 0)

    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (0, -120)
    principled.inputs["Base Color"].default_value = (color_rgb[0], color_rgb[1], color_rgb[2], 1.0)
    principled.inputs["Roughness"].default_value = float(roughness)

    # Optional emission to keep fluorescent colors punchy
    if emission_strength > 0.0:
        emission = nodes.new("ShaderNodeEmission")
        emission.location = (0, -320)
        emission.inputs["Color"].default_value = (color_rgb[0], color_rgb[1], color_rgb[2], 1.0)
        emission.inputs["Strength"].default_value = float(emission_strength)

        add = nodes.new("ShaderNodeAddShader")
        add.location = (220, -220)
        links.new(principled.outputs[0], add.inputs[0])
        links.new(emission.outputs[0], add.inputs[1])
        shaded = add.outputs[0]
    else:
        shaded = principled.outputs[0]

    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (0, 120)

    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (450, 0)

    alpha_node = nodes.new("ShaderNodeValue")
    alpha_node.location = (-220, 0)
    alpha_node.outputs[0].default_value = alpha

    # Fac: 0 -> Transparent, 1 -> Shaded
    links.new(alpha_node.outputs[0], mix.inputs["Fac"])
    links.new(transparent.outputs[0], mix.inputs[1])
    links.new(shaded, mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])

    # viewport preview
    mat.diffuse_color = (color_rgb[0], color_rgb[1], color_rgb[2], alpha)

    if hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND" if alpha < 1.0 else "OPAQUE"
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "NONE" if alpha <= 0.0 else "HASHED"

    return mat


def make_image_material(name: str, image: bpy.types.Image, alpha: float = 1.0) -> bpy.types.Material:
    alpha = clamp01(alpha)

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (700, 0)

    tex = nodes.new("ShaderNodeTexImage")
    tex.location = (0, 0)
    tex.image = image

    # Use Emission for documentation renders: lighting-independent and predictable.
    emission = nodes.new("ShaderNodeEmission")
    emission.location = (250, -120)
    emission.inputs["Strength"].default_value = 1.0

    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (250, 120)

    # Multiply image alpha by user alpha
    mul = nodes.new("ShaderNodeMath")
    mul.location = (250, 40)
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = alpha

    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (500, 0)

    # Texture sampling preferences
    try:
        tex.extension = "CLIP"
    except Exception:
        pass
    try:
        tex.interpolation = "Linear"
    except Exception:
        pass

    links.new(tex.outputs["Color"], emission.inputs["Color"])
    if "Alpha" in tex.outputs:
        links.new(tex.outputs["Alpha"], mul.inputs[0])
        links.new(mul.outputs[0], mix.inputs["Fac"])
    else:
        # No alpha channel, use user alpha
        v = nodes.new("ShaderNodeValue")
        v.outputs[0].default_value = alpha
        links.new(v.outputs[0], mix.inputs["Fac"])

    links.new(transparent.outputs[0], mix.inputs[1])
    links.new(emission.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])

    if hasattr(mat, "blend_method"):
        # Always use a transparency-capable mode; the shader includes transparency even
        # when alpha==1.0, and Eevee will otherwise render a white quad in many cases.
        mat.blend_method = "BLEND"
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "NONE"

    # Improves icon look in documentation renders
    try:
        mat.use_backface_culling = True
    except Exception:
        pass

    return mat


def assign_material(obj: bpy.types.Object, mat: bpy.types.Material):
    """Assign a material to an object *safely* even when the object shares a cached mesh.

    Blender stores materials on the *mesh datablock* (obj.data), not per-object.
    In this project we intentionally reuse cached primitive meshes (unit cylinder/plane/cone)
    across many objects for speed.

    If we directly clear/append obj.data.materials on a shared mesh, every other object that
    uses that same mesh will suddenly change appearance (classic 'last material wins' bug).

    Fix: keep a small cache of (base_mesh_name, material_name) -> mesh_copy_with_that_material,
    and swap obj.data to the appropriate copy.
    """
    if obj is None or obj.data is None:
        return
    data = obj.data
    if not hasattr(data, "materials"):
        return

    # If already correct, do nothing.
    try:
        mats = data.materials
        if len(mats) == 1 and mats[0] == mat:
            return
    except Exception:
        pass

    # Choose a stable key based on the current mesh name and material name.
    base_name = getattr(data, "name", "Mesh")
    mat_name = getattr(mat, "name", "Mat")
    key = f"{base_name}__MAT__{mat_name}"

    # Reuse an existing mesh copy if we already made one for this (mesh, material) pair.
    m = _mesh_mat_cache.get(key)
    if m is not None and m.name in bpy.data.meshes:
        obj.data = m
        return

    # Otherwise make a copy of the mesh datablock and assign the material there.
    try:
        m = data.copy()
    except Exception:
        # As a last resort, mutate in place (may affect shared meshes)
        data.materials.clear()
        data.materials.append(mat)
        return

    m.name = key[:63]  # Blender datablock names are limited; keep it short/stable.
    try:
        m.materials.clear()
        m.materials.append(mat)
    except Exception:
        pass

    _mesh_mat_cache[key] = m
    obj.data = m


# ----------------------------
# Primitive meshes (no bpy.ops)
# ----------------------------

_mesh_cache: Dict[str, bpy.types.Mesh] = {}
# Cache of mesh copies with a specific material applied (prevents shared-mesh material cross-talk)
_mesh_mat_cache: Dict[str, bpy.types.Mesh] = {}



def unit_plane_mesh() -> bpy.types.Mesh:
    key = "unit_plane"
    if key in _mesh_cache and _mesh_cache[key].name in bpy.data.meshes:
        return _mesh_cache[key]

    # 1x1 plane centered at origin in XY, normal +Z
    # IMPORTANT: provide an explicit UV map. Without UVs, Blender's Image Texture
    # node can evaluate to a constant color in renders (common symptom: a white
    # rectangle instead of the image).
    verts = [(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0)]
    faces = [(0, 1, 2, 3)]
    m = bpy.data.meshes.new("UnitPlane")
    m.from_pydata(verts, [], faces)
    m.update()

    # Add UVs: (0,0) bottom-left ... (1,1) top-right
    try:
        uv = m.uv_layers.new(name="UVMap")
        # One polygon with 4 loops
        if len(m.polygons) == 1:
            poly = m.polygons[0]
            loop_indices = range(poly.loop_start, poly.loop_start + poly.loop_total)
            # The loop->vertex order matches faces[0]
            uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
            for li, uvco in zip(loop_indices, uvs):
                uv.data[li].uv = uvco
    except Exception:
        pass
    _mesh_cache[key] = m
    return m


def unit_cylinder_mesh(sides: int, cap_ends: bool = True) -> bpy.types.Mesh:
    sides = max(3, int(sides))
    key = f"unit_cyl_{sides}_{int(cap_ends)}"
    if key in _mesh_cache and _mesh_cache[key].name in bpy.data.meshes:
        return _mesh_cache[key]

    verts: List[Tuple[float, float, float]] = []
    faces: List[Tuple[int, ...]] = []

    bottom_ring = []
    top_ring = []
    for j in range(sides):
        a = 2.0 * math.pi * j / sides
        x = math.cos(a)
        y = math.sin(a)
        bottom_ring.append(len(verts))
        verts.append((x, y, -1.0))
        top_ring.append(len(verts))
        verts.append((x, y, 1.0))

    bottom_center = None
    top_center = None
    if cap_ends:
        bottom_center = len(verts)
        verts.append((0.0, 0.0, -1.0))
        top_center = len(verts)
        verts.append((0.0, 0.0, 1.0))

    for j in range(sides):
        b0 = bottom_ring[j]
        b1 = bottom_ring[(j + 1) % sides]
        t1 = top_ring[(j + 1) % sides]
        t0 = top_ring[j]
        faces.append((b0, b1, t1, t0))

    if cap_ends and bottom_center is not None and top_center is not None:
        for j in range(sides):
            faces.append((top_center, top_ring[j], top_ring[(j + 1) % sides]))
            faces.append((bottom_center, bottom_ring[(j + 1) % sides], bottom_ring[j]))

    m = bpy.data.meshes.new(f"UnitCylinder_{sides}")
    m.from_pydata(verts, [], faces)
    m.update()
    # smooth shading
    for p in m.polygons:
        p.use_smooth = True

    _mesh_cache[key] = m
    return m



def unit_cone_mesh(sides: int, cap_base: bool = True) -> bpy.types.Mesh:
    """Create a unit cone mesh (no bpy.ops).

    - Aligned along local +Z
    - Centered at origin
    - Tip at z=+1
    - Base ring at z=-1 with radius 1

    Scaling convention matches the other unit meshes:
      scale.x/y = radius
      scale.z   = half-length
    """
    sides = max(3, int(sides))
    key = f"unit_cone_{sides}_{int(cap_base)}"
    if key in _mesh_cache and _mesh_cache[key].name in bpy.data.meshes:
        return _mesh_cache[key]

    verts: List[Tuple[float, float, float]] = []
    faces: List[Tuple[int, ...]] = []

    base_ring = []
    for j in range(sides):
        a = 2.0 * math.pi * j / sides
        x = math.cos(a)
        y = math.sin(a)
        base_ring.append(len(verts))
        verts.append((x, y, -1.0))

    tip = len(verts)
    verts.append((0.0, 0.0, 1.0))

    for j in range(sides):
        b0 = base_ring[j]
        b1 = base_ring[(j + 1) % sides]
        faces.append((b0, b1, tip))

    if cap_base:
        base_center = len(verts)
        verts.append((0.0, 0.0, -1.0))
        for j in range(sides):
            b0 = base_ring[j]
            b1 = base_ring[(j + 1) % sides]
            # Winding so normal points outward (-Z)
            faces.append((base_center, b1, b0))

    m = bpy.data.meshes.new(f"UnitCone_{sides}")
    m.from_pydata(verts, [], faces)
    m.update()
    for p in m.polygons:
        p.use_smooth = True

    _mesh_cache[key] = m
    return m

def unit_uv_sphere_mesh(segments: int, rings: int) -> bpy.types.Mesh:
    segs = max(3, int(segments))
    rcount = max(3, int(rings))
    key = f"unit_sphere_{segs}_{rcount}"
    if key in _mesh_cache and _mesh_cache[key].name in bpy.data.meshes:
        return _mesh_cache[key]

    verts: List[Tuple[float, float, float]] = []
    faces: List[Tuple[int, int, int]] = []

    top = 0
    verts.append((0.0, 0.0, 1.0))

    for i in range(1, rcount):
        theta = math.pi * i / rcount
        z = math.cos(theta)
        rr = math.sin(theta)
        for j in range(segs):
            phi = 2.0 * math.pi * j / segs
            x = rr * math.cos(phi)
            y = rr * math.sin(phi)
            verts.append((x, y, z))

    bottom = len(verts)
    verts.append((0.0, 0.0, -1.0))

    def ring_idx(i: int, j: int) -> int:
        return 1 + (i - 1) * segs + (j % segs)

    # top fan
    for j in range(segs):
        faces.append((top, ring_idx(1, j), ring_idx(1, j + 1)))

    # middle
    for i in range(1, rcount - 1):
        for j in range(segs):
            a = ring_idx(i, j)
            b = ring_idx(i, j + 1)
            c = ring_idx(i + 1, j + 1)
            d = ring_idx(i + 1, j)
            faces.append((a, d, c))
            faces.append((a, c, b))

    # bottom fan
    last_ring = rcount - 1
    for j in range(segs):
        faces.append((bottom, ring_idx(last_ring, j + 1), ring_idx(last_ring, j)))

    m = bpy.data.meshes.new(f"UnitSphere_{segs}_{rcount}")
    m.from_pydata(verts, [], faces)
    m.update()
    for p in m.polygons:
        p.use_smooth = True

    _mesh_cache[key] = m
    return m


# ----------------------------
# Shape topology
# ----------------------------

def scale_to_radius(verts: List[Vector], radius: float) -> List[Vector]:
    if not verts:
        return verts
    base_len = verts[0].length
    if base_len < 1e-9:
        return verts
    s = float(radius) / base_len
    return [v * s for v in verts]


def icosahedron_topology(radius: float) -> Tuple[List[Vector], List[Tuple[int, int, int]]]:
    phi = (1.0 + math.sqrt(5.0)) / 2.0
    verts = [
        Vector((-1.0,  phi, 0.0)),
        Vector(( 1.0,  phi, 0.0)),
        Vector((-1.0, -phi, 0.0)),
        Vector(( 1.0, -phi, 0.0)),
        Vector((0.0, -1.0,  phi)),
        Vector((0.0,  1.0,  phi)),
        Vector((0.0, -1.0, -phi)),
        Vector((0.0,  1.0, -phi)),
        Vector(( phi, 0.0, -1.0)),
        Vector(( phi, 0.0,  1.0)),
        Vector((-phi, 0.0, -1.0)),
        Vector((-phi, 0.0,  1.0)),
    ]
    verts = scale_to_radius(verts, radius)

    faces = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]
    return verts, faces


def subdivide_to_icosphere(
    verts: List[Vector],
    faces: List[Tuple[int, int, int]],
    radius: float,
    subdivisions: int
) -> Tuple[List[Vector], List[Tuple[int, int, int]]]:
    verts = [v.copy() for v in verts]
    faces = list(faces)

    for _ in range(max(0, int(subdivisions))):
        cache: Dict[Tuple[int, int], int] = {}
        new_faces: List[Tuple[int, int, int]] = []

        def mid(i: int, j: int) -> int:
            key = (i, j) if i < j else (j, i)
            if key in cache:
                return cache[key]
            v = (verts[i] + verts[j]) * 0.5
            if v.length > 1e-9:
                v = v.normalized() * float(radius)
            verts.append(v)
            idx = len(verts) - 1
            cache[key] = idx
            return idx

        for a, b, c in faces:
            ab = mid(a, b)
            bc = mid(b, c)
            ca = mid(c, a)
            new_faces.extend([
                (a, ab, ca),
                (b, bc, ab),
                (c, ca, bc),
                (ab, bc, ca),
            ])
        faces = new_faces

    return verts, faces


def tetrahedron_topology(radius: float) -> Tuple[List[Vector], List[Tuple[int, int, int]]]:
    verts = [
        Vector(( 1,  1,  1)),
        Vector((-1, -1,  1)),
        Vector((-1,  1, -1)),
        Vector(( 1, -1, -1)),
    ]
    verts = scale_to_radius(verts, radius)
    faces = [
        (0, 1, 2),
        (0, 3, 1),
        (0, 2, 3),
        (1, 3, 2),
    ]
    return verts, faces


def cube_topology(radius: float) -> Tuple[List[Vector], List[Tuple[int, ...]]]:
    # Cube vertices at distance sqrt(3) from origin, scale to radius
    verts = [
        Vector((-1, -1, -1)),
        Vector(( 1, -1, -1)),
        Vector(( 1,  1, -1)),
        Vector((-1,  1, -1)),
        Vector((-1, -1,  1)),
        Vector(( 1, -1,  1)),
        Vector(( 1,  1,  1)),
        Vector((-1,  1,  1)),
    ]
    verts = scale_to_radius(verts, radius)

    # 6 quad faces (outward winding)
    faces: List[Tuple[int, ...]] = [
        (0, 3, 2, 1),  # bottom (-Z)
        (4, 5, 6, 7),  # top (+Z)
        (0, 1, 5, 4),  # -Y
        (3, 7, 6, 2),  # +Y
        (1, 2, 6, 5),  # +X
        (0, 4, 7, 3),  # -X
    ]
    return verts, faces

def octahedron_topology(radius: float) -> Tuple[List[Vector], List[Tuple[int, int, int]]]:
    verts = [
        Vector(( 1, 0, 0)),
        Vector((-1, 0, 0)),
        Vector((0,  1, 0)),
        Vector((0, -1, 0)),
        Vector((0, 0,  1)),
        Vector((0, 0, -1)),
    ]
    verts = scale_to_radius(verts, radius)
    faces = [
        (0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
        (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5),
    ]
    return verts, faces


def dodecahedron_topology(radius: float) -> Tuple[List[Vector], List[Tuple[int, ...]]]:
    """
    Regular dodecahedron as the dual of an icosahedron.

    - Vertices are (normalized) face-centers of the icosahedron (20 verts)
    - Faces correspond to icosahedron vertices (12 pentagons)
    """
    ico_verts, ico_faces = icosahedron_topology(radius=1.0)

    # dodecahedron vertices: normalized icosa face centers
    dverts: List[Vector] = []
    face_to_dvert: List[int] = []
    for (a, b, c) in ico_faces:
        ctr = (ico_verts[a] + ico_verts[b] + ico_verts[c]) / 3.0
        if ctr.length > 1e-9:
            ctr = ctr.normalized()
        face_to_dvert.append(len(dverts))
        dverts.append(ctr)

    # For each icosahedron vertex, gather incident faces -> one pentagon face
    incident: List[List[int]] = [[] for _ in range(len(ico_verts))]
    for fi, (a, b, c) in enumerate(ico_faces):
        incident[a].append(fi)
        incident[b].append(fi)
        incident[c].append(fi)

    faces: List[Tuple[int, ...]] = []

    for vi, face_ids in enumerate(incident):
        if len(face_ids) != 5:
            continue

        axis = ico_verts[vi].normalized()  # outward face normal direction

        # choose basis on plane perpendicular to axis
        ref = Vector((1.0, 0.0, 0.0)) if abs(axis.x) < 0.9 else Vector((0.0, 1.0, 0.0))
        x_axis = (ref - axis * ref.dot(axis))
        if x_axis.length < 1e-9:
            x_axis = Vector((0.0, 0.0, 1.0)) - axis * axis.z
        x_axis.normalize()
        y_axis = axis.cross(x_axis).normalized()

        angs: List[Tuple[float, int]] = []
        for fi in face_ids:
            dv_idx = face_to_dvert[fi]
            dv = dverts[dv_idx]
            # project onto plane orthogonal to axis and sort by angle
            u = dv - axis * dv.dot(axis)
            if u.length > 1e-9:
                u.normalize()
            ang = math.atan2(u.dot(y_axis), u.dot(x_axis))
            angs.append((ang, dv_idx))

        angs.sort(key=lambda t: t[0])
        pent = [idx for _, idx in angs]

        # Ensure winding matches outward normal (axis)
        v0, v1, v2 = dverts[pent[0]], dverts[pent[1]], dverts[pent[2]]
        n = (v1 - v0).cross(v2 - v0)
        if n.length > 1e-9:
            n.normalize()
        if n.dot(axis) < 0.0:
            pent.reverse()

        faces.append(tuple(pent))

    # Scale vertices to requested circumradius
    dverts = [v.normalized() * float(radius) for v in dverts]
    return dverts, faces

def make_shape_topology(shape_cfg: Dict[str, Any], radius: float) -> Tuple[List[Vector], List[Tuple[int, ...]]]:
    st = str(shape_cfg.get("type", "icosahedron")).lower()
    sub = int(shape_cfg.get("subdivisions", shape_cfg.get("subdivision", 0)) or 0)

    if st in {"icosahedron"}:
        v, f = icosahedron_topology(radius)
        return v, [tuple(face) for face in f]
    if st in {"icosphere"}:
        v, f = icosahedron_topology(radius)
        # interpret subdivisions like: 1 -> no subdiv (icosahedron), 2 -> 1 subdiv, etc.
        actual = max(0, sub - 1)
        v2, f2 = subdivide_to_icosphere(v, f, radius, actual)
        return v2, [tuple(face) for face in f2]

    if st in {"tetrahedron"}:
        v, f = tetrahedron_topology(radius)
        return v, [tuple(face) for face in f]
    if st in {"cube"}:
        return cube_topology(radius)
    if st in {"octahedron"}:
        v, f = octahedron_topology(radius)
        return v, [tuple(face) for face in f]
    if st in {"dodecahedron"}:
        return dodecahedron_topology(radius)

    # fallback
    v, f = icosahedron_topology(radius)
    return v, [tuple(face) for face in f]

def boundary_edges_from_faces(faces: List[Tuple[int, ...]]) -> List[Tuple[int, int]]:
    """Return unique boundary edges from a polygon face list (triangles/quads/pentagons/...).

    This avoids interior diagonals introduced by triangulating planar n-gon faces.
    """
    edges = set()
    for face in faces:
        if len(face) < 2:
            continue
        for a, b in zip(face, face[1:] + face[:1]):  # type: ignore
            i, j = (a, b) if a < b else (b, a)
            edges.add((i, j))
    return sorted(edges)


def boundary_edges(verts: List[Vector], tri_faces: List[Tuple[int, int, int]], coplanar_dot: float = 0.999999) -> List[Tuple[int, int]]:
    """Derive true polyhedron edges from a triangulated surface.

    Triangulation of planar n-gon faces introduces internal diagonals. We remove
    those diagonals by dropping edges whose adjacent triangle normals are nearly
    parallel (coplanar triangles).
    """

    normals: List[Vector] = []
    for (a, b, c) in tri_faces:
        va, vb, vc = verts[a], verts[b], verts[c]
        n = (vb - va).cross(vc - va)
        if n.length > 1e-12:
            n.normalize()
        else:
            n = Vector((0.0, 0.0, 0.0))
        normals.append(n)

    edge_faces: Dict[Tuple[int, int], List[int]] = {}
    for fi, (a, b, c) in enumerate(tri_faces):
        for i, j in ((a, b), (b, c), (c, a)):
            key = (i, j) if i < j else (j, i)
            edge_faces.setdefault(key, []).append(fi)

    edges: List[Tuple[int, int]] = []
    for (i, j), fs in edge_faces.items():
        if len(fs) <= 1:
            # boundary/open edge (or degenerate mesh): keep
            edges.append((i, j))
            continue

        # Keep the edge if any adjacent triangle pair is not coplanar.
        # Use abs(dot) since winding may differ.
        n0 = normals[fs[0]]
        keep = False
        for fj in fs[1:]:
            n1 = normals[fj]
            if n0.length < 1e-12 or n1.length < 1e-12:
                keep = True
                break
            if abs(n0.dot(n1)) < float(coplanar_dot):
                keep = True
                break

        if keep:
            edges.append((i, j))

    return sorted(edges)

def create_mesh_object(name: str, mesh: bpy.types.Mesh, collection: bpy.types.Collection) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def build_solid_mesh(name: str, verts: List[Vector], faces: List[Tuple[int, ...]]) -> bpy.types.Mesh:
    pv = [(v.x, v.y, v.z) for v in verts]
    m = bpy.data.meshes.new(name)
    m.from_pydata(pv, [], faces)
    m.update()
    for p in m.polygons:
        p.use_smooth = False
    return m

def build_face_plate_mesh(name: str, verts: List[Vector], faces: List[Tuple[int, ...]], thickness: float) -> bpy.types.Mesh:
    """Build face plates as closed prisms (no Solidify modifier).

    We build *one* plate per polygon face (tri/quads/pentagons...), duplicating vertices per face.
    This avoids interior seams that appear when triangulated faces are solidified separately.
    The thickness is centered around the original face plane (+/- thickness/2).
    """
    t = float(thickness)
    pv: List[Tuple[float, float, float]] = []
    pf: List[Tuple[int, ...]] = []

    if t <= 0.0:
        # Fallback: single-surface polygons
        for face in faces:
            if len(face) < 3:
                continue
            base = len(pv)
            for idx in face:
                v = verts[idx]
                pv.append((v.x, v.y, v.z))
            pf.append(tuple(range(base, base + len(face))))
    else:
        half = t * 0.5
        for face in faces:
            if len(face) < 3:
                continue

            face_idx = list(face)
            vcoords = [verts[i] for i in face_idx]
            ctr = Vector((0.0, 0.0, 0.0))
            for v in vcoords:
                ctr += v
            ctr /= float(len(vcoords))

            n = (vcoords[1] - vcoords[0]).cross(vcoords[2] - vcoords[0])
            if n.length < 1e-9:
                continue
            n.normalize()

            # Ensure outward normal for convex solids centered at origin
            if n.dot(ctr) < 0.0:
                face_idx.reverse()
                vcoords = [verts[i] for i in face_idx]
                n = -n

            top_start = len(pv)
            for v in vcoords:
                vt = v + n * half
                pv.append((vt.x, vt.y, vt.z))

            bot_start = len(pv)
            for v in vcoords:
                vb = v - n * half
                pv.append((vb.x, vb.y, vb.z))

            k = len(vcoords)
            # top face (outward)
            pf.append(tuple(range(top_start, top_start + k)))
            # bottom face (outward from the plate bottom)
            pf.append(tuple(range(bot_start + k - 1, bot_start - 1, -1)))

            # side walls
            for i in range(k):
                i2 = (i + 1) % k
                pf.append((top_start + i, top_start + i2, bot_start + i2, bot_start + i))

    m = bpy.data.meshes.new(name)
    m.from_pydata(pv, [], pf)
    m.update()
    for p in m.polygons:
        p.use_smooth = False
    return m

def apply_transform_to_root(root: bpy.types.Object, transform_cfg: Dict[str, Any]):
    loc = transform_cfg.get("location", [0.0, 0.0, 0.0])
    rot = transform_cfg.get("rotation_deg", transform_cfg.get("rotation_euler_deg", [0.0, 0.0, 0.0]))
    sca = transform_cfg.get("scale", [1.0, 1.0, 1.0])

    root.location = (float(loc[0]), float(loc[1]), float(loc[2]))
    root.rotation_euler = (rad(rot[0]), rad(rot[1]), rad(rot[2]))
    root.scale = (float(sca[0]), float(sca[1]), float(sca[2]))


def build_boundary_object(spec: Dict[str, Any], parent_collection: bpy.types.Collection, global_scale: float = 1.0) -> BoundaryInfo:
    name = str(spec.get("name", "boundary"))
    coll = ensure_collection(name, parent_collection)

    root = create_empty(name, coll)

    shape_cfg = spec.get("shape", {}) if isinstance(spec.get("shape", {}), dict) else {}
    radius = float(spec.get("radius", 1.0)) * float(global_scale)

    verts, faces = make_shape_topology(shape_cfg, radius)

    # --- solid mesh (hidden, for BVH + face centers)
    solid_mesh = build_solid_mesh(f"{name}_SolidMesh", verts, faces)
    solid_obj = create_mesh_object(f"{name}_Solid", solid_mesh, coll)
    solid_obj.hide_render = True
    solid_obj.hide_viewport = True
    parent_keep_world(solid_obj, root)

    # --- materials
    edges_cfg = spec.get("edges", {}) if isinstance(spec.get("edges", {}), dict) else {}
    vertices_cfg = spec.get("vertices", spec.get("verticies", {}))
    vertices_cfg = vertices_cfg if isinstance(vertices_cfg, dict) else {}
    faces_cfg = spec.get("faces", {}) if isinstance(spec.get("faces", {}), dict) else {}
    detail_cfg = spec.get("detail", spec.get("details", {}))
    detail_cfg = detail_cfg if isinstance(detail_cfg, dict) else {}

    coplanar_dot = float(detail_cfg.get("edge_coplanar_dot", 0.999999))

    edge_radius = float(edges_cfg.get("radius", 0.05)) * float(global_scale)
    edge_color = parse_color_rgb(edges_cfg.get("color"), default=(1.0, 1.0, 1.0))
    edge_alpha = clamp01(edges_cfg.get("alpha", 1.0))

    vert_radius = float(vertices_cfg.get("radius", 0.08)) * float(global_scale)
    vert_color = parse_color_rgb(vertices_cfg.get("color"), default=(1.0, 0.2, 0.2))
    vert_alpha = clamp01(vertices_cfg.get("alpha", 1.0))

    face_thickness = float(faces_cfg.get("thickness", 0.03)) * float(global_scale)
    face_color = parse_color_rgb(faces_cfg.get("color"), default=(0.2, 0.6, 1.0))
    face_alpha = clamp01(faces_cfg.get("alpha", 0.12))

    edge_sides = int(detail_cfg.get("edge_cylinder_sides", 24))
    sphere_segs = int(detail_cfg.get("vertex_sphere_segments", 32))
    sphere_rings = int(detail_cfg.get("vertex_sphere_rings", 16))

    mat_edges = make_transparent_material(f"{name}_Mat_Edges", edge_color, edge_alpha, roughness=0.25, emission_strength=0.0)
    mat_verts = make_transparent_material(f"{name}_Mat_Vertices", vert_color, vert_alpha, roughness=0.20, emission_strength=0.0)
    mat_faces = make_transparent_material(f"{name}_Mat_Faces", face_color, face_alpha, roughness=0.45, emission_strength=0.0)

    # --- edges
    cyl_mesh = unit_cylinder_mesh(edge_sides, cap_ends=True)
    z_axis = Vector((0.0, 0.0, 1.0))

    for i, j in boundary_edges_from_faces(faces):
        v1, v2 = verts[i], verts[j]
        d = v2 - v1
        L = d.length
        if L < 1e-9:
            continue
        mid = (v1 + v2) * 0.5
        dir_n = d.normalized()

        obj = create_mesh_object(f"{name}_Edge_{i:04d}_{j:04d}", cyl_mesh, coll)
        obj.location = (mid.x, mid.y, mid.z)
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = z_axis.rotation_difference(dir_n)
        obj.scale = (edge_radius, edge_radius, L / 2.0)
        assign_material(obj, mat_edges)
        parent_keep_world(obj, root)

    # --- vertices
    sph_mesh = unit_uv_sphere_mesh(sphere_segs, sphere_rings)
    for idx, v in enumerate(verts):
        obj = create_mesh_object(f"{name}_Vertex_{idx:04d}", sph_mesh, coll)
        obj.location = (v.x, v.y, v.z)
        obj.scale = (vert_radius, vert_radius, vert_radius)
        assign_material(obj, mat_verts)
        parent_keep_world(obj, root)

    # --- face plates
    if face_alpha > 0.0 and face_thickness > 0.0:
        plates_mesh = build_face_plate_mesh(f"{name}_FacePlatesMesh", verts, faces, face_thickness)
        plates_obj = create_mesh_object(f"{name}_FacePlates", plates_mesh, coll)
        assign_material(plates_obj, mat_faces)
        parent_keep_world(plates_obj, root)

    # transform
    transform_cfg = spec.get("transform", {}) if isinstance(spec.get("transform", {}), dict) else {}
    apply_transform_to_root(root, transform_cfg)

    return BoundaryInfo(name=name, collection=coll, root=root, solid=solid_obj, radius=radius, vertex_radius=vert_radius)


# ----------------------------
# Camera / light / render
# ----------------------------

def look_at(obj: bpy.types.Object, target: Sequence[float]):
    """Aim an object so its local -Z axis points at target (camera-style look-at)."""
    t = Vector((float(target[0]), float(target[1]), float(target[2])))
    d = t - obj.location
    if d.length < 1e-9:
        return
    q = d.to_track_quat("-Z", "Y")
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = q


def camera_billboard_basis(cam_obj: bpy.types.Object) -> Matrix:
    """
    Returns a 3x3 rotation matrix whose axes match camera axes, with Z pointing toward camera.
    Local axes:
      X = camera right
      Y = camera up
      Z = toward camera (opposite camera forward)
    """
    R = cam_obj.matrix_world.to_3x3()
    right = R @ Vector((1.0, 0.0, 0.0))
    up = R @ Vector((0.0, 1.0, 0.0))
    forward = R @ Vector((0.0, 0.0, -1.0))
    normal = (-forward).normalized()
    return Matrix((right, up, normal)).transposed()



def create_camera_from_manifest(cfg: Dict[str, Any], parent_collection: bpy.types.Collection, boundary_for_auto: Optional[BoundaryInfo]) -> bpy.types.Object:
    """Create a camera from manifest.

    Supported modes:
      - mode: "EXPLICIT" -> use location + rotation (quaternion or euler) if provided; no look-at override.
      - otherwise -> use legacy LOOK_AT behavior (explicit location allowed; orientation is set by look_at()).

    Rotation fields (optional):
      - rotation_quat: [w, x, y, z]
      - rotation_euler_deg: [x_deg, y_deg, z_deg]
      - rotation_euler: [x_rad, y_rad, z_rad]
    """
    cam_cfg = cfg if isinstance(cfg, dict) else {}
    lens = float(cam_cfg.get("lens_mm", 50.0))
    dist = float(cam_cfg.get("distance", 5.0))

    target_cfg = cam_cfg.get("target", "AUTO")
    target = None
    if isinstance(target_cfg, (list, tuple)) and len(target_cfg) >= 3:
        target = [float(target_cfg[0]), float(target_cfg[1]), float(target_cfg[2])]
    elif isinstance(target_cfg, str) and target_cfg.strip().upper() == "AUTO":
        target = None
    else:
        target = [0.0, 0.0, 0.0]

    mode = str(cam_cfg.get("mode", cam_cfg.get("camera_mode", "LOOK_AT"))).upper()

    loc = cam_cfg.get("location", None)
    rot_quat = cam_cfg.get("rotation_quat", cam_cfg.get("rotation_quaternion", None))
    rot_euler_deg = cam_cfg.get("rotation_euler_deg", cam_cfg.get("rotation_deg", None))
    rot_euler_rad = cam_cfg.get("rotation_euler", None)

    have_explicit_loc = isinstance(loc, (list, tuple)) and len(loc) >= 3
    have_quat = isinstance(rot_quat, (list, tuple)) and len(rot_quat) >= 4
    have_euler_deg = isinstance(rot_euler_deg, (list, tuple)) and len(rot_euler_deg) >= 3
    have_euler_rad = isinstance(rot_euler_rad, (list, tuple)) and len(rot_euler_rad) >= 3

    explicit_rot = have_quat or have_euler_deg or have_euler_rad
    explicit_mode = (mode == "EXPLICIT") or explicit_rot

    cam_data = bpy.data.cameras.new("Camera")
    cam_obj = bpy.data.objects.new("Camera", cam_data)
    parent_collection.objects.link(cam_obj)
    cam_data.lens = lens

    cam_type = str(cam_cfg.get("type", cam_cfg.get("projection", "PERSP"))).upper()
    if cam_type in {"PERSP", "ORTHO"}:
        cam_data.type = cam_type
    if getattr(cam_data, "type", "PERSP") == "ORTHO":
        cam_data.ortho_scale = float(cam_cfg.get("ortho_scale", cam_cfg.get("scale", 6.0)))

    # Location
    if have_explicit_loc:
        cam_obj.location = (float(loc[0]), float(loc[1]), float(loc[2]))
    else:
        # Auto location: choose a direction that avoids aligning with face/edge/vertex axes.
        if boundary_for_auto is not None:
            solid = boundary_for_auto.solid
            mesh = solid.data
            mw = solid.matrix_world
            center_w = mw.translation

            axes: List[Vector] = []
            for v in mesh.vertices:
                d = (mw @ v.co) - center_w
                if d.length > 1e-9:
                    axes.append(d.normalized())
            for poly in mesh.polygons:
                d = (mw @ poly.center) - center_w
                if d.length > 1e-9:
                    axes.append(d.normalized())
            for e in mesh.edges:
                v0 = mw @ mesh.vertices[e.vertices[0]].co
                v1 = mw @ mesh.vertices[e.vertices[1]].co
                d = ((v0 + v1) * 0.5) - center_w
                if d.length > 1e-9:
                    axes.append(d.normalized())

            best_dir = Vector((0.37, -0.81, 0.45)).normalized()
            best_score = -1e9

            rng = random.Random(int(cfg.get("seed", 1337)))
            candidates: List[Vector] = [
                Vector((0.37, -0.81, 0.45)).normalized(),
                Vector((-0.52, -0.73, 0.44)).normalized(),
                Vector((0.61, -0.55, 0.57)).normalized(),
            ]
            for _ in range(60):
                z = rng.uniform(-0.7, 0.9)
                t = rng.uniform(0.0, 2.0 * math.pi)
                r = math.sqrt(max(0.0, 1.0 - z * z))
                candidates.append(Vector((r * math.cos(t), r * math.sin(t), z)).normalized())

            for d in candidates:
                pref = 0.15 * (-d.y) + 0.10 * (d.z)
                min_ang = 1e9
                for a in axes:
                    c = abs(d.dot(a))
                    c = max(-1.0, min(1.0, c))
                    ang = math.acos(c)
                    if ang < min_ang:
                        min_ang = ang
                score = min_ang + pref
                if score > best_score:
                    best_score = score
                    best_dir = d

            cam_obj.location = (center_w.x + best_dir.x * dist, center_w.y + best_dir.y * dist, center_w.z + best_dir.z * dist)
            target = [center_w.x, center_w.y, center_w.z]
        else:
            cam_obj.location = (0.0, -dist, dist * 0.4)

    # Rotation
    if explicit_mode and explicit_rot:
        if have_quat:
            w, x, y, z = float(rot_quat[0]), float(rot_quat[1]), float(rot_quat[2]), float(rot_quat[3])
            cam_obj.rotation_mode = "QUATERNION"
            cam_obj.rotation_quaternion = (w, x, y, z)
        elif have_euler_deg:
            cam_obj.rotation_mode = "XYZ"
            cam_obj.rotation_euler = (rad(rot_euler_deg[0]), rad(rot_euler_deg[1]), rad(rot_euler_deg[2]))
        elif have_euler_rad:
            cam_obj.rotation_mode = "XYZ"
            cam_obj.rotation_euler = (float(rot_euler_rad[0]), float(rot_euler_rad[1]), float(rot_euler_rad[2]))
    else:
        # Legacy behavior: compute target and look-at
        if target is None:
            if boundary_for_auto is not None:
                c = boundary_for_auto.root.matrix_world.translation
                target = [c.x, c.y, c.z]
            else:
                target = [0.0, 0.0, 0.0]
        look_at(cam_obj, target)

    return cam_obj



def create_light_from_manifest(cfg: Dict[str, Any], parent_collection: bpy.types.Collection) -> bpy.types.Object:
    lcfg = cfg if isinstance(cfg, dict) else {}
    lt = str(lcfg.get("type", "SUN")).upper()
    if lt not in {"SUN", "POINT", "SPOT", "AREA"}:
        lt = "SUN"

    energy = float(lcfg.get("energy", 3.0))
    loc = lcfg.get("location", [4.0, -4.0, 6.0])

    light_data = bpy.data.lights.new("KeyLight", type=lt)
    light_obj = bpy.data.objects.new("KeyLight", light_data)
    parent_collection.objects.link(light_obj)

    light_obj.location = (float(loc[0]), float(loc[1]), float(loc[2]))
    light_data.energy = energy
    look_at(light_obj, [0.0, 0.0, 0.0])
    return light_obj


def disable_cycles_denoise(scene: bpy.types.Scene):
    # disable any per-view-layer denoise flags (prevents OIDN error in builds without OIDN)
    for vl in scene.view_layers:
        if hasattr(vl, "cycles") and hasattr(vl.cycles, "use_denoising"):
            vl.cycles.use_denoising = False


def apply_render_settings(cfg: Dict[str, Any], project_root: str):
    scn, _ = scene_and_root_collection()
    rcfg = cfg.get("render", {}) if isinstance(cfg.get("render", {}), dict) else {}

    engine = str(rcfg.get("engine", "CYCLES"))
    scn.render.engine = engine

    scn.render.resolution_x = int(rcfg.get("resolution_x", 1024))
    scn.render.resolution_y = int(rcfg.get("resolution_y", 1024))
    scn.render.resolution_percentage = int(rcfg.get("resolution_percentage", 100))

    file_format = str(rcfg.get("file_format", "PNG"))
    scn.render.image_settings.file_format = file_format
    if file_format.upper() == "PNG":
        scn.render.image_settings.color_mode = "RGBA"

    scn.render.film_transparent = bool(rcfg.get("transparent", False))

    raw_path = str(rcfg.get("filepath", "output/render.png"))
    abs_path = os.path.abspath(os.path.join(project_root, raw_path))
    base, _ext = os.path.splitext(abs_path)
    out_dir = os.path.dirname(base)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    scn.render.filepath = base
    scn.render.use_file_extension = True

    if engine.upper() == "CYCLES" and hasattr(scn, "cycles"):
        scn.cycles.samples = int(rcfg.get("samples", 128))

        cycles_cfg = rcfg.get("cycles", {}) if isinstance(rcfg.get("cycles", {}), dict) else {}
        if "adaptive_sampling" in cycles_cfg:
            scn.cycles.use_adaptive_sampling = bool(cycles_cfg.get("adaptive_sampling"))
        if "adaptive_threshold" in cycles_cfg:
            scn.cycles.adaptive_threshold = float(cycles_cfg.get("adaptive_threshold"))
        if "clamp_indirect" in cycles_cfg:
            scn.cycles.sample_clamp_indirect = float(cycles_cfg.get("clamp_indirect"))
        if "max_bounces" in cycles_cfg:
            scn.cycles.max_bounces = int(cycles_cfg.get("max_bounces"))

        # Force denoise off (avoids OIDN error on Guix Blender builds without it)
        disable_cycles_denoise(scn)


# ----------------------------
# Label placement helpers (based on the uploaded strategy doc)
# ----------------------------

def ndc_and_in_frame(scene: bpy.types.Scene, cam_obj: bpy.types.Object, world_pt: Vector) -> Tuple[Vector, bool]:
    ndc = world_to_camera_view(scene, cam_obj, world_pt)
    in_frame = (0.0 <= ndc.x <= 1.0 and 0.0 <= ndc.y <= 1.0 and ndc.z >= 0.0)
    return ndc, in_frame


def ndc_to_px(scene: bpy.types.Scene, ndc: Vector) -> Tuple[Vector, float, float]:
    r = scene.render
    W = r.resolution_x * (r.resolution_percentage / 100.0)
    H = r.resolution_y * (r.resolution_percentage / 100.0)
    return Vector((ndc.x * W, ndc.y * H)), W, H


def build_solid_bvh(solid_obj: bpy.types.Object) -> BVHTree:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return BVHTree.FromObject(solid_obj, depsgraph, epsilon=1e-6)


def visible_on_solid_from_camera(
    scene: bpy.types.Scene,
    cam_obj: bpy.types.Object,
    solid_obj: bpy.types.Object,
    solid_bvh: BVHTree,
    world_pt: Vector,
    eps: float = 1e-3,
) -> bool:
    cam_origin_w = cam_obj.matrix_world.translation
    vec = world_pt - cam_origin_w
    dist_w = vec.length
    if dist_w < 1e-9:
        return False

    mw = solid_obj.matrix_world
    inv = mw.inverted()

    origin_o = inv @ cam_origin_w
    target_o = inv @ world_pt

    dir_o = target_o - origin_o
    dist_o = dir_o.length
    if dist_o < 1e-9:
        return False
    dir_o.normalize()

    hit_o, _normal_o, _face_i, _hit_dist = solid_bvh.ray_cast(origin_o, dir_o, dist_o)
    if hit_o is None:
        return False

    hit_w = mw @ hit_o
    return (hit_w - world_pt).length <= eps


def projected_bbox_px(scene: bpy.types.Scene, cam_obj: bpy.types.Object, points_w: List[Vector]) -> Tuple[float, float, float, float]:
    pxs: List[Vector] = []
    for p in points_w:
        ndc = world_to_camera_view(scene, cam_obj, p)
        if ndc.z < 0.0:
            continue
        px, _, _ = ndc_to_px(scene, ndc)
        pxs.append(px)

    if not pxs:
        return (0.0, 0.0, 0.0, 0.0)

    minx = min(p.x for p in pxs)
    maxx = max(p.x for p in pxs)
    miny = min(p.y for p in pxs)
    maxy = max(p.y for p in pxs)
    return (minx, maxx, miny, maxy)


def outside_distance_to_bbox_px(p: Vector, bbox: Tuple[float, float, float, float]) -> float:
    minx, maxx, miny, maxy = bbox
    dx = 0.0
    if p.x < minx:
        dx = minx - p.x
    elif p.x > maxx:
        dx = p.x - maxx

    dy = 0.0
    if p.y < miny:
        dy = miny - p.y
    elif p.y > maxy:
        dy = p.y - maxy

    if dx == 0.0 and dy == 0.0:
        din = min(p.x - minx, maxx - p.x, p.y - miny, maxy - p.y)
        return -float(din)

    return math.sqrt(dx * dx + dy * dy)


@dataclass
class LabelPlacement:
    face_index: int
    base_w: Vector
    dir_w: Vector
    length: float
    tip_w: Vector


@dataclass
class PortPlacement:
    vertex_index: int
    base_w: Vector
    dir_w: Vector
    length: float
    tip_w: Vector


def choose_vertex_and_length_for_port(
    scene: bpy.types.Scene,
    cam_obj: bpy.types.Object,
    boundary: BoundaryInfo,
    port_spec: Dict[str, Any],
    used_vertices: Optional[set[int]] = None,
) -> PortPlacement:
    """Pick a vertex (and a suitable length) for a vertex-attached port.

    - If attach.index is provided (>=0), that vertex is used.
    - If attach.index is None or <0, a vertex is auto-selected.
    - When auto-selecting, auto_placement.unique_vertices (default True) avoids reusing
      vertices already present in used_vertices (but will fall back to used vertices if needed).

    This mirrors choose_face_and_length_for_label(), but uses boundary vertices as attach sites.
    """

    def _norm_index(v: Any) -> Optional[int]:
        if v is None:
            return None
        try:
            iv = int(v)
        except Exception:
            return None
        return iv if iv >= 0 else None

    port_name = str(port_spec.get("name", "port"))

    solid_obj = boundary.solid
    mesh = solid_obj.data
    mw = solid_obj.matrix_world
    center_w = mw.translation

    attach = port_spec.get("attach", {}) if isinstance(port_spec.get("attach", {}), dict) else {}
    forced_idx = _norm_index(attach.get("index", None))
    forced_type = attach.get("site_type", "VERTEX")
    if forced_type is None:
        forced_type = "VERTEX"
    forced_type = str(forced_type).upper()

    # If a forced index is out-of-range (e.g. boundary topology changed), fall back to AUTO.
    if forced_idx is not None:
        if forced_idx < 0 or forced_idx >= len(mesh.vertices):
            print(f'[port] "{port_name}": attach.index={forced_idx} is out of range for boundary "{boundary.name}" (verts={len(mesh.vertices)}); using AUTO.')
            forced_idx = None

    cyl_cfg = port_spec.get("cylinder", {}) if isinstance(port_spec.get("cylinder", {}), dict) else {}
    cyl_radius = float(cyl_cfg.get("radius", 0.03))

    base_offset = cyl_cfg.get("base_offset", "AUTO")
    if base_offset == "AUTO":
        # Start just outside the visible vertex sphere, plus a small margin.
        base_offset = max(float(boundary.vertex_radius) * 1.05, cyl_radius * 1.05)
    base_offset = float(base_offset)

    length_cfg = cyl_cfg.get("length", "AUTO")
    L_min = float(cyl_cfg.get("length_min", 0.6))
    L_max = float(cyl_cfg.get("length_max", 2.8))
    if L_max < L_min:
        L_max = L_min

    ap = port_spec.get("auto_placement", {}) if isinstance(port_spec.get("auto_placement", {}), dict) else {}
    require_visible_base = bool(ap.get("require_visible_base", True))
    require_tip_in_frame = bool(ap.get("require_tip_in_frame", True))
    bbox_margin_px = float(ap.get("bbox_margin_px", 40.0))
    tip_margin_px = float(ap.get("tip_margin_px", 60.0))
    silhouette_bias = float(ap.get("silhouette_bias", 0.25))
    seg_bias = float(ap.get("segment_len_bias", 0.10))
    length_samples = int(ap.get("length_samples", 24))

    unique_vertices = bool(ap.get("unique_vertices", ap.get("unique_vertex", True)))
    used_set = used_vertices if (unique_vertices and used_vertices is not None and forced_idx is None) else None

    solid_bvh = build_solid_bvh(solid_obj)

    center_ndc, _ = ndc_and_in_frame(scene, cam_obj, center_w)
    center_px, W, H = ndc_to_px(scene, center_ndc)

    v_world = [mw @ v.co for v in mesh.vertices]
    bbox = projected_bbox_px(scene, cam_obj, v_world)
    bbox_expanded = (
        bbox[0] - bbox_margin_px,
        bbox[1] + bbox_margin_px,
        bbox[2] - bbox_margin_px,
        bbox[3] + bbox_margin_px,
    )

    mx = tip_margin_px / max(1.0, W)
    my = tip_margin_px / max(1.0, H)

    def _search(require_visible_base_local: bool):
        best_any: Optional[PortPlacement] = None
        best_any_score = -1e18
        best_unused: Optional[PortPlacement] = None
        best_unused_score = -1e18

        for v in mesh.vertices:
            vi = int(v.index)

            # Respect explicit selection when provided.
            if forced_type == "VERTEX" and forced_idx is not None and vi != int(forced_idx):
                continue

            base_w = mw @ v.co
            base_ndc, base_in = ndc_and_in_frame(scene, cam_obj, base_w)
            if not base_in:
                continue

            if require_visible_base_local:
                # Vertex hits are numerically sensitive; use a slightly larger epsilon.
                if not visible_on_solid_from_camera(scene, cam_obj, solid_obj, solid_bvh, base_w, eps=2e-2):
                    continue

            base_px, _, _ = ndc_to_px(scene, base_ndc)
            silhouette = (base_px - center_px).length

            dir_w = (base_w - center_w)
            if dir_w.length < 1e-9:
                continue
            dir_w.normalize()

            # Evaluate length either fixed or sampled, but keep the best score for this vertex.
            local_best: Optional[PortPlacement] = None
            local_best_score = -1e18

            if isinstance(length_cfg, (int, float)):
                L = float(length_cfg)
                tip_w = base_w + dir_w * (base_offset + L)
                tip_ndc, _tip_in = ndc_and_in_frame(scene, cam_obj, tip_w)
                if require_tip_in_frame:
                    if not (mx <= tip_ndc.x <= 1.0 - mx and my <= tip_ndc.y <= 1.0 - my and tip_ndc.z >= 0.0):
                        local_best = None
                    else:
                        tip_px, _, _ = ndc_to_px(scene, tip_ndc)
                        outd = outside_distance_to_bbox_px(tip_px, bbox_expanded)
                        seglen = (tip_px - base_px).length
                        out_term = outd if outd >= 0.0 else outd * 1.5
                        score = out_term + silhouette_bias * silhouette + seg_bias * seglen
                        local_best_score = score
                        local_best = PortPlacement(vertex_index=vi, base_w=base_w, dir_w=dir_w, length=L, tip_w=tip_w)
                else:
                    tip_px, _, _ = ndc_to_px(scene, tip_ndc)
                    outd = outside_distance_to_bbox_px(tip_px, bbox_expanded)
                    seglen = (tip_px - base_px).length
                    out_term = outd if outd >= 0.0 else outd * 1.5
                    score = out_term + silhouette_bias * silhouette + seg_bias * seglen
                    local_best_score = score
                    local_best = PortPlacement(vertex_index=vi, base_w=base_w, dir_w=dir_w, length=L, tip_w=tip_w)
            else:
                for s in range(max(1, length_samples)):
                    t = 0.0 if length_samples <= 1 else s / (length_samples - 1)
                    L = L_min + t * (L_max - L_min)

                    tip_w = base_w + dir_w * (base_offset + L)
                    tip_ndc, _tip_in = ndc_and_in_frame(scene, cam_obj, tip_w)

                    if require_tip_in_frame:
                        if not (mx <= tip_ndc.x <= 1.0 - mx and my <= tip_ndc.y <= 1.0 - my and tip_ndc.z >= 0.0):
                            continue

                    tip_px, _, _ = ndc_to_px(scene, tip_ndc)
                    outd = outside_distance_to_bbox_px(tip_px, bbox_expanded)
                    seglen = (tip_px - base_px).length

                    out_term = outd if outd >= 0.0 else outd * 1.5
                    score = out_term + silhouette_bias * silhouette + seg_bias * seglen

                    if score > local_best_score:
                        local_best_score = score
                        local_best = PortPlacement(vertex_index=vi, base_w=base_w, dir_w=dir_w, length=L, tip_w=tip_w)

            if local_best is None:
                continue

            # Track best overall (used for fallback if all vertices are "used")
            if local_best_score > best_any_score:
                best_any_score = local_best_score
                best_any = local_best

            # Track best among unused vertices if requested
            if used_set is None or vi not in used_set:
                if local_best_score > best_unused_score:
                    best_unused_score = local_best_score
                    best_unused = local_best
        return best_any, best_any_score, best_unused, best_unused_score

    best_any, best_any_score, best_unused, best_unused_score = _search(require_visible_base)

    # If we ran out of unused candidate vertices (causing overlaps), try a relaxed pass
    # that skips the strict ray-test for base visibility. This keeps AUTO placement usable
    # when the visibility test is overly strict for your current camera framing.
    if best_unused is None and used_set is not None and forced_idx is None and require_visible_base:
        _best_any2, _best_any_score2, best_unused2, _best_unused_score2 = _search(False)
        if best_unused2 is not None:
            best = best_unused2
        else:
            best = best_any
    else:
        best = best_unused if best_unused is not None else best_any

    if best is None:
        if not mesh.vertices:
            raise RuntimeError("Boundary has no vertices to attach port to.")
        v0 = mesh.vertices[0]
        base_w = mw @ v0.co
        dir_w = (base_w - center_w)
        if dir_w.length < 1e-9:
            dir_w = Vector((0.0, 0.0, 1.0))
        else:
            dir_w.normalize()
        L = float(L_min)
        tip_w = base_w + dir_w * (base_offset + L)
        best = PortPlacement(vertex_index=int(v0.index), base_w=base_w, dir_w=dir_w, length=L, tip_w=tip_w)

    return best



def choose_face_and_length_for_label(
    scene: bpy.types.Scene,
    cam_obj: bpy.types.Object,
    boundary: BoundaryInfo,
    label_spec: Dict[str, Any],
) -> LabelPlacement:
    solid_obj = boundary.solid
    mesh = solid_obj.data
    mw = solid_obj.matrix_world
    center_w = mw.translation

    # Labels can point OUT (default) or IN (into the boundary).
    dir_mode = str(label_spec.get("direction", label_spec.get("side", "OUT")) or "OUT").upper()
    if dir_mode not in {"OUT", "IN"}:
        dir_mode = "OUT"
    want_in = (dir_mode == "IN")

    attach = label_spec.get("attach", {}) if isinstance(label_spec.get("attach", {}), dict) else {}
    forced_idx = attach.get("index", None)
    forced_type = attach.get("site_type", "FACE")
    if forced_type is None:
        forced_type = "FACE"
    forced_type = str(forced_type).upper()

    cyl_cfg = label_spec.get("cylinder", {}) if isinstance(label_spec.get("cylinder", {}), dict) else {}
    cyl_radius = float(cyl_cfg.get("radius", 0.03))
    base_offset = cyl_cfg.get("base_offset", "AUTO")
    if base_offset == "AUTO":
        base_offset = cyl_radius * 1.05
    base_offset = float(base_offset)

    length_cfg = cyl_cfg.get("length", "AUTO")
    L_min = float(cyl_cfg.get("length_min", 0.6))
    L_max = float(cyl_cfg.get("length_max", 2.8))
    if L_max < L_min:
        L_max = L_min

    ap = label_spec.get("auto_placement", {}) if isinstance(label_spec.get("auto_placement", {}), dict) else {}
    require_visible_base = bool(ap.get("require_visible_base", True))
    require_tip_in_frame = bool(ap.get("require_tip_in_frame", True))
    bbox_margin_px = float(ap.get("bbox_margin_px", 40.0))
    tip_margin_px = float(ap.get("tip_margin_px", 60.0))
    silhouette_bias = float(ap.get("silhouette_bias", 0.25))
    seg_bias = float(ap.get("segment_len_bias", 0.10))
    length_samples = int(ap.get("length_samples", 24))

    solid_bvh = build_solid_bvh(solid_obj)

    center_ndc, _ = ndc_and_in_frame(scene, cam_obj, center_w)
    center_px, W, H = ndc_to_px(scene, center_ndc)

    v_world = [mw @ v.co for v in mesh.vertices]
    bbox = projected_bbox_px(scene, cam_obj, v_world)
    bbox_expanded = (bbox[0] - bbox_margin_px, bbox[1] + bbox_margin_px, bbox[2] - bbox_margin_px, bbox[3] + bbox_margin_px)

    mx = tip_margin_px / max(1.0, W)
    my = tip_margin_px / max(1.0, H)

    best: Optional[LabelPlacement] = None
    best_score = -1e18

    for poly in mesh.polygons:
        if forced_type == "FACE" and forced_idx is not None and int(poly.index) != int(forced_idx):
            continue

        tri_center_w = mw @ poly.center

        # Use the face normal so labels are perpendicular to planar polygon faces
        # (cube squares, dodecahedron pentagons) even though the solid mesh is triangulated.
        # Transform normals with inverse-transpose to handle object scaling correctly.
        nmat = mw.to_3x3().inverted().transposed()
        outward_dir = (nmat @ poly.normal).normalized()
        # Ensure outward_dir points outward (away from the polyhedron center)
        if outward_dir.dot(tri_center_w - center_w) < 0.0:
            outward_dir = -outward_dir

        # Project the polyhedron center onto the face plane to get a stable face-center
        # point (works for regular solids; avoids triangle-centroid bias).
        dist = outward_dir.dot(tri_center_w - center_w)
        base_w = center_w + outward_dir * dist

        # Final direction for this label (OUT = outward, IN = inward)
        dir_w = -outward_dir if want_in else outward_dir


        base_ndc, base_in = ndc_and_in_frame(scene, cam_obj, base_w)
        if not base_in:
            continue

        if require_visible_base:
            if not visible_on_solid_from_camera(scene, cam_obj, solid_obj, solid_bvh, base_w):
                continue

        base_px, _, _ = ndc_to_px(scene, base_ndc)
        silhouette = (base_px - center_px).length

        if isinstance(length_cfg, (int, float)):
            L = float(length_cfg)
            tip_w = base_w + dir_w * (base_offset + L)
            tip_ndc, _tip_in = ndc_and_in_frame(scene, cam_obj, tip_w)
            if require_tip_in_frame:
                if not (mx <= tip_ndc.x <= 1.0 - mx and my <= tip_ndc.y <= 1.0 - my and tip_ndc.z >= 0.0):
                    continue
            tip_px, _, _ = ndc_to_px(scene, tip_ndc)
            outd = outside_distance_to_bbox_px(tip_px, bbox_expanded)
            seglen = (tip_px - base_px).length
            out_term = (-outd) if want_in else (outd if outd >= 0.0 else outd * 1.5)
            score = out_term + silhouette_bias * silhouette + seg_bias * seglen
            if score > best_score:
                best_score = score
                best = LabelPlacement(face_index=int(poly.index), base_w=base_w, dir_w=dir_w, length=L, tip_w=tip_w)
            continue

        local_best: Optional[LabelPlacement] = None
        local_best_score = -1e18

        for s in range(max(1, length_samples)):
            t = 0.0 if length_samples <= 1 else s / (length_samples - 1)
            L = L_min + t * (L_max - L_min)

            tip_w = base_w + dir_w * (base_offset + L)
            tip_ndc, _tip_in = ndc_and_in_frame(scene, cam_obj, tip_w)

            if require_tip_in_frame:
                if not (mx <= tip_ndc.x <= 1.0 - mx and my <= tip_ndc.y <= 1.0 - my and tip_ndc.z >= 0.0):
                    continue

            tip_px, _, _ = ndc_to_px(scene, tip_ndc)
            outd = outside_distance_to_bbox_px(tip_px, bbox_expanded)
            seglen = (tip_px - base_px).length

            out_term = (-outd) if want_in else (outd if outd >= 0.0 else outd * 1.5)
            score = out_term + silhouette_bias * silhouette + seg_bias * seglen

            if score > local_best_score:
                local_best_score = score
                local_best = LabelPlacement(face_index=int(poly.index), base_w=base_w, dir_w=dir_w, length=L, tip_w=tip_w)

        if local_best is not None and local_best_score > best_score:
            best_score = local_best_score
            best = local_best

    if best is None:
        best_poly = mesh.polygons[0] if mesh.polygons else None
        if best_poly is None:
            raise RuntimeError("Boundary has no faces to attach label to.")
        tri_center_w = mw @ best_poly.center
        nmat = mw.to_3x3().inverted().transposed()
        dir_w = (nmat @ best_poly.normal).normalized()
        if dir_w.dot(tri_center_w - center_w) < 0.0:
            dir_w = -dir_w
        dist = dir_w.dot(tri_center_w - center_w)
        base_w = center_w + dir_w * dist
        L = float(L_min)
        tip_w = base_w + dir_w * (base_offset + L)
        best = LabelPlacement(face_index=int(best_poly.index), base_w=base_w, dir_w=dir_w, length=L, tip_w=tip_w)

    return best


# ----------------------------
# Label build
# ----------------------------

def create_text_object(
    name: str,
    text_cfg: Dict[str, Any],
    collection: bpy.types.Collection,
    mat: bpy.types.Material,
) -> bpy.types.Object:
    """Create a Text object (FONT curve) for boards (labels/ports).

    Fixes:
      - Prevent the 'double drawn' look that can happen when front/back faces overlap on flat text.
      - Make text look 3D by default via auto-extrude + optional bevel.
    """
    curve = bpy.data.curves.new(name=f"{name}_Curve", type="FONT")

    # --- Text content ---
    value = text_cfg.get("value", "")
    curve.body = "" if value is None else str(value)

    # --- Size ---
    size = float(text_cfg.get("size", 0.3) or 0.3)
    curve.size = size

    # --- Extrude (3D thickness) ---
    # Back-compat + nicer default: treat missing/"AUTO"/0 as auto-extrude.
    extrude_raw = text_cfg.get("extrude", "AUTO")
    extrude_val: float
    if isinstance(extrude_raw, str) and extrude_raw.strip().upper() == "AUTO":
        extrude_val = max(0.001, size * 0.07)
    else:
        try:
            extrude_val = float(extrude_raw)
            if extrude_val <= 1e-6:
                extrude_val = max(0.001, size * 0.07)
        except Exception:
            extrude_val = max(0.001, size * 0.07)

    curve.extrude = float(extrude_val)

    # --- Bevel (round the edges a bit so letters catch light) ---
    bevel_depth_raw = text_cfg.get("bevel_depth", "AUTO")
    bevel_depth: float
    if isinstance(bevel_depth_raw, str) and bevel_depth_raw.strip().upper() == "AUTO":
        # Keep bevel subtle; clamp by both thickness and size.
        bevel_depth = min(extrude_val * 0.25, size * 0.01)
    else:
        try:
            bevel_depth = float(bevel_depth_raw)
        except Exception:
            bevel_depth = 0.0

    if hasattr(curve, "bevel_depth"):
        curve.bevel_depth = float(max(0.0, bevel_depth))

    bevel_res = int(text_cfg.get("bevel_resolution", text_cfg.get("bevel_res", 2)) or 2)
    bevel_res = max(0, min(10, bevel_res))
    if hasattr(curve, "bevel_resolution"):
        curve.bevel_resolution = bevel_res

    if hasattr(curve, "use_fill_caps"):
        curve.use_fill_caps = True

    # --- Alignment (center origin for easier layout) ---
    align_x = str(text_cfg.get("align_x", "CENTER")).upper()
    if hasattr(curve, "align_x"):
        try:
            curve.align_x = align_x
        except Exception:
            pass

    align_y = str(text_cfg.get("align_y", "CENTER")).upper()
    if hasattr(curve, "align_y"):
        try:
            curve.align_y = align_y
        except Exception:
            try:
                curve.align_y = "CENTER"
            except Exception:
                pass

    # --- Avoid z-fighting / 'double text' when flat ---
    if hasattr(curve, "fill_mode"):
        try:
            # FULL is fine when extruded; FRONT is safer if flat.
            curve.fill_mode = "FULL" if curve.extrude > 1e-6 else "FRONT"
        except Exception:
            pass

    # --- Optional custom font ---
    font_path = text_cfg.get("font", None)
    if isinstance(font_path, str) and font_path.strip():
        fp = font_path.strip()
        try:
            curve.font = bpy.data.fonts.load(fp)
        except Exception:
            pass

    curve.materials.clear()
    curve.materials.append(mat)

    obj = bpy.data.objects.new(name, curve)
    collection.objects.link(obj)
    return obj


def create_image_plane(
    name: str,
    image_cfg: Dict[str, Any],
    collection: bpy.types.Collection,
    project_root: str,
) -> Optional[Tuple[bpy.types.Object, float, float]]:
    path = image_cfg.get("filepath", None)
    if not isinstance(path, str) or not path.strip():
        return None

    abs_path = os.path.abspath(os.path.join(project_root, path))
    if not os.path.exists(abs_path):
        print(f"[label] image file not found: {abs_path} (skipping)")
        return None

    try:
        img = bpy.data.images.load(abs_path, check_existing=True)
    except Exception as e:
        print(f"[label] failed to load image {abs_path}: {e} (skipping)")
        return None

    alpha = float(image_cfg.get("alpha", 1.0))
    mat = make_image_material(f"{name}_Mat_Image", img, alpha=alpha)

    m = unit_plane_mesh()
    obj = create_mesh_object(name, m, collection)
    assign_material(obj, mat)

    desired_h = float(image_cfg.get("height", 0.55))
    img_scale = image_cfg.get("scale", 1.0)
    try:
        img_scale = float(img_scale)
    except Exception:
        img_scale = 1.0
    desired_h *= img_scale
    w_px, h_px = img.size[0], img.size[1]
    aspect = (w_px / h_px) if h_px else 1.0
    desired_w = desired_h * aspect
    obj.scale = (desired_w, desired_h, 1.0)
    return obj, desired_w, desired_h


def build_label_object(
    spec: Dict[str, Any],
    boundaries: Dict[str, BoundaryInfo],
    cam_obj: bpy.types.Object,
    scene: bpy.types.Scene,
    parent_collection: bpy.types.Collection,
    project_root: str,
    label_plane_mode: str = "CAMERA",
) -> None:
    name = str(spec.get("name", "label"))
    coll = ensure_collection(name, parent_collection)
    root = create_empty(name, coll)

    target = str(spec.get("target", "boundary"))
    if target not in boundaries:
        raise RuntimeError(f'Label "{name}" target boundary "{target}" not found.')

    boundary = boundaries[target]
    parent_keep_world(root, boundary.root)

    attach = spec.get("attach", {}) if isinstance(spec.get("attach", {}), dict) else {}
    ap = spec.get("auto_placement", {}) if isinstance(spec.get("auto_placement", {}), dict) else {}
    enabled = bool(ap.get("enabled", True))
    if not enabled and attach.get("index", None) is None:
        raise RuntimeError(f'Label "{name}": auto_placement disabled but no attach.index specified.')

    placement = choose_face_and_length_for_label(scene, cam_obj, boundary, spec)
    # Store the resolved face index for UI/debugging
    try:
        root["attach_index"] = int(placement.face_index)
    except Exception:
        pass

    cyl_cfg = spec.get("cylinder", {}) if isinstance(spec.get("cylinder", {}), dict) else {}
    cyl_radius = float(cyl_cfg.get("radius", 0.03))
    cyl_sides = int(cyl_cfg.get("sides", 24))
    cyl_color = parse_color_rgb(cyl_cfg.get("color"), default=(1.0, 1.0, 1.0))
    cyl_alpha = clamp01(cyl_cfg.get("alpha", 1.0))

    base_offset = cyl_cfg.get("base_offset", "AUTO")
    if base_offset == "AUTO":
        base_offset = cyl_radius * 1.05
    base_offset = float(base_offset)

    mat_cyl = make_transparent_material(f"{name}_Mat_Cylinder", cyl_color, cyl_alpha, roughness=0.25, emission_strength=0.0)
    cyl_mesh = unit_cylinder_mesh(cyl_sides, cap_ends=True)

    z_axis = Vector((0.0, 0.0, 1.0))
    dir_w = placement.dir_w.normalized()
    L = float(placement.length)

    cyl_center = placement.base_w + dir_w * base_offset + dir_w * (L * 0.5)

    cyl_obj = create_mesh_object(f"{name}_Cylinder", cyl_mesh, coll)
    cyl_obj.rotation_mode = "QUATERNION"
    cyl_obj.rotation_quaternion = z_axis.rotation_difference(dir_w)
    cyl_obj.location = (cyl_center.x, cyl_center.y, cyl_center.z)
    cyl_obj.scale = (cyl_radius, cyl_radius, L / 2.0)
    assign_material(cyl_obj, mat_cyl)
    parent_keep_world(cyl_obj, root)

    board_cfg = spec.get("board", {}) if isinstance(spec.get("board", {}), dict) else {}
    gap = board_cfg.get("gap", "AUTO")
    if gap == "AUTO":
        gap = max(0.02, cyl_radius * 2.5)
    gap = float(gap)

    tip_w = placement.base_w + dir_w * (base_offset + L)
    board_center = tip_w + dir_w * gap

    board_root = create_empty(f"{name}_Board", coll)

    pm = str(board_cfg.get("plane_mode", label_plane_mode or "CAMERA")).upper()
    if pm not in {"CAMERA", "AXIS"}:
        pm = "CAMERA"

    if pm == "AXIS":
        # Plane normal along the cylinder axis, but flip to face the camera if needed
        normal = dir_w.normalized()
        cam_to_board = cam_obj.matrix_world.translation - board_center
        if normal.dot(cam_to_board) < 0.0:
            normal = -normal

        R = cam_obj.matrix_world.to_3x3()
        cam_right = R @ Vector((1.0, 0.0, 0.0))
        cam_up = R @ Vector((0.0, 1.0, 0.0))

        right = cam_right - normal * cam_right.dot(normal)
        if right.length < 1e-9:
            right = cam_up - normal * cam_up.dot(normal)
        if right.length < 1e-9:
            tmp = Vector((1.0, 0.0, 0.0)) if abs(normal.x) < 0.9 else Vector((0.0, 1.0, 0.0))
            right = tmp - normal * tmp.dot(normal)

        right.normalize()
        up = normal.cross(right).normalized()
        basis = Matrix((right, up, normal)).transposed()
    else:
        basis = camera_billboard_basis(cam_obj)

    board_root.matrix_world = Matrix.Translation(board_center) @ basis.to_4x4()
    parent_keep_world(board_root, root)

    layout_cfg = spec.get("layout", {}) if isinstance(spec.get("layout", {}), dict) else {}
    spacing = float(layout_cfg.get("spacing", 0.05))
    padding = float(layout_cfg.get("padding", 0.04))
    image_above_text = bool(layout_cfg.get("image_above_text", True))

    text_cfg = spec.get("text", {}) if isinstance(spec.get("text", {}), dict) else {}
    text_value = str(text_cfg.get("value", "") or "")
    want_text = bool(text_value.strip())

    image_cfg = spec.get("image", {}) if isinstance(spec.get("image", {}), dict) else {}
    want_image = isinstance(image_cfg.get("filepath", None), str) and bool(image_cfg.get("filepath", "").strip())

    text_color = parse_color_rgb(text_cfg.get("color"), default=(1.0, 1.0, 1.0))
    text_alpha = clamp01(text_cfg.get("alpha", 1.0))
    mat_text = make_transparent_material(f"{name}_Mat_Text", text_color, text_alpha, roughness=0.4, emission_strength=0.0)

    text_obj = None
    text_w = text_h = 0.0
    if want_text:
        text_obj = create_text_object(f"{name}_Text", text_cfg, coll, mat_text)
        parent_inherit(text_obj, board_root)
        text_obj.location = (0.0, 0.0, 0.0)
        text_obj.rotation_euler = (0.0, 0.0, 0.0)
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        text_w = float(text_obj.dimensions.x)
        text_h = float(text_obj.dimensions.y)

    img_obj = None
    img_w = img_h = 0.0
    if want_image:
        out = create_image_plane(f"{name}_Image", image_cfg, coll, project_root=project_root)
        if out is not None:
            img_obj, img_w, img_h = out
            parent_inherit(img_obj, board_root)
            img_obj.location = (0.0, 0.0, 0.0)
            img_obj.rotation_euler = (0.0, 0.0, 0.0)

    elements = []
    if img_obj is not None:
        elements.append(("image", img_obj, img_w, img_h))
    if text_obj is not None:
        elements.append(("text", text_obj, text_w, text_h))

    if not elements:
        # No text/image content requested/available: do not create fallback text.
        return

    if len(elements) == 1:
        _, obj, _, _ = elements[0]
        obj.location = (0.0, 0.0, 0.0)
    else:
        if image_above_text:
            top = next(e for e in elements if e[0] == "image")
            bottom = next(e for e in elements if e[0] == "text")
        else:
            top = next(e for e in elements if e[0] == "text")
            bottom = next(e for e in elements if e[0] == "image")

        _, top_obj, _, top_h = top
        _, bot_obj, _, bot_h = bottom

        total_h = top_h + bot_h + spacing + 2.0 * padding
        y_top = (total_h / 2.0) - padding - (top_h / 2.0)
        y_bot = y_top - (top_h / 2.0) - spacing - (bot_h / 2.0)

        top_obj.location = (0.0, y_top, 0.0)
        bot_obj.location = (0.0, y_bot, 0.0)


    # Apply per-text offset within the board plane (helps move text away from cylinders)
    if text_obj is not None:
        off_y = text_cfg.get("offset_y", 0.0)
        try:
            off_y = float(off_y)
        except Exception:
            off_y = 0.0
        if abs(off_y) > 1.0e-9:
            text_obj.location.y += off_y


    root["attach_site_type"] = "FACE"
    root["attach_index"] = int(placement.face_index)
    root["cylinder_length"] = float(L)



# ----------------------------
# Port build (vertex-attached power/info callouts)
# ----------------------------

def build_port_object(
    spec: Dict[str, Any],
    boundaries: Dict[str, BoundaryInfo],
    cam_obj: bpy.types.Object,
    scene: bpy.types.Scene,
    parent_collection: bpy.types.Collection,
    project_root: str,
    board_plane_mode: str = "CAMERA",
    used_vertices: Optional[set[int]] = None,
) -> None:
    name = str(spec.get("name", "port"))
    coll = ensure_collection(name, parent_collection)
    root = create_empty(name, coll)

    target = str(spec.get("target", "boundary"))
    if target not in boundaries:
        raise RuntimeError(f'Port "{name}" target boundary "{target}" not found.')

    boundary = boundaries[target]
    parent_keep_world(root, boundary.root)

    attach = spec.get("attach", {}) if isinstance(spec.get("attach", {}), dict) else {}
    ap = spec.get("auto_placement", {}) if isinstance(spec.get("auto_placement", {}), dict) else {}
    enabled = bool(ap.get("enabled", True))
    if not enabled and attach.get("index", None) is None:
        raise RuntimeError(f'Port "{name}": auto_placement disabled but no attach.index specified.')

    used_set = used_vertices if used_vertices is not None else set()
    placement = choose_vertex_and_length_for_port(scene, cam_obj, boundary, spec, used_vertices=used_set)
    # Track used vertex so subsequent AUTO-selected ports don't stack on the same vertex.
    try:
        used_set.add(int(placement.vertex_index))
    except Exception:
        pass

    # Store the resolved vertex index for UI/debugging
    root["attach_site_type"] = "VERTEX"
    root["attach_index"] = int(placement.vertex_index)

    cyl_cfg = spec.get("cylinder", {}) if isinstance(spec.get("cylinder", {}), dict) else {}
    cyl_radius = float(cyl_cfg.get("radius", 0.03))
    cyl_sides = int(cyl_cfg.get("sides", 24))
    cyl_color = parse_color_rgb(cyl_cfg.get("color"), default=(1.0, 1.0, 1.0))
    cyl_alpha = clamp01(cyl_cfg.get("alpha", 1.0))

    base_offset = cyl_cfg.get("base_offset", "AUTO")
    if base_offset == "AUTO":
        base_offset = max(float(boundary.vertex_radius) * 1.05, cyl_radius * 1.05)
    base_offset = float(base_offset)

    mat_cyl = make_transparent_material(f"{name}_Mat_Cylinder", cyl_color, cyl_alpha, roughness=0.25, emission_strength=0.0)
    cyl_mesh = unit_cylinder_mesh(cyl_sides, cap_ends=True)

    z_axis = Vector((0.0, 0.0, 1.0))
    dir_w = placement.dir_w.normalized()
    L = float(placement.length)

    # Cylinder spans from (base_w + base_offset) to (base_w + base_offset + L)
    cyl_center = placement.base_w + dir_w * base_offset + dir_w * (L * 0.5)

    cyl_obj = create_mesh_object(f"{name}_Cylinder", cyl_mesh, coll)
    cyl_obj.rotation_mode = "QUATERNION"
    cyl_obj.rotation_quaternion = z_axis.rotation_difference(dir_w)
    cyl_obj.location = (cyl_center.x, cyl_center.y, cyl_center.z)
    cyl_obj.scale = (cyl_radius, cyl_radius, L / 2.0)
    assign_material(cyl_obj, mat_cyl)
    parent_keep_world(cyl_obj, root)

    # Optional arrowheads to indicate flow direction (IN/OUT/BIDIR)
    flow_cfg = spec.get("flow", {}) if isinstance(spec.get("flow", {}), dict) else {}
    flow_dir = str(flow_cfg.get("direction", spec.get("direction", "OUT")) or "OUT").upper()
    if flow_dir in {"IN"}:
        arrow_mode = "IN"
    elif flow_dir in {"OUT"}:
        arrow_mode = "OUT"
    elif flow_dir in {"BIDIR", "INOUT", "BOTH"}:
        arrow_mode = "BIDIR"
    else:
        arrow_mode = "OUT"

    arrow_cfg = spec.get("arrow", {}) if isinstance(spec.get("arrow", {}), dict) else {}
    arrow_enabled = bool(arrow_cfg.get("enabled", True))
    arrow_len = float(arrow_cfg.get("length", arrow_cfg.get("size", max(0.12, cyl_radius * 6.0))))
    arrow_radius = float(arrow_cfg.get("radius", arrow_cfg.get("width", max(0.06, cyl_radius * 2.0))))
    arrow_sides = int(arrow_cfg.get("sides", cyl_sides))

    if arrow_enabled and arrow_len > 1e-6 and arrow_radius > 1e-6:
        cone_mesh = unit_cone_mesh(arrow_sides, cap_base=True)

        base_pt = placement.base_w + dir_w * base_offset
        tip_pt = placement.base_w + dir_w * (base_offset + L)

        def _make_arrow(obj_name: str, center: Vector, direction: Vector):
            aobj = create_mesh_object(obj_name, cone_mesh, coll)
            aobj.rotation_mode = "QUATERNION"
            aobj.rotation_quaternion = z_axis.rotation_difference(direction)
            aobj.location = (center.x, center.y, center.z)
            aobj.scale = (arrow_radius, arrow_radius, arrow_len / 2.0)
            assign_material(aobj, mat_cyl)
            parent_keep_world(aobj, root)

        if arrow_mode in {"OUT", "BIDIR"}:
            # Head at the outer end, pointing outward
            center = tip_pt - dir_w * (arrow_len * 0.5)
            _make_arrow(f"{name}_Arrow_OUT", center, dir_w)
        if arrow_mode in {"IN", "BIDIR"}:
            # Head near the boundary, pointing inward
            center = base_pt + dir_w * (arrow_len * 0.5)
            _make_arrow(f"{name}_Arrow_IN", center, -dir_w)

    # Board placement at ray tip
    board_cfg = spec.get("board", {}) if isinstance(spec.get("board", {}), dict) else {}
    gap = board_cfg.get("gap", "AUTO")
    if gap == "AUTO":
        gap = max(0.02, cyl_radius * 2.5)
    gap = float(gap)

    tip_w = placement.base_w + dir_w * (base_offset + L)
    board_center = tip_w + dir_w * gap

    board_root = create_empty(f"{name}_Board", coll)

    # Allow per-port override, else use global setting
    pm = str(board_cfg.get("plane_mode", board_plane_mode or "CAMERA")).upper()
    if pm not in {"CAMERA", "AXIS"}:
        pm = "CAMERA"

    if pm == "AXIS":
        # Plane normal along the port axis, but flip to face the camera if needed
        normal = dir_w.normalized()
        cam_to_board = cam_obj.matrix_world.translation - board_center
        if normal.dot(cam_to_board) < 0.0:
            normal = -normal

        R = cam_obj.matrix_world.to_3x3()
        cam_right = R @ Vector((1.0, 0.0, 0.0))
        cam_up = R @ Vector((0.0, 1.0, 0.0))

        right = cam_right - normal * cam_right.dot(normal)
        if right.length < 1e-9:
            right = cam_up - normal * cam_up.dot(normal)
        if right.length < 1e-9:
            tmp = Vector((1.0, 0.0, 0.0)) if abs(normal.x) < 0.9 else Vector((0.0, 1.0, 0.0))
            right = tmp - normal * tmp.dot(normal)

        right.normalize()
        up = normal.cross(right).normalized()
        basis = Matrix((right, up, normal)).transposed()
    else:
        basis = camera_billboard_basis(cam_obj)

    board_root.matrix_world = Matrix.Translation(board_center) @ basis.to_4x4()
    parent_keep_world(board_root, root)

    # Content (image + text)
    layout_cfg = spec.get("layout", {}) if isinstance(spec.get("layout", {}), dict) else {}
    spacing = float(layout_cfg.get("spacing", 0.05))
    padding = float(layout_cfg.get("padding", 0.04))
    image_above_text = bool(layout_cfg.get("image_above_text", True))

    text_cfg = spec.get("text", {}) if isinstance(spec.get("text", {}), dict) else {}
    text_value = str(text_cfg.get("value", "") or "")
    want_text = bool(text_value.strip())

    image_cfg = spec.get("image", {}) if isinstance(spec.get("image", {}), dict) else {}
    want_image = isinstance(image_cfg.get("filepath", None), str) and bool(image_cfg.get("filepath", "").strip())

    text_color = parse_color_rgb(text_cfg.get("color"), default=(1.0, 1.0, 1.0))
    text_alpha = clamp01(text_cfg.get("alpha", 1.0))
    mat_text = make_transparent_material(f"{name}_Mat_Text", text_color, text_alpha, roughness=0.4, emission_strength=0.0)

    text_obj = None
    text_w = text_h = 0.0
    if want_text:
        text_obj = create_text_object(f"{name}_Text", text_cfg, coll, mat_text)
        parent_inherit(text_obj, board_root)
        text_obj.location = (0.0, 0.0, 0.0)
        text_obj.rotation_euler = (0.0, 0.0, 0.0)
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        text_w = float(text_obj.dimensions.x)
        text_h = float(text_obj.dimensions.y)

    img_obj = None
    img_w = img_h = 0.0
    if want_image:
        out = create_image_plane(f"{name}_Image", image_cfg, coll, project_root=project_root)
        if out is not None:
            img_obj, img_w, img_h = out
            parent_inherit(img_obj, board_root)
            img_obj.location = (0.0, 0.0, 0.0)
            img_obj.rotation_euler = (0.0, 0.0, 0.0)

    elements = []
    if img_obj is not None:
        elements.append(("image", img_obj, img_w, img_h))
    if text_obj is not None:
        elements.append(("text", text_obj, text_w, text_h))

    if not elements:
        # No text/image content requested/available: do not create fallback text.
        return

    if len(elements) == 1:
        _, obj, _, _ = elements[0]
        obj.location = (0.0, 0.0, 0.0)
    else:
        if image_above_text:
            top = next(e for e in elements if e[0] == "image")
            bottom = next(e for e in elements if e[0] == "text")
        else:
            top = next(e for e in elements if e[0] == "text")
            bottom = next(e for e in elements if e[0] == "image")

        _, top_obj, _, top_h = top
        _, bot_obj, _, bot_h = bottom

        total_h = top_h + bot_h + spacing + 2.0 * padding
        y_top = (total_h / 2.0) - padding - (top_h / 2.0)
        y_bot = y_top - (top_h / 2.0) - spacing - (bot_h / 2.0)

        top_obj.location = (0.0, y_top, 0.0)
        bot_obj.location = (0.0, y_bot, 0.0)


    # Apply per-text offset within the board plane (helps move text away from cylinders)
    if text_obj is not None:
        off_y = text_cfg.get("offset_y", 0.0)
        try:
            off_y = float(off_y)
        except Exception:
            off_y = 0.0
        if abs(off_y) > 1.0e-9:
            text_obj.location.y += off_y


    root["cylinder_length"] = float(L)


# ----------------------------
# Main
# ----------------------------

def build_scene_from_manifest(manifest: Dict[str, Any], project_root: str, do_render: bool):
    clear_scene_data()
    scene, root_coll = scene_and_root_collection()

    objects = manifest.get("objects", [])
    if not isinstance(objects, list):
        raise ValueError('"objects" must be a list in manifest.json')

    global_scale = _get_global_scale(manifest)

    boundaries: Dict[str, BoundaryInfo] = {}
    for o in objects:
        if not isinstance(o, dict):
            continue
        if str(o.get("type", "")).lower() == "boundary":
            info = build_boundary_object(o, parent_collection=root_coll, global_scale=global_scale)
            boundaries[info.name] = info

    boundary_for_auto = boundaries.get("boundary", None) or (next(iter(boundaries.values())) if boundaries else None)

    cam_obj = create_camera_from_manifest(manifest.get("camera", {}), parent_collection=root_coll, boundary_for_auto=boundary_for_auto)
    scene.camera = cam_obj

    create_light_from_manifest(manifest.get("light", {}), parent_collection=root_coll)
    apply_render_settings(manifest, project_root=project_root)

    # Global board/billboard settings (used by labels + ports)
    boards_cfg = manifest.get("boards", {}) if isinstance(manifest.get("boards", {}), dict) else {}
    labels_cfg = manifest.get("labels", {}) if isinstance(manifest.get("labels", {}), dict) else {}
    src_cfg = boards_cfg if boards_cfg else labels_cfg
    board_plane_mode = str(src_cfg.get("plane_mode", src_cfg.get("plane", manifest.get("label_plane_mode", "CAMERA")))).upper()
    if board_plane_mode not in {"CAMERA", "AXIS"}:
        board_plane_mode = "CAMERA"

    # Global styles for ports/labels (optional)
    styles_cfg = manifest.get("styles", {}) if isinstance(manifest.get("styles", {}), dict) else {}
    enforce_styles = bool(styles_cfg.get("enforce_global", False))

    label_style = styles_cfg.get("label", {}) if isinstance(styles_cfg.get("label", {}), dict) else {}

    port_styles = styles_cfg.get("port", {}) if isinstance(styles_cfg.get("port", {}), dict) else {}
    port_power_style = port_styles.get("power", {}) if isinstance(port_styles.get("power", {}), dict) else {}
    port_info_style = port_styles.get("info", {}) if isinstance(port_styles.get("info", {}), dict) else {}
    port_both_style = port_styles.get("both", {}) if isinstance(port_styles.get("both", {}), dict) else {}

    # Track vertices used by AUTO-selected ports so they don't stack on the same vertex.
    used_port_vertices_by_boundary: Dict[str, set[int]] = {}

    for o in objects:
        if not isinstance(o, dict):
            continue
        t = str(o.get("type", "")).lower()
        if t == "label":
            spec = _apply_style_to_spec(o, label_style, enforce_styles, is_port=False)
            spec = _apply_global_scale_to_spec(spec, global_scale)
            build_label_object(spec, boundaries, cam_obj, scene, parent_collection=root_coll, project_root=project_root, label_plane_mode=board_plane_mode)
        elif t == "port":
            kind = _get_port_kind(o)
            if kind == "INFO":
                st = port_info_style
            elif kind == "POWER":
                st = port_power_style
            elif kind in {"BOTH", "POWER+INFO", "POWER_INFO"}:
                st = (port_both_style or port_power_style)
            else:
                st = port_power_style

            spec = _apply_style_to_spec(o, st, enforce_styles, is_port=True)
            spec = _apply_global_scale_to_spec(spec, global_scale)

            target_name = str(spec.get("target", "boundary"))
            used_set = used_port_vertices_by_boundary.setdefault(target_name, set())
            build_port_object(
                spec,
                boundaries,
                cam_obj,
                scene,
                parent_collection=root_coll,
                project_root=project_root,
                board_plane_mode=board_plane_mode,
                used_vertices=used_set,
            )

    if do_render:
        try:
            bpy.ops.render.render(write_still=True)
        except RuntimeError as e:
            if "OpenImageDenoiser" in str(e):
                disable_cycles_denoise(scene)
                bpy.ops.render.render(write_still=True)
            else:
                raise
        bpy.ops.wm.quit_blender()


def main():
    args = parse_args()
    manifest_path = os.path.abspath(args.manifest)
    project_root = os.path.dirname(manifest_path) or os.getcwd()

    manifest = load_manifest(manifest_path)
    build_scene_from_manifest(manifest, project_root=project_root, do_render=bool(args.render))


if __name__ == "__main__":
    main()
