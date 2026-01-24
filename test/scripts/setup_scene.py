# scripts/setup_scene.py
#
# Scene generator driven by manifest.json.
#
# Manifest schema (relevant part):
# {
#   "objects": [
#     {
#       "name": "boundary",
#       "type": "boundary",
#       "shape": {"type": "icosahedron|icosphere|tetrahedron|cube|octahedron|dodecahedron", "subdivisions": 0..},
#       "radius": 1.25,
#       "edges": {"radius": 0.05, "color": [r,g,b]|"#RRGGBB", "alpha": 1.0},
#       "vertices": {"radius": 0.08, "color": ..., "alpha": 1.0},
#       "faces": {"thickness": 0.03, "color": ..., "alpha": 0.10},
#       "detail": {"edge_cylinder_sides": 24, "vertex_sphere_segments": 32, "vertex_sphere_rings": 16},
#       "transform": {"location":[x,y,z], "rotation_deg":[rx,ry,rz], "scale":[sx,sy,sz]}
#     }
#   ],
#   "render": {...},
#   "camera": {...},
#   "light": {...}
# }
#
# The "boundary" object is represented in Blender as:
#   - an Empty root named <name>
#   - children:
#       * cylinders for edges
#       * spheres for vertices
#       * one "FacePlates" mesh object (optional) with Solidify modifier
#
# This script avoids reliance on bpy.context.object and avoids mesh-add operators
# for geometry creation so it works reliably in --background headless rendering.
#
import argparse
import json
import math
import os
import sys
from typing import Any, Dict, Iterable, List, Sequence, Tuple, Union

import bpy
from mathutils import Vector, Matrix


# ----------------------------
# Utilities
# ----------------------------

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


def scene_and_root_collection():
    scn = getattr(bpy.context, "scene", None) or (bpy.data.scenes[0] if bpy.data.scenes else None)
    if scn is None:
        raise RuntimeError("No Blender scene available.")
    return scn, scn.collection


def clear_scene_data():
    """
    Remove objects + common data-blocks without relying on bpy.ops (reliable in headless contexts).
    """
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh, do_unlink=True)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat, do_unlink=True)
    for cam in list(bpy.data.cameras):
        bpy.data.cameras.remove(cam, do_unlink=True)
    for light in list(bpy.data.lights):
        bpy.data.lights.remove(light, do_unlink=True)

    # Collections (except the scene master collection) get removed automatically when unlinked,
    # but to be safe, remove leftover user collections.
    for coll in list(bpy.data.collections):
        # Do not remove master scene collection (it's not in bpy.data.collections in the same way),
        # but extra collections are safe to remove.
        if coll.users == 0:
            bpy.data.collections.remove(coll, do_unlink=True)


def ensure_collection(name: str, parent: bpy.types.Collection) -> bpy.types.Collection:
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
    # In Blender, `parent.children` is a bpy_prop_collection and membership checks
    # ("x in parent.children") expect a *name string*, not a Collection object.
    # Using the object form can raise:
    #   TypeError: bpy_prop_collection.__contains__: expected a string...
    # So we check/link by name.
    if parent.children.get(coll.name) is None:
        parent.children.link(coll)
    return coll


def make_transparent_material(
    name: str,
    color_rgb: Tuple[float, float, float],
    alpha: float,
    roughness: float = 0.35,
) -> bpy.types.Material:
    """
    Works in Cycles and Eevee:
      - Mix Transparent BSDF with Principled using alpha (0..1).
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
    out.location = (520, 0)

    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (0, -120)
    principled.inputs["Base Color"].default_value = (color_rgb[0], color_rgb[1], color_rgb[2], 1.0)
    principled.inputs["Roughness"].default_value = float(roughness)

    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (0, 120)
    transparent.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)

    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (270, 0)

    alpha_node = nodes.new("ShaderNodeValue")
    alpha_node.location = (-240, 0)
    alpha_node.outputs[0].default_value = alpha

    # Fac: 0 -> Transparent, 1 -> Principled
    links.new(alpha_node.outputs[0], mix.inputs["Fac"])
    links.new(transparent.outputs[0], mix.inputs[1])
    links.new(principled.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])

    # Viewport preview
    mat.diffuse_color = (color_rgb[0], color_rgb[1], color_rgb[2], alpha)

    # Eevee transparency flags (safe to set; ignored by Cycles if irrelevant)
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


def create_object(name: str, mesh: Union[bpy.types.Mesh, None], collection: bpy.types.Collection) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


# ----------------------------
# Primitive mesh builders (unit shapes)
# ----------------------------

def create_unit_cylinder_mesh(name: str, sides: int, cap_ends: bool = True) -> bpy.types.Mesh:
    """
    Cylinder centered at origin, aligned to +Z/-Z, with:
      - radius = 1
      - half-length = 1 (total length = 2)
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

    # Caps (tri fan)
    if cap_ends and bottom_center is not None and top_center is not None:
        for j in range(sides):
            # top cap points outward (+Z)
            faces.append((top_center, top_ring[j], top_ring[(j + 1) % sides]))
            # bottom cap points outward (-Z)
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

    # Rings between poles: i = 1..rcount-1
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

    # Middle quads split into triangles
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


# ----------------------------
# Topology generators
# ----------------------------

def normalize_to_radius(v: Vector, radius: float) -> Vector:
    if v.length <= 1e-12:
        return v.copy()
    return v.normalized() * float(radius)


def icosahedron_topology(radius: float) -> Tuple[List[Vector], List[Tuple[int, int, int]]]:
    """
    12 vertices, 20 triangular faces, vertices on sphere of given radius.
    """
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
    verts = [normalize_to_radius(v, radius) for v in verts]

    faces = [
        (0, 11, 5),
        (0, 5, 1),
        (0, 1, 7),
        (0, 7, 10),
        (0, 10, 11),
        (1, 5, 9),
        (5, 11, 4),
        (11, 10, 2),
        (10, 7, 6),
        (7, 1, 8),
        (3, 9, 4),
        (3, 4, 2),
        (3, 2, 6),
        (3, 6, 8),
        (3, 8, 9),
        (4, 9, 5),
        (2, 4, 11),
        (6, 2, 10),
        (8, 6, 7),
        (9, 8, 1),
    ]
    return verts, faces


def icosphere_topology(radius: float, subdivisions: int) -> Tuple[List[Vector], List[Tuple[int, int, int]]]:
    """
    Icosphere generated by subdividing an icosahedron and projecting to sphere.
    subdivisions:
      0 => icosahedron
      1 => split each triangle into 4
      2 => split again, etc.
    """
    subdivisions = max(0, int(subdivisions))
    verts, faces = icosahedron_topology(radius=radius)

    # Midpoint cache: key=(min_i,max_i) => new_index
    midpoint_cache: Dict[Tuple[int, int], int] = {}

    def midpoint(i: int, j: int) -> int:
        key = (i, j) if i < j else (j, i)
        if key in midpoint_cache:
            return midpoint_cache[key]
        v = (verts[i] + verts[j]) * 0.5
        v = normalize_to_radius(v, radius)
        verts.append(v)
        idx = len(verts) - 1
        midpoint_cache[key] = idx
        return idx

    for _ in range(subdivisions):
        new_faces: List[Tuple[int, int, int]] = []
        midpoint_cache.clear()
        for (a, b, c) in faces:
            ab = midpoint(a, b)
            bc = midpoint(b, c)
            ca = midpoint(c, a)
            new_faces.extend([
                (a, ab, ca),
                (b, bc, ab),
                (c, ca, bc),
                (ab, bc, ca),
            ])
        faces = new_faces

    return verts, faces


def tetrahedron_topology(radius: float) -> Tuple[List[Vector], List[Tuple[int, int, int]]]:
    # Regular tetra vertices as opposite corners of a cube.
    base = [
        Vector(( 1.0,  1.0,  1.0)),
        Vector(( 1.0, -1.0, -1.0)),
        Vector((-1.0,  1.0, -1.0)),
        Vector((-1.0, -1.0,  1.0)),
    ]
    verts = [normalize_to_radius(v, radius) for v in base]
    faces = [
        (0, 2, 1),
        (0, 1, 3),
        (0, 3, 2),
        (1, 2, 3),
    ]
    return verts, faces


def octahedron_topology(radius: float) -> Tuple[List[Vector], List[Tuple[int, int, int]]]:
    base = [
        Vector(( 1.0, 0.0, 0.0)),
        Vector((-1.0, 0.0, 0.0)),
        Vector((0.0,  1.0, 0.0)),
        Vector((0.0, -1.0, 0.0)),
        Vector((0.0, 0.0,  1.0)),
        Vector((0.0, 0.0, -1.0)),
    ]
    verts = [normalize_to_radius(v, radius) for v in base]
    faces = [
        (0, 2, 4),
        (2, 1, 4),
        (1, 3, 4),
        (3, 0, 4),
        (2, 0, 5),
        (1, 2, 5),
        (3, 1, 5),
        (0, 3, 5),
    ]
    return verts, faces


def cube_topology(radius: float) -> Tuple[List[Vector], List[Tuple[int, ...]]]:
    # Vertices of cube with circumradius 1 are at (±1,±1,±1)/sqrt(3)
    s = float(radius) / math.sqrt(3.0)
    verts = [
        Vector((-s, -s, -s)),  # 0
        Vector(( s, -s, -s)),  # 1
        Vector(( s,  s, -s)),  # 2
        Vector((-s,  s, -s)),  # 3
        Vector((-s, -s,  s)),  # 4
        Vector(( s, -s,  s)),  # 5
        Vector(( s,  s,  s)),  # 6
        Vector((-s,  s,  s)),  # 7
    ]
    faces = [
        (0, 1, 2, 3),  # -Z
        (4, 5, 6, 7),  # +Z
        (0, 4, 5, 1),  # -Y
        (1, 5, 6, 2),  # +X
        (2, 6, 7, 3),  # +Y
        (3, 7, 4, 0),  # -X
    ]
    return verts, faces


def face_normal(verts: List[Vector], face: Sequence[int]) -> Vector:
    if len(face) < 3:
        return Vector((0.0, 0.0, 0.0))
    a, b, c = verts[face[0]], verts[face[1]], verts[face[2]]
    n = (b - a).cross(c - a)
    if n.length <= 1e-12:
        return n
    # Ensure outward for convex poly centered at origin
    centroid = Vector((0.0, 0.0, 0.0))
    for idx in face:
        centroid += verts[idx]
    centroid /= float(len(face))
    if n.dot(centroid) < 0.0:
        n = -n
    return n.normalized()


def dodecahedron_topology(radius: float) -> Tuple[List[Vector], List[Tuple[int, ...]]]:
    """
    Build a regular dodecahedron as the dual of an icosahedron:
      - dodeca vertices = outward face normals of icosahedron (scaled to radius)
      - dodeca faces = for each icosa vertex, the 5 incident face-normals ordered around that vertex
    """
    ico_verts, ico_faces = icosahedron_topology(radius=1.0)

    # Dodeca vertices: one per icosa face
    dodeca_verts: List[Vector] = []
    for f in ico_faces:
        n = face_normal(ico_verts, f)
        dodeca_verts.append(n * float(radius))

    # Build adjacency: icosa vertex -> list of face indices that include it
    incident_faces: List[List[int]] = [[] for _ in range(len(ico_verts))]
    for fi, f in enumerate(ico_faces):
        for vi in f:
            incident_faces[vi].append(fi)

    dodeca_faces: List[Tuple[int, ...]] = []

    for vi, face_ids in enumerate(incident_faces):
        # Should be 5 for an icosahedron vertex
        if len(face_ids) < 3:
            continue

        axis = ico_verts[vi].normalized()

        # Build local 2D basis (u,v) perpendicular to axis
        tmp = Vector((0.0, 0.0, 1.0))
        if abs(axis.dot(tmp)) > 0.9:
            tmp = Vector((0.0, 1.0, 0.0))
        u = axis.cross(tmp)
        if u.length <= 1e-12:
            tmp = Vector((1.0, 0.0, 0.0))
            u = axis.cross(tmp)
        u.normalize()
        v = axis.cross(u)
        v.normalize()

        # Sort the 5 dodeca vertices around axis by angle in the perpendicular plane
        def angle_for_face(fi: int) -> float:
            p = dodeca_verts[fi]
            # project onto plane perpendicular to axis
            q = p - axis * p.dot(axis)
            return math.atan2(q.dot(v), q.dot(u))

        ordered = sorted(face_ids, key=angle_for_face)
        dodeca_faces.append(tuple(ordered))

    return dodeca_verts, dodeca_faces


def topology_from_shape(shape_cfg: Dict[str, Any], radius: float) -> Tuple[List[Vector], List[Tuple[int, ...]]]:
    stype = str(shape_cfg.get("type", "icosahedron")).lower()
    subdivisions = int(shape_cfg.get("subdivisions", 0))

    if stype in {"icosahedron", "ico"}:
        v, f = icosahedron_topology(radius=radius)
        return v, [tuple(face) for face in f]
    if stype in {"icosphere"}:
        v, f = icosphere_topology(radius=radius, subdivisions=subdivisions)
        return v, [tuple(face) for face in f]
    if stype in {"tetrahedron", "tetra"}:
        v, f = tetrahedron_topology(radius=radius)
        return v, [tuple(face) for face in f]
    if stype in {"octahedron", "octa"}:
        v, f = octahedron_topology(radius=radius)
        return v, [tuple(face) for face in f]
    if stype in {"cube", "hexahedron"}:
        v, f = cube_topology(radius=radius)
        return v, [tuple(face) for face in f]
    if stype in {"dodecahedron", "dodeca"}:
        v, f = dodecahedron_topology(radius=radius)
        return v, [tuple(face) for face in f]

    raise ValueError(f"Unknown shape.type '{stype}'")


# ----------------------------
# Boundary builder
# ----------------------------

def unique_edges_from_faces(faces: List[Tuple[int, ...]]) -> List[Tuple[int, int]]:
    edges = set()
    for face in faces:
        n = len(face)
        if n < 2:
            continue
        for i in range(n):
            a = int(face[i])
            b = int(face[(i + 1) % n])
            key = (a, b) if a < b else (b, a)
            edges.add(key)
    return sorted(edges)


def build_edge_objects(
    name_prefix: str,
    verts: List[Vector],
    faces: List[Tuple[int, ...]],
    edge_radius: float,
    edge_sides: int,
    mat_edges: bpy.types.Material,
    collection: bpy.types.Collection,
    parent: bpy.types.Object,
):
    cyl_mesh = create_unit_cylinder_mesh(f"{name_prefix}_EdgeCylinderMesh", sides=edge_sides, cap_ends=True)
    set_mesh_material(cyl_mesh, mat_edges)

    z_axis = Vector((0.0, 0.0, 1.0))

    for i, j in unique_edges_from_faces(faces):
        v1 = verts[i]
        v2 = verts[j]
        d = v2 - v1
        length = d.length
        if length <= 1e-9:
            continue

        mid = (v1 + v2) * 0.5
        dir_n = d.normalized()

        obj = create_object(f"{name_prefix}_Edge_{i:04d}_{j:04d}", cyl_mesh, collection)
        obj.location = (mid.x, mid.y, mid.z)
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = z_axis.rotation_difference(dir_n)
        obj.scale = (float(edge_radius), float(edge_radius), float(length) / 2.0)

        obj.parent = parent
        obj.matrix_parent_inverse = parent.matrix_world.inverted()


def build_vertex_objects(
    name_prefix: str,
    verts: List[Vector],
    vertex_radius: float,
    sphere_segments: int,
    sphere_rings: int,
    mat_verts: bpy.types.Material,
    collection: bpy.types.Collection,
    parent: bpy.types.Object,
):
    sph_mesh = create_unit_uv_sphere_mesh(f"{name_prefix}_VertexSphereMesh", segments=sphere_segments, rings=sphere_rings)
    set_mesh_material(sph_mesh, mat_verts)

    for idx, v in enumerate(verts):
        obj = create_object(f"{name_prefix}_Vertex_{idx:04d}", sph_mesh, collection)
        obj.location = (v.x, v.y, v.z)
        obj.scale = (float(vertex_radius), float(vertex_radius), float(vertex_radius))

        obj.parent = parent
        obj.matrix_parent_inverse = parent.matrix_world.inverted()


def build_face_plates(
    name_prefix: str,
    verts: List[Vector],
    faces: List[Tuple[int, ...]],
    thickness: float,
    mat_faces: bpy.types.Material,
    face_alpha: float,
    collection: bpy.types.Collection,
    parent: bpy.types.Object,
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(f"{name_prefix}_FacePlatesMesh")

    plate_verts: List[Tuple[float, float, float]] = []
    plate_faces: List[Tuple[int, ...]] = []

    for face in faces:
        if len(face) < 3:
            continue
        base = len(plate_verts)
        for idx in face:
            v = verts[int(idx)]
            plate_verts.append((v.x, v.y, v.z))
        plate_faces.append(tuple(base + i for i in range(len(face))))

    mesh.from_pydata(plate_verts, [], plate_faces)
    mesh.update()

    smooth_shade_mesh(mesh, False)
    set_mesh_material(mesh, mat_faces)

    obj = create_object(f"{name_prefix}_FacePlates", mesh, collection)
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted()

    # If invisible or thickness == 0 => hide entirely for clean wireframe
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


def create_boundary_root_empty(name: str, collection: bpy.types.Collection) -> bpy.types.Object:
    root = bpy.data.objects.new(name, None)
    # Some Blender versions expose these fields; safe to guard
    if hasattr(root, "empty_display_type"):
        root.empty_display_type = "PLAIN_AXES"
    if hasattr(root, "empty_display_size"):
        root.empty_display_size = 0.5
    collection.objects.link(root)
    return root


def apply_transform(obj: bpy.types.Object, transform_cfg: Dict[str, Any]):
    loc = transform_cfg.get("location", [0.0, 0.0, 0.0])
    rot_deg = transform_cfg.get("rotation_deg", transform_cfg.get("rotation_euler_deg", [0.0, 0.0, 0.0]))
    scale = transform_cfg.get("scale", [1.0, 1.0, 1.0])

    obj.location = (float(loc[0]), float(loc[1]), float(loc[2]))
    obj.rotation_euler = (
        math.radians(float(rot_deg[0])),
        math.radians(float(rot_deg[1])),
        math.radians(float(rot_deg[2])),
    )
    obj.scale = (float(scale[0]), float(scale[1]), float(scale[2]))


def build_boundary_object(obj_cfg: Dict[str, Any], parent_collection: bpy.types.Collection) -> Dict[str, Any]:
    """
    Build a 'boundary' object and return metadata:
      { "root": <empty>, "verts": [...], "faces": [...], "extent": float }
    """
    name = str(obj_cfg.get("name", "boundary"))
    radius = float(obj_cfg.get("radius", 1.0))

    shape_cfg = obj_cfg.get("shape", {}) if isinstance(obj_cfg.get("shape", {}), dict) else {}
    verts, faces = topology_from_shape(shape_cfg, radius=radius)

    # Allow misspelling "verticies" as alias
    edges_cfg = obj_cfg.get("edges", {}) if isinstance(obj_cfg.get("edges", {}), dict) else {}
    vertices_cfg = obj_cfg.get("vertices", obj_cfg.get("verticies", {}))
    vertices_cfg = vertices_cfg if isinstance(vertices_cfg, dict) else {}
    faces_cfg = obj_cfg.get("faces", {}) if isinstance(obj_cfg.get("faces", {}), dict) else {}
    detail_cfg = obj_cfg.get("detail", obj_cfg.get("details", {}))
    detail_cfg = detail_cfg if isinstance(detail_cfg, dict) else {}

    edge_radius = float(edges_cfg.get("radius", 0.05))
    edge_color = parse_color_rgb(edges_cfg.get("color"), default=(0.0, 1.0, 0.4))
    edge_alpha = clamp01(edges_cfg.get("alpha", 1.0))

    vertex_radius = float(vertices_cfg.get("radius", 0.08))
    vertex_color = parse_color_rgb(vertices_cfg.get("color"), default=(1.0, 0.0, 1.0))
    vertex_alpha = clamp01(vertices_cfg.get("alpha", 1.0))

    face_thickness = float(faces_cfg.get("thickness", 0.03))
    face_color = parse_color_rgb(faces_cfg.get("color"), default=(0.0, 1.0, 1.0))
    face_alpha = clamp01(faces_cfg.get("alpha", 0.10))

    edge_sides = int(detail_cfg.get("edge_cylinder_sides", 24))
    sphere_segs = int(detail_cfg.get("vertex_sphere_segments", 32))
    sphere_rings = int(detail_cfg.get("vertex_sphere_rings", 16))

    # Create a dedicated collection for this object
    obj_coll = ensure_collection(name, parent_collection)

    # Root Empty (parents all parts)
    root = create_boundary_root_empty(name, obj_coll)

    # Materials (per-boundary so future objects can have different materials)
    mat_edges = make_transparent_material(f"{name}_Mat_Edges", edge_color, edge_alpha, roughness=0.25)
    mat_verts = make_transparent_material(f"{name}_Mat_Vertices", vertex_color, vertex_alpha, roughness=0.20)
    mat_faces = make_transparent_material(f"{name}_Mat_Faces", face_color, face_alpha, roughness=0.45)

    # Build geometry (local space around origin), parent under root
    build_edge_objects(name, verts, faces, edge_radius=edge_radius, edge_sides=edge_sides,
                       mat_edges=mat_edges, collection=obj_coll, parent=root)
    build_vertex_objects(name, verts, vertex_radius=vertex_radius, sphere_segments=sphere_segs, sphere_rings=sphere_rings,
                         mat_verts=mat_verts, collection=obj_coll, parent=root)
    build_face_plates(name, verts, faces, thickness=face_thickness, mat_faces=mat_faces, face_alpha=face_alpha,
                      collection=obj_coll, parent=root)

    # Apply object transform after parenting so it moves as a unit
    transform_cfg = obj_cfg.get("transform", {}) if isinstance(obj_cfg.get("transform", {}), dict) else {}
    apply_transform(root, transform_cfg)

    extent = radius + max(edge_radius, vertex_radius) * 3.0 + max(0.0, face_thickness) * 1.5

    return {
        "root": root,
        "verts": verts,
        "faces": faces,
        "extent": extent,
        "name": name,
    }


# ----------------------------
# Camera selection (non-symmetric default)
# ----------------------------

def compute_axes_for_symmetry_avoidance(verts: List[Vector], faces: List[Tuple[int, ...]]) -> List[Vector]:
    axes: List[Vector] = []

    # vertex axes
    for v in verts:
        if v.length > 1e-9:
            axes.append(v.normalized())

    # face normal axes
    for f in faces:
        n = face_normal(verts, f)
        if n.length > 1e-9:
            axes.append(n)

    # edge midpoint axes
    for i, j in unique_edges_from_faces(faces):
        m = (verts[i] + verts[j]) * 0.5
        if m.length > 1e-9:
            axes.append(m.normalized())

    # Deduplicate roughly
    uniq: List[Vector] = []
    for a in axes:
        keep = True
        for b in uniq:
            if abs(a.dot(b)) > 0.999:  # almost same axis (or opposite)
                keep = False
                break
        if keep:
            uniq.append(a)
    return uniq


def fibonacci_sphere(n: int) -> List[Vector]:
    # Deterministic distribution of points on sphere
    n = max(1, int(n))
    points: List[Vector] = []
    golden = (1.0 + math.sqrt(5.0)) / 2.0
    for i in range(n):
        t = (i + 0.5) / n
        z = 1.0 - 2.0 * t
        r = math.sqrt(max(0.0, 1.0 - z * z))
        phi = 2.0 * math.pi * i / golden
        x = r * math.cos(phi)
        y = r * math.sin(phi)
        points.append(Vector((x, y, z)))
    return points


def projected_vertex_separation(verts: List[Vector], view_dir: Vector) -> float:
    """
    Compute minimum pairwise distance between projected vertex points
    on the plane perpendicular to view_dir.
    Larger means less overlap/clumping.
    """
    if len(verts) < 2:
        return 0.0

    d = view_dir.normalized()
    # Basis for plane
    tmp = Vector((0.0, 0.0, 1.0))
    if abs(d.dot(tmp)) > 0.9:
        tmp = Vector((0.0, 1.0, 0.0))
    u = d.cross(tmp)
    if u.length <= 1e-12:
        tmp = Vector((1.0, 0.0, 0.0))
        u = d.cross(tmp)
    u.normalize()
    v = d.cross(u)
    v.normalize()

    pts = []
    for p in verts:
        # projection of p onto plane basis
        pts.append((p.dot(u), p.dot(v)))

    min_dist2 = float("inf")
    for i in range(len(pts)):
        xi, yi = pts[i]
        for j in range(i + 1, len(pts)):
            xj, yj = pts[j]
            dx = xi - xj
            dy = yi - yj
            dist2 = dx * dx + dy * dy
            if dist2 < min_dist2:
                min_dist2 = dist2

    if min_dist2 == float("inf"):
        return 0.0
    return math.sqrt(min_dist2)


def choose_camera_direction(verts: List[Vector], faces: List[Tuple[int, ...]]) -> Vector:
    """
    Pick a camera direction that avoids aligning with major symmetry axes
    and reduces projected vertex overlap.
    """
    axes = compute_axes_for_symmetry_avoidance(verts, faces)
    candidates = fibonacci_sphere(600)

    best = None
    best_score = -1e9

    # Estimate model scale for normalizing projection score
    r_est = max((v.length for v in verts), default=1.0)
    r_est = max(r_est, 1e-6)

    for d in candidates:
        d = d.normalized()

        # 1) Avoid axes: maximize minimum angular distance
        # Use abs(dot) so both axis directions are avoided.
        max_abs_dot = 0.0
        for a in axes:
            ad = abs(d.dot(a))
            if ad > max_abs_dot:
                max_abs_dot = ad
        # Convert to an "angle-like" score: higher is better
        # abs(dot)=1 => aligned, abs(dot)=0 => 90 degrees
        axis_score = 1.0 - max_abs_dot  # in [0,1]

        # 2) Spread projected vertices
        sep = projected_vertex_separation(verts, d) / r_est  # normalize
        sep_score = sep  # typically 0..something small

        # Preferences: slightly favor "front-ish" and "above-ish"
        # (not required, but helps get a nice default)
        pref = 0.0
        if d.y < -0.15:
            pref += 0.05
        if d.z > 0.10:
            pref += 0.05
        if abs(d.x) > 0.10:
            pref += 0.02

        score = axis_score * 1.0 + sep_score * 0.25 + pref

        if score > best_score:
            best_score = score
            best = d

    return best if best is not None else Vector((0.4, -0.8, 0.4)).normalized()


# ----------------------------
# Camera / Light / Render config
# ----------------------------

def look_at(obj: bpy.types.Object, target=(0.0, 0.0, 0.0)):
    target_v = Vector(target)
    direction = target_v - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def disable_cycles_denoising_everywhere():
    # View layer denoise
    scn, _ = scene_and_root_collection()
    for vl in scn.view_layers:
        cy = getattr(vl, "cycles", None)
        if cy is not None:
            if hasattr(cy, "use_denoising"):
                cy.use_denoising = False
            if hasattr(cy, "denoising_store_passes"):
                cy.denoising_store_passes = False
            if hasattr(cy, "denoising_input_passes"):
                # leave as-is
                pass

    # Scene cycles denoise (some versions)
    if hasattr(scn, "cycles") and hasattr(scn.cycles, "use_denoising"):
        scn.cycles.use_denoising = False


def apply_render_settings(cfg: Dict[str, Any], project_root: str):
    scn, _ = scene_and_root_collection()
    r = scn.render
    rcfg = cfg.get("render", {}) if isinstance(cfg.get("render", {}), dict) else {}

    engine = str(rcfg.get("engine", "CYCLES")).upper()
    # Blender uses exact enum strings
    if engine in {"CYCLES", "BLENDER_EEVEE", "BLENDER_WORKBENCH"}:
        r.engine = engine
    else:
        r.engine = "CYCLES"

    r.resolution_x = int(rcfg.get("resolution_x", 1024))
    r.resolution_y = int(rcfg.get("resolution_y", 1024))
    r.resolution_percentage = 100

    file_format = str(rcfg.get("file_format", "PNG")).upper()
    r.image_settings.file_format = file_format
    if file_format == "PNG":
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

    # Samples
    samples = int(rcfg.get("samples", 256))
    if r.engine == "CYCLES" and hasattr(scn, "cycles"):
        scn.cycles.samples = samples
        # Optional cycles sub-config
        ccfg = rcfg.get("cycles", {}) if isinstance(rcfg.get("cycles", {}), dict) else {}

        if hasattr(scn.cycles, "use_adaptive_sampling") and "adaptive_sampling" in ccfg:
            scn.cycles.use_adaptive_sampling = bool(ccfg.get("adaptive_sampling"))
        if hasattr(scn.cycles, "adaptive_threshold") and "adaptive_threshold" in ccfg:
            scn.cycles.adaptive_threshold = float(ccfg.get("adaptive_threshold"))
        if hasattr(scn.cycles, "clamp_indirect") and "clamp_indirect" in ccfg:
            scn.cycles.clamp_indirect = float(ccfg.get("clamp_indirect"))
        if hasattr(scn.cycles, "max_bounces") and "max_bounces" in ccfg:
            scn.cycles.max_bounces = int(ccfg.get("max_bounces"))

    # Denoise setting (must be false for your build without OIDN)
    if bool(rcfg.get("denoise", False)):
        # User asked for denoise, but build may not support it; we will still disable
        # if the build can't do it to avoid crashing.
        pass
    disable_cycles_denoising_everywhere()


def create_camera(cfg: Dict[str, Any], extent: float, ref_verts: List[Vector], ref_faces: List[Tuple[int, ...]], collection: bpy.types.Collection):
    scn, _ = scene_and_root_collection()

    cam_cfg = cfg.get("camera", {}) if isinstance(cfg.get("camera", {}), dict) else {}
    target = cam_cfg.get("target", [0.0, 0.0, 0.0])
    target_v = Vector((float(target[0]), float(target[1]), float(target[2])))

    lens_mm = float(cam_cfg.get("lens_mm", 50.0))
    roll_deg = float(cam_cfg.get("roll_deg", 0.0))

    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = lens_mm
    cam_obj = bpy.data.objects.new("Camera", cam_data)
    collection.objects.link(cam_obj)

    # If user provides explicit location, use it
    if "location" in cam_cfg:
        loc = cam_cfg["location"]
        cam_obj.location = (float(loc[0]), float(loc[1]), float(loc[2]))
    # If user provides spherical angles, use them
    elif "azimuth_deg" in cam_cfg and "elevation_deg" in cam_cfg:
        dist = float(cam_cfg.get("distance", extent * 3.2))
        az = math.radians(float(cam_cfg.get("azimuth_deg")))
        el = math.radians(float(cam_cfg.get("elevation_deg")))
        x = math.cos(el) * math.cos(az)
        y = math.cos(el) * math.sin(az)
        z = math.sin(el)
        cam_obj.location = target_v + Vector((x, y, z)) * dist
    else:
        # Auto non-symmetric view
        dist = float(cam_cfg.get("distance", extent * 3.2))
        d = choose_camera_direction(ref_verts, ref_faces)
        cam_obj.location = target_v + d * dist

    look_at(cam_obj, (target_v.x, target_v.y, target_v.z))

    # Apply roll around camera's viewing axis
    if abs(roll_deg) > 1e-6:
        axis = (target_v - cam_obj.location).normalized()
        q = axis.rotation_difference(axis)  # identity-ish placeholder
        # Blender quaternion rotation: build a quaternion from axis+angle
        # mathutils.Quaternion(axis, angle)
        from mathutils import Quaternion
        roll_q = Quaternion(axis, math.radians(roll_deg))
        cam_obj.rotation_mode = "QUATERNION"
        cam_obj.rotation_quaternion = roll_q @ cam_obj.rotation_quaternion

    scn.camera = cam_obj
    return cam_obj


def create_light(cfg: Dict[str, Any], extent: float, collection: bpy.types.Collection):
    light_cfg = cfg.get("light", {}) if isinstance(cfg.get("light", {}), dict) else {}

    lt = str(light_cfg.get("type", "SUN")).upper()
    if lt not in {"SUN", "POINT", "SPOT", "AREA"}:
        lt = "SUN"

    energy = float(light_cfg.get("energy", 3.0))
    loc = light_cfg.get("location", [extent * 3.0, -extent * 3.0, extent * 4.0])

    light_data = bpy.data.lights.new("KeyLight", type=lt)
    light_data.energy = energy
    light_obj = bpy.data.objects.new("KeyLight", light_data)
    collection.objects.link(light_obj)

    light_obj.location = (float(loc[0]), float(loc[1]), float(loc[2]))
    look_at(light_obj, (0.0, 0.0, 0.0))
    return light_obj


def parse_objects_list(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Accept either:
      - cfg["objects"] as a list of objects
      - cfg["objects"] as a dict mapping names -> object cfg
    """
    objs = cfg.get("objects", [])
    if isinstance(objs, list):
        return [o for o in objs if isinstance(o, dict)]
    if isinstance(objs, dict):
        out = []
        for name, ocfg in objs.items():
            if not isinstance(ocfg, dict):
                continue
            merged = dict(ocfg)
            merged.setdefault("name", str(name))
            out.append(merged)
        return out
    return []


def safe_render_still():
    """
    Render with a defensive retry if a denoiser crashes (OIDN missing).
    """
    try:
        bpy.ops.render.render(write_still=True)
        return
    except RuntimeError as e:
        msg = str(e)
        if "OpenImageDenoiser" in msg or "OIDN" in msg:
            disable_cycles_denoising_everywhere()
            bpy.ops.render.render(write_still=True)
            return
        raise


def main():
    args = parse_args()
    manifest_path = os.path.abspath(args.manifest)
    project_root = os.getcwd()
    cfg = load_manifest(manifest_path)

    # Fresh scene
    clear_scene_data()
    scn, root_coll = scene_and_root_collection()

    # Build objects
    objects = parse_objects_list(cfg)
    if not objects:
        raise ValueError("manifest.json must contain a non-empty 'objects' list (or object map).")

    built: List[Dict[str, Any]] = []
    max_extent = 1.0
    ref_verts: List[Vector] = []
    ref_faces: List[Tuple[int, ...]] = []

    for o in objects:
        otype = str(o.get("type", "boundary")).lower()
        if otype == "boundary":
            info = build_boundary_object(o, parent_collection=root_coll)
            built.append(info)
            max_extent = max(max_extent, float(info.get("extent", 1.0)))
            # Use the first boundary as camera reference
            if not ref_verts:
                ref_verts = info["verts"]
                ref_faces = info["faces"]
        else:
            raise ValueError(f"Unsupported object type '{otype}' (only 'boundary' is implemented so far).")

    # Render settings and camera/light
    apply_render_settings(cfg, project_root=project_root)

    # Camera/light in root collection (not inside per-object collection)
    # Use camera reference topology if available, else fallback to a default direction
    if not ref_verts:
        ref_verts, ref_faces = icosahedron_topology(radius=1.0)

    create_camera(cfg, extent=max_extent, ref_verts=ref_verts, ref_faces=ref_faces, collection=root_coll)
    create_light(cfg, extent=max_extent, collection=root_coll)

    if args.render:
        safe_render_still()
        bpy.ops.wm.quit_blender()


if __name__ == "__main__":
    main()
