# scripts/setup_scene.py
#
# JSON-driven Blender scene builder for "solid wireframe" platonic solids / icospheres:
#   - cylinders for edges ("wires")
#   - spheres for vertices ("points")
#   - thick face plates for faces (optional via alpha/thickness)
#
# Works in headless/background contexts by avoiding bpy.context.object and avoiding
# mesh-add operators for geometry creation.

import argparse
import json
import math
import os
import sys
from typing import Any, Dict, List, Sequence, Tuple, Union

import bpy
from mathutils import Vector


# -----------------------------
# CLI + JSON helpers
# -----------------------------

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


# -----------------------------
# Scene utilities (headless-safe)
# -----------------------------

def scene_collection():
    scn = getattr(bpy.context, "scene", None) or (bpy.data.scenes[0] if bpy.data.scenes else None)
    if scn is None:
        raise RuntimeError("No Blender scene available.")
    return scn, scn.collection


def clear_scene_data():
    # Remove objects first
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    # Remove datablocks (keep worlds, etc. unless you want to clear those too)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh, do_unlink=True)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat, do_unlink=True)
    for cam in list(bpy.data.cameras):
        bpy.data.cameras.remove(cam, do_unlink=True)
    for light in list(bpy.data.lights):
        bpy.data.lights.remove(light, do_unlink=True)


def look_at(obj: bpy.types.Object, target=(0.0, 0.0, 0.0)):
    target_v = Vector(target)
    direction = target_v - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


# -----------------------------
# Materials
# -----------------------------

def make_transparent_material(
    name: str,
    color_rgb: Tuple[float, float, float],
    alpha: float,
    roughness: float = 0.35,
) -> bpy.types.Material:
    """
    Cycles + Eevee:
      - Mix Transparent BSDF with Principled based on alpha (0..1)
      - alpha=0 => fully invisible
      - alpha=1 => fully opaque
    """
    alpha = clamp01(alpha)

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links

    nodes.clear()

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (500, 0)

    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (0, -120)
    principled.inputs["Base Color"].default_value = (color_rgb[0], color_rgb[1], color_rgb[2], 1.0)
    principled.inputs["Roughness"].default_value = float(roughness)

    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (0, 120)

    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (250, 0)

    alpha_node = nodes.new("ShaderNodeValue")
    alpha_node.location = (-200, 0)
    alpha_node.outputs[0].default_value = alpha

    # Fac: 0 -> Transparent, 1 -> Principled
    links.new(alpha_node.outputs[0], mix.inputs["Fac"])
    links.new(transparent.outputs[0], mix.inputs[1])
    links.new(principled.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])

    # Viewport preview
    mat.diffuse_color = (color_rgb[0], color_rgb[1], color_rgb[2], alpha)

    # Eevee transparency flags (ignored by Cycles where not needed)
    if hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND" if alpha < 1.0 else "OPAQUE"
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "NONE" if alpha <= 0.0 else "HASHED"
    if hasattr(mat, "use_backface_culling"):
        mat.use_backface_culling = False

    return mat


def set_mesh_material(mesh: bpy.types.Mesh, mat: bpy.types.Material):
    mesh.materials.clear()
    mesh.materials.append(mat)


def smooth_shade_mesh(mesh: bpy.types.Mesh, smooth: bool):
    for poly in mesh.polygons:
        poly.use_smooth = bool(smooth)


def create_object(name: str, mesh: bpy.types.Mesh, collection: bpy.types.Collection) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


# -----------------------------
# Primitive meshes (no bpy.ops)
# -----------------------------

def create_unit_cylinder_mesh(name: str, sides: int, cap_ends: bool = True) -> bpy.types.Mesh:
    """
    Cylinder aligned to Z with:
      radius = 1
      half-length = 1 (total length = 2)
    """
    sides = max(3, int(sides))
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

    # Side quads
    for j in range(sides):
        b0 = bottom_ring[j]
        b1 = bottom_ring[(j + 1) % sides]
        t1 = top_ring[(j + 1) % sides]
        t0 = top_ring[j]
        faces.append((b0, b1, t1, t0))

    # Caps
    if cap_ends and bottom_center is not None and top_center is not None:
        for j in range(sides):
            faces.append((top_center, top_ring[j], top_ring[(j + 1) % sides]))
            faces.append((bottom_center, bottom_ring[(j + 1) % sides], bottom_ring[j]))

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    smooth_shade_mesh(mesh, True)
    return mesh


def create_unit_uv_sphere_mesh(name: str, segments: int, rings: int) -> bpy.types.Mesh:
    """
    UV sphere centered at origin with radius = 1.
    """
    segs = max(3, int(segments))
    rcount = max(3, int(rings))

    verts: List[Tuple[float, float, float]] = []
    faces: List[Tuple[int, int, int]] = []

    # Poles
    top = 0
    verts.append((0.0, 0.0, 1.0))

    # Rings
    for i in range(1, rcount):
        theta = math.pi * i / rcount
        z = math.cos(theta)
        r = math.sin(theta)
        for j in range(segs):
            phi = 2.0 * math.pi * j / segs
            x = r * math.cos(phi)
            y = r * math.sin(phi)
            verts.append((x, y, z))

    bottom = len(verts)
    verts.append((0.0, 0.0, -1.0))

    def ring_idx(i: int, j: int) -> int:
        return 1 + (i - 1) * segs + (j % segs)

    # Top fan
    for j in range(segs):
        faces.append((top, ring_idx(1, j), ring_idx(1, j + 1)))

    # Middle
    for i in range(1, rcount - 1):
        for j in range(segs):
            a = ring_idx(i, j)
            b = ring_idx(i, j + 1)
            c = ring_idx(i + 1, j + 1)
            d = ring_idx(i + 1, j)
            faces.append((a, d, c))
            faces.append((a, c, b))

    # Bottom fan
    last_ring = rcount - 1
    for j in range(segs):
        faces.append((bottom, ring_idx(last_ring, j + 1), ring_idx(last_ring, j)))

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    smooth_shade_mesh(mesh, True)
    return mesh


# -----------------------------
# Polyhedron / icosphere topology
# -----------------------------

Face = List[int]


def icosahedron_topology(radius: float) -> Tuple[List[Vector], List[Face]]:
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
    # Scale to circumradius
    base_len = verts[0].length
    scale = float(radius) / base_len if base_len > 1e-9 else 1.0
    verts = [v * scale for v in verts]

    faces: List[Face] = [
        [0, 11, 5],
        [0, 5, 1],
        [0, 1, 7],
        [0, 7, 10],
        [0, 10, 11],
        [1, 5, 9],
        [5, 11, 4],
        [11, 10, 2],
        [10, 7, 6],
        [7, 1, 8],
        [3, 9, 4],
        [3, 4, 2],
        [3, 2, 6],
        [3, 6, 8],
        [3, 8, 9],
        [4, 9, 5],
        [2, 4, 11],
        [6, 2, 10],
        [8, 6, 7],
        [9, 8, 1],
    ]
    return verts, faces


def normalize_to_radius(v: Vector, radius: float) -> Vector:
    if v.length <= 1e-12:
        return v.copy()
    return v.normalized() * float(radius)


def subdivide_icosphere(
    verts: List[Vector],
    tri_faces: List[Face],
    subdivisions: int,
    radius: float
) -> Tuple[List[Vector], List[Face]]:
    """
    Subdivide each triangle into 4. 'subdivisions' matches Blender's Icosphere parameter:
      1 -> icosahedron
      2 -> one subdivision
      3 -> two subdivisions
      ...
    """
    sub = int(subdivisions)
    if sub <= 1:
        return verts, tri_faces

    cur_verts = verts[:]
    cur_faces = [f[:] for f in tri_faces]

    for _ in range(sub - 1):
        midpoint_cache: Dict[Tuple[int, int], int] = {}

        def midpoint(a: int, b: int) -> int:
            key = (a, b) if a < b else (b, a)
            if key in midpoint_cache:
                return midpoint_cache[key]
            m = (cur_verts[a] + cur_verts[b]) * 0.5
            m = normalize_to_radius(m, radius)
            idx = len(cur_verts)
            cur_verts.append(m)
            midpoint_cache[key] = idx
            return idx

        new_faces: List[Face] = []
        for f in cur_faces:
            a, b, c = f[0], f[1], f[2]
            ab = midpoint(a, b)
            bc = midpoint(b, c)
            ca = midpoint(c, a)
            new_faces.append([a, ab, ca])
            new_faces.append([b, bc, ab])
            new_faces.append([c, ca, bc])
            new_faces.append([ab, bc, ca])
        cur_faces = new_faces

    return cur_verts, cur_faces


def tetrahedron_topology(radius: float) -> Tuple[List[Vector], List[Face]]:
    verts = [
        Vector(( 1.0,  1.0,  1.0)),
        Vector((-1.0, -1.0,  1.0)),
        Vector((-1.0,  1.0, -1.0)),
        Vector(( 1.0, -1.0, -1.0)),
    ]
    # scale to circumradius
    base_len = verts[0].length  # sqrt(3)
    scale = float(radius) / base_len if base_len > 1e-9 else 1.0
    verts = [v * scale for v in verts]
    faces: List[Face] = [
        [0, 1, 2],
        [0, 3, 1],
        [0, 2, 3],
        [1, 3, 2],
    ]
    return verts, faces


def octahedron_topology(radius: float) -> Tuple[List[Vector], List[Face]]:
    verts = [
        Vector(( 1.0, 0.0, 0.0)),
        Vector((-1.0, 0.0, 0.0)),
        Vector((0.0,  1.0, 0.0)),
        Vector((0.0, -1.0, 0.0)),
        Vector((0.0, 0.0,  1.0)),
        Vector((0.0, 0.0, -1.0)),
    ]
    verts = [v * float(radius) for v in verts]
    faces: List[Face] = [
        [0, 2, 4],
        [2, 1, 4],
        [1, 3, 4],
        [3, 0, 4],
        [2, 0, 5],
        [1, 2, 5],
        [3, 1, 5],
        [0, 3, 5],
    ]
    return verts, faces


def cube_topology(radius: float) -> Tuple[List[Vector], List[Face]]:
    verts = [
        Vector((-1.0, -1.0, -1.0)),
        Vector(( 1.0, -1.0, -1.0)),
        Vector(( 1.0,  1.0, -1.0)),
        Vector((-1.0,  1.0, -1.0)),
        Vector((-1.0, -1.0,  1.0)),
        Vector(( 1.0, -1.0,  1.0)),
        Vector(( 1.0,  1.0,  1.0)),
        Vector((-1.0,  1.0,  1.0)),
    ]
    base_len = verts[0].length  # sqrt(3)
    scale = float(radius) / base_len if base_len > 1e-9 else 1.0
    verts = [v * scale for v in verts]

    # 6 square faces (as quads). We'll keep them as quads for plates.
    faces: List[Face] = [
        [0, 1, 2, 3],  # bottom
        [4, 5, 6, 7],  # top
        [0, 1, 5, 4],  # front
        [1, 2, 6, 5],  # right
        [2, 3, 7, 6],  # back
        [3, 0, 4, 7],  # left
    ]
    return verts, faces


def face_normal_newell(verts: List[Vector], face: Face) -> Vector:
    # Newell's method for polygon normal
    n = Vector((0.0, 0.0, 0.0))
    m = len(face)
    for i in range(m):
        v0 = verts[face[i]]
        v1 = verts[face[(i + 1) % m]]
        n.x += (v0.y - v1.y) * (v0.z + v1.z)
        n.y += (v0.z - v1.z) * (v0.x + v1.x)
        n.z += (v0.x - v1.x) * (v0.y + v1.y)
    if n.length <= 1e-12:
        return n
    return n.normalized()


def dodecahedron_from_icosahedron(radius: float) -> Tuple[List[Vector], List[Face]]:
    """
    Dodecahedron is the dual of the icosahedron.
    - Dual vertices = normalized face centroids of the icosahedron
    - Dual faces: for each icosahedron vertex, connect the 5 adjacent face-centers
      ordered around that vertex.
    """
    ico_verts, ico_faces = icosahedron_topology(radius=1.0)

    # Dual vertices = face centroids projected to sphere
    dual_verts: List[Vector] = []
    for f in ico_faces:
        c = (ico_verts[f[0]] + ico_verts[f[1]] + ico_verts[f[2]]) / 3.0
        dual_verts.append(normalize_to_radius(c, radius))

    # For each ico vertex, list adjacent faces
    faces_per_vertex: List[List[int]] = [[] for _ in range(len(ico_verts))]
    for fi, f in enumerate(ico_faces):
        for vi in f:
            faces_per_vertex[vi].append(fi)

    dual_faces: List[Face] = []
    for vi, adj in enumerate(faces_per_vertex):
        axis = normalize_to_radius(ico_verts[vi], 1.0)
        if axis.length <= 1e-12:
            continue
        axis = axis.normalized()

        # Build a stable local basis around axis
        ref = Vector((0.0, 0.0, 1.0))
        if abs(axis.dot(ref)) > 0.9:
            ref = Vector((0.0, 1.0, 0.0))
        u = axis.cross(ref)
        if u.length <= 1e-12:
            continue
        u.normalize()
        w = axis.cross(u)
        w.normalize()

        items = []
        for fi in adj:
            p = dual_verts[fi]
            # project onto plane perpendicular to axis
            pp = p - axis * p.dot(axis)
            ang = math.atan2(pp.dot(w), pp.dot(u))
            items.append((ang, fi))
        items.sort(key=lambda t: t[0])

        dual_faces.append([fi for _, fi in items])

    # For a regular icosahedron, each vertex has exactly 5 adjacent faces -> 12 pentagons
    return dual_verts, dual_faces


def generate_shape(cfg: Dict[str, Any], radius: float) -> Tuple[List[Vector], List[Face]]:
    shape_cfg = cfg.get("shape", {"type": "icosahedron"})
    if isinstance(shape_cfg, str):
        stype = shape_cfg
        shape_cfg = {"type": stype}
    if not isinstance(shape_cfg, dict):
        shape_cfg = {"type": "icosahedron"}

    stype = str(shape_cfg.get("type", "icosahedron")).lower()
    subdivisions = int(shape_cfg.get("subdivisions", 1))

    if stype in {"icosahedron", "ico"}:
        verts, faces = icosahedron_topology(radius=radius)
        return verts, faces

    if stype in {"icosphere", "ico_sphere"}:
        verts, faces = icosahedron_topology(radius=radius)
        # faces already triangles
        verts, faces = subdivide_icosphere(verts, faces, subdivisions=subdivisions, radius=radius)
        return verts, faces

    if stype in {"tetrahedron", "tetra"}:
        return tetrahedron_topology(radius=radius)

    if stype in {"cube", "hexahedron", "box"}:
        return cube_topology(radius=radius)

    if stype in {"octahedron", "octa"}:
        return octahedron_topology(radius=radius)

    if stype in {"dodecahedron", "dodeca"}:
        return dodecahedron_from_icosahedron(radius=radius)

    raise ValueError(f"Unknown shape type '{stype}'. Supported: icosahedron, icosphere, tetrahedron, cube, octahedron, dodecahedron.")


# -----------------------------
# Build edges / vertices / plates
# -----------------------------

def unique_edges_from_faces(faces: List[Face]) -> List[Tuple[int, int]]:
    edges = set()
    for f in faces:
        m = len(f)
        for i in range(m):
            a = int(f[i])
            b = int(f[(i + 1) % m])
            if a == b:
                continue
            edges.add((a, b) if a < b else (b, a))
    return sorted(edges)


def build_edge_objects(
    verts: List[Vector],
    faces: List[Face],
    edge_radius: float,
    edge_sides: int,
    mat_edges: bpy.types.Material,
    collection: bpy.types.Collection,
):
    cyl_mesh = create_unit_cylinder_mesh("EdgeCylinderMesh", sides=edge_sides, cap_ends=True)
    set_mesh_material(cyl_mesh, mat_edges)

    z_axis = Vector((0.0, 0.0, 1.0))

    for i, j in unique_edges_from_faces(faces):
        v1 = verts[i]
        v2 = verts[j]
        d = v2 - v1
        length = d.length
        if length <= 1e-12:
            continue

        mid = (v1 + v2) * 0.5
        dir_n = d.normalized()

        obj = create_object(f"Edge_{i:03d}_{j:03d}", cyl_mesh, collection)
        obj.location = (mid.x, mid.y, mid.z)
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = z_axis.rotation_difference(dir_n)

        # unit cylinder: radius=1 in XY, half-length=1 in Z
        obj.scale = (float(edge_radius), float(edge_radius), float(length) / 2.0)


def build_vertex_objects(
    verts: List[Vector],
    vertex_radius: float,
    sphere_segments: int,
    sphere_rings: int,
    mat_verts: bpy.types.Material,
    collection: bpy.types.Collection,
):
    sph_mesh = create_unit_uv_sphere_mesh("VertexSphereMesh", segments=sphere_segments, rings=sphere_rings)
    set_mesh_material(sph_mesh, mat_verts)

    for idx, v in enumerate(verts):
        obj = create_object(f"Vertex_{idx:03d}", sph_mesh, collection)
        obj.location = (v.x, v.y, v.z)
        obj.scale = (float(vertex_radius), float(vertex_radius), float(vertex_radius))


def build_face_plates(
    verts: List[Vector],
    faces: List[Face],
    thickness: float,
    mat_faces: bpy.types.Material,
    face_alpha: float,
    collection: bpy.types.Collection,
) -> bpy.types.Object:
    """
    Create one mesh containing faces as independent islands (no shared verts),
    then Solidify to make plates with thickness + rim walls.
    """
    mesh = bpy.data.meshes.new("FacePlatesMesh")

    plate_verts: List[Tuple[float, float, float]] = []
    plate_faces: List[Tuple[int, ...]] = []

    for f in faces:
        base = len(plate_verts)
        for vi in f:
            vv = verts[int(vi)]
            plate_verts.append((vv.x, vv.y, vv.z))
        plate_faces.append(tuple(base + k for k in range(len(f))))

    mesh.from_pydata(plate_verts, [], plate_faces)
    mesh.update()

    smooth_shade_mesh(mesh, False)
    set_mesh_material(mesh, mat_faces)

    obj = create_object("FacePlates", mesh, collection)

    # Wireframe mode: hide plates completely
    if face_alpha <= 0.0 or thickness <= 0.0:
        obj.hide_viewport = True
        obj.hide_render = True
        return obj

    mod = obj.modifiers.new(name="Solidify", type="SOLIDIFY")
    mod.thickness = float(thickness)
    mod.offset = 0.0
    if hasattr(mod, "use_even_offset"):
        mod.use_even_offset = True
    if hasattr(mod, "use_rim"):
        mod.use_rim = True

    return obj


# -----------------------------
# Camera selection (avoid symmetry axes)
# -----------------------------

def fibonacci_sphere(n: int) -> List[Vector]:
    # Deterministic, reasonably uniform distribution on a sphere.
    pts: List[Vector] = []
    n = max(16, int(n))
    golden = (1.0 + math.sqrt(5.0)) / 2.0
    for i in range(n):
        t = (i + 0.5) / n
        z = 1.0 - 2.0 * t
        r = math.sqrt(max(0.0, 1.0 - z * z))
        theta = 2.0 * math.pi * i / golden
        x = r * math.cos(theta)
        y = r * math.sin(theta)
        pts.append(Vector((x, y, z)))
    return pts


def face_axes(verts: List[Vector], faces: List[Face]) -> List[Vector]:
    axes: List[Vector] = []
    for f in faces:
        n = face_normal_newell(verts, f)
        if n.length > 1e-6:
            axes.append(n)
    return axes


def vertex_axes(verts: List[Vector]) -> List[Vector]:
    axes: List[Vector] = []
    for v in verts:
        if v.length > 1e-6:
            axes.append(v.normalized())
    return axes


def edge_mid_axes(verts: List[Vector], faces: List[Face]) -> List[Vector]:
    axes: List[Vector] = []
    for i, j in unique_edges_from_faces(faces):
        m = verts[i] + verts[j]
        if m.length > 1e-6:
            axes.append(m.normalized())
    return axes


def projected_min_vertex_distance(verts: List[Vector], view_dir: Vector) -> float:
    # Larger is better (less overlap).
    d = view_dir.normalized()
    up = Vector((0.0, 0.0, 1.0))
    u = d.cross(up)
    if u.length < 1e-6:
        up = Vector((0.0, 1.0, 0.0))
        u = d.cross(up)
    u.normalize()
    v = d.cross(u)
    v.normalize()

    pts = [(vv.dot(u), vv.dot(v)) for vv in verts]
    min_dist2 = float("inf")
    for i in range(len(pts)):
        x1, y1 = pts[i]
        for j in range(i + 1, len(pts)):
            x2, y2 = pts[j]
            dx = x1 - x2
            dy = y1 - y2
            dist2 = dx * dx + dy * dy
            if dist2 < min_dist2:
                min_dist2 = dist2
    if min_dist2 == float("inf"):
        return 0.0
    return math.sqrt(min_dist2)


def choose_nonsymmetric_view_direction(verts: List[Vector], faces: List[Face]) -> Vector:
    axes = vertex_axes(verts) + face_axes(verts, faces) + edge_mid_axes(verts, faces)

    candidates = fibonacci_sphere(2048)

    best_dir = None
    best_key = None

    for d in candidates:
        # Prefer "front-ish" and "above-ish" so posters look consistent
        if d.y > -0.05:
            continue
        if d.z < 0.05:
            continue
        if abs(d.x) < 0.10:
            continue

        # primary: avoid aligning with symmetry axes (minimize max abs dot)
        max_abs_dot = 0.0
        for a in axes:
            ad = abs(d.dot(a))
            if ad > max_abs_dot:
                max_abs_dot = ad
                if max_abs_dot > 0.995:
                    break

        # secondary: reduce projected overlaps between vertices
        sep = projected_min_vertex_distance(verts, d)

        key = (max_abs_dot, -sep)
        if best_key is None or key < best_key:
            best_key = key
            best_dir = d

    if best_dir is None:
        # Fallback that is usually "not aligned" but still deterministic
        best_dir = Vector((0.73, -0.51, 0.45)).normalized()

    return best_dir.normalized()


def create_camera_from_config(
    camera_cfg: Dict[str, Any],
    verts: List[Vector],
    faces: List[Face],
    distance_default: float,
    collection: bpy.types.Collection,
) -> bpy.types.Object:
    target = camera_cfg.get("target", [0.0, 0.0, 0.0])
    if isinstance(target, (list, tuple)) and len(target) >= 3:
        target_v = Vector((float(target[0]), float(target[1]), float(target[2])))
    else:
        target_v = Vector((0.0, 0.0, 0.0))

    lens_mm = float(camera_cfg.get("lens_mm", 50.0))
    distance = float(camera_cfg.get("distance", distance_default))

    loc = camera_cfg.get("location", None)
    az = camera_cfg.get("azimuth_deg", None)
    el = camera_cfg.get("elevation_deg", None)

    if isinstance(loc, (list, tuple)) and len(loc) >= 3:
        cam_loc = Vector((float(loc[0]), float(loc[1]), float(loc[2])))
    elif az is not None and el is not None:
        azr = math.radians(float(az))
        elr = math.radians(float(el))
        # direction from origin to camera
        cam_dir = Vector((
            math.cos(elr) * math.cos(azr),
            math.cos(elr) * math.sin(azr),
            math.sin(elr),
        )).normalized()
        cam_loc = target_v + cam_dir * distance
    else:
        cam_dir = choose_nonsymmetric_view_direction(verts, faces)
        cam_loc = target_v + cam_dir * distance

    cam_data = bpy.data.cameras.new("Camera")
    cam_obj = bpy.data.objects.new("Camera", cam_data)
    collection.objects.link(cam_obj)

    cam_obj.location = (cam_loc.x, cam_loc.y, cam_loc.z)
    cam_data.lens = lens_mm
    look_at(cam_obj, (target_v.x, target_v.y, target_v.z))

    scn, _ = scene_collection()
    scn.camera = cam_obj
    return cam_obj


def create_light(light_type: str, energy: float, location: Sequence[float], collection: bpy.types.Collection) -> bpy.types.Object:
    lt = str(light_type).upper()
    if lt not in {"SUN", "POINT", "SPOT", "AREA"}:
        lt = "SUN"
    light_data = bpy.data.lights.new("KeyLight", type=lt)
    light_obj = bpy.data.objects.new("KeyLight", light_data)
    collection.objects.link(light_obj)

    light_obj.location = (float(location[0]), float(location[1]), float(location[2]))
    light_data.energy = float(energy)
    look_at(light_obj, (0.0, 0.0, 0.0))
    return light_obj


# -----------------------------
# Render settings + Cycles denoise safety
# -----------------------------

def disable_cycles_denoising():
    # Some Blender builds (like yours) can be compiled without OpenImageDenoise.
    # If denoising gets enabled anywhere, Cycles may error at render time.
    scn, _ = scene_collection()

    # Scene-level denoise flag (if present)
    if hasattr(scn, "cycles") and hasattr(scn.cycles, "use_denoising"):
        scn.cycles.use_denoising = False

    # View-layer denoise flag (common)
    for vl in scn.view_layers:
        if hasattr(vl, "cycles") and hasattr(vl.cycles, "use_denoising"):
            vl.cycles.use_denoising = False


def apply_render_settings(cfg: dict, project_root: str):
    scn, _ = scene_collection()
    r = scn.render
    rcfg = cfg.get("render", {}) if isinstance(cfg.get("render", {}), dict) else {}

    engine_raw = str(rcfg.get("engine", "BLENDER_EEVEE")).upper()
    if engine_raw in {"EEVEE", "BLENDER_EEVEE"}:
        engine = "BLENDER_EEVEE"
    elif engine_raw == "CYCLES":
        engine = "CYCLES"
    else:
        engine = engine_raw  # allow user to pass actual id if needed

    r.engine = engine

    r.resolution_x = int(rcfg.get("resolution_x", 1024))
    r.resolution_y = int(rcfg.get("resolution_y", 1024))
    r.resolution_percentage = 100

    file_format = str(rcfg.get("file_format", "PNG"))
    r.image_settings.file_format = file_format
    if file_format.upper() == "PNG":
        r.image_settings.color_mode = "RGBA"

    r.film_transparent = bool(rcfg.get("transparent", False))

    raw_path = str(rcfg.get("filepath", "output/render.png"))
    abs_path = os.path.abspath(os.path.join(project_root, raw_path))
    base, _ext = os.path.splitext(abs_path)
    out_dir = os.path.dirname(base)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    r.filepath = base
    r.use_file_extension = True

    # Unified "samples" knob (interpreted per engine)
    samples_default = int(rcfg.get("samples", 64))

    # Engine-specific settings
    if engine == "CYCLES" and hasattr(scn, "cycles"):
        c = scn.cycles
        cycles_cfg = rcfg.get("cycles", {}) if isinstance(rcfg.get("cycles", {}), dict) else {}

        samples = int(cycles_cfg.get("samples", samples_default))
        c.samples = samples

        if "adaptive_sampling" in cycles_cfg and hasattr(c, "use_adaptive_sampling"):
            c.use_adaptive_sampling = bool(cycles_cfg["adaptive_sampling"])
        if "adaptive_threshold" in cycles_cfg and hasattr(c, "adaptive_threshold"):
            c.adaptive_threshold = float(cycles_cfg["adaptive_threshold"])

        # Clamp helps reduce fireflies/noisy speckles
        if "clamp_indirect" in cycles_cfg and hasattr(c, "sample_clamp_indirect"):
            c.sample_clamp_indirect = float(cycles_cfg["clamp_indirect"])
        if "clamp_direct" in cycles_cfg and hasattr(c, "sample_clamp_direct"):
            c.sample_clamp_direct = float(cycles_cfg["clamp_direct"])

        if "max_bounces" in cycles_cfg and hasattr(c, "max_bounces"):
            c.max_bounces = int(cycles_cfg["max_bounces"])

        # Never enable OIDN denoise here (Guix build may not have it)
        disable_cycles_denoising()

        # If the user explicitly requested denoise, ignore it but don't crash
        if bool(cycles_cfg.get("denoise", False)):
            disable_cycles_denoising()

    elif engine == "BLENDER_EEVEE" and hasattr(scn, "eevee"):
        e = scn.eevee
        eevee_cfg = rcfg.get("eevee", {}) if isinstance(rcfg.get("eevee", {}), dict) else {}

        taa = int(eevee_cfg.get("taa_render_samples", samples_default))
        if hasattr(e, "taa_render_samples"):
            e.taa_render_samples = taa


# -----------------------------
# Main
# -----------------------------

def main():
    args = parse_args()
    manifest_path = os.path.abspath(args.manifest)
    project_root = os.getcwd()

    cfg = load_manifest(manifest_path)

    # Size
    radius = float(cfg.get("radius", 1.0))

    # Shape
    verts, faces = generate_shape(cfg, radius=radius)

    # Style
    edges_cfg = cfg.get("edges", {}) if isinstance(cfg.get("edges", {}), dict) else {}
    verts_cfg = cfg.get("vertices", {}) if isinstance(cfg.get("vertices", {}), dict) else {}
    faces_cfg = cfg.get("faces", {}) if isinstance(cfg.get("faces", {}), dict) else {}
    detail_cfg = cfg.get("detail", {}) if isinstance(cfg.get("detail", {}), dict) else {}

    edge_radius = float(edges_cfg.get("radius", 0.05))
    edge_color = parse_color_rgb(edges_cfg.get("color"), default=(0.0, 1.0, 0.4))
    edge_alpha = clamp01(edges_cfg.get("alpha", 1.0))

    vertex_radius = float(verts_cfg.get("radius", 0.08))
    vertex_color = parse_color_rgb(verts_cfg.get("color"), default=(1.0, 0.0, 1.0))
    vertex_alpha = clamp01(verts_cfg.get("alpha", 1.0))

    face_thickness = float(faces_cfg.get("thickness", 0.03))
    face_color = parse_color_rgb(faces_cfg.get("color"), default=(0.0, 1.0, 1.0))
    face_alpha = clamp01(faces_cfg.get("alpha", 0.10))

    edge_sides = int(detail_cfg.get("edge_cylinder_sides", 24))
    sphere_segs = int(detail_cfg.get("vertex_sphere_segments", 32))
    sphere_rings = int(detail_cfg.get("vertex_sphere_rings", 16))

    # Clear scene and create
    clear_scene_data()
    scn, coll = scene_collection()

    # Materials
    mat_edges = make_transparent_material("Mat_Edges", edge_color, edge_alpha, roughness=0.25)
    mat_verts = make_transparent_material("Mat_Vertices", vertex_color, vertex_alpha, roughness=0.20)
    mat_faces = make_transparent_material("Mat_Faces", face_color, face_alpha, roughness=0.45)

    # Geometry
    build_edge_objects(verts, faces, edge_radius=edge_radius, edge_sides=edge_sides, mat_edges=mat_edges, collection=coll)
    build_vertex_objects(verts, vertex_radius=vertex_radius, sphere_segments=sphere_segs, sphere_rings=sphere_rings, mat_verts=mat_verts, collection=coll)
    build_face_plates(verts, faces, thickness=face_thickness, mat_faces=mat_faces, face_alpha=face_alpha, collection=coll)

    # Camera + light
    extent = radius + max(edge_radius, vertex_radius, face_thickness) * 3.0
    camera_cfg = cfg.get("camera", {}) if isinstance(cfg.get("camera", {}), dict) else {}
    light_cfg = cfg.get("light", {}) if isinstance(cfg.get("light", {}), dict) else {}

    distance_default = float(camera_cfg.get("distance", extent * 3.2))
    create_camera_from_config(camera_cfg, verts, faces, distance_default=distance_default, collection=coll)

    light_type = str(light_cfg.get("type", "SUN"))
    light_energy = float(light_cfg.get("energy", 3.0))
    light_loc = light_cfg.get("location", [extent * 3.0, -extent * 3.0, extent * 4.0])
    create_light(light_type=light_type, energy=light_energy, location=light_loc, collection=coll)

    # Render settings
    apply_render_settings(cfg, project_root=project_root)

    if args.render:
        # If Cycles denoising sneaks on somehow, retry after forcing it off.
        try:
            bpy.ops.render.render(write_still=True)
        except RuntimeError as e:
            msg = str(e)
            if "OpenImageDenoiser" in msg or "OpenImageDenoise" in msg:
                disable_cycles_denoising()
                bpy.ops.render.render(write_still=True)
            else:
                raise
        bpy.ops.wm.quit_blender()


if __name__ == "__main__":
    main()
