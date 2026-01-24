# scripts/setup_scene.py
#
# Builds an icosahedron "poster model" from a JSON manifest:
#   - cylinders for edges ("wires")
#   - spheres for vertices ("points")
#   - thick face plates for faces (optional via alpha/thickness)
#
# This version avoids relying on bpy.context.object and avoids mesh-add operators
# for geometry creation, so it works more reliably in headless / non-UI contexts.

import argparse
import json
import math
import os
import sys
from typing import Any, Dict, List, Sequence, Tuple

import bpy
from mathutils import Vector


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


def scene_collection():
    # In normal Blender runs, bpy.context.scene exists. As a fallback, use the first scene.
    scn = getattr(bpy.context, "scene", None) or (bpy.data.scenes[0] if bpy.data.scenes else None)
    if scn is None:
        raise RuntimeError("No Blender scene available.")
    return scn, scn.collection


def clear_scene_data():
    """
    Remove objects + data-blocks without relying on bpy.ops (more reliable in headless contexts).
    """
    # Unlink and delete all objects
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    # Remove common datablocks
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh, do_unlink=True)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat, do_unlink=True)
    for cam in list(bpy.data.cameras):
        bpy.data.cameras.remove(cam, do_unlink=True)
    for light in list(bpy.data.lights):
        bpy.data.lights.remove(light, do_unlink=True)


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
    out.location = (500, 0)

    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (0, -120)
    principled.inputs["Base Color"].default_value = (color_rgb[0], color_rgb[1], color_rgb[2], 1.0)
    principled.inputs["Roughness"].default_value = float(roughness)

    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (0, 120)
    transparent.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)

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


def create_object(name: str, mesh: bpy.types.Mesh, collection: bpy.types.Collection) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


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

    # Smooth shading for round look
    smooth_shade_mesh(mesh, True)
    return mesh


def create_unit_uv_sphere_mesh(name: str, segments: int, rings: int) -> bpy.types.Mesh:
    """
    UV sphere centered at origin with radius = 1.
    'segments' ~ longitude count, 'rings' ~ latitude segments (like Blender UI ring count).
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
        # i in [1, rcount-1]
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


def icosahedron_topology(radius: float) -> Tuple[List[Vector], List[Tuple[int, int, int]]]:
    """
    12 vertices, 20 triangular faces.
    Vertices are scaled to lie on a sphere of the given radius (circumradius).
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

    # Scale to desired circumradius
    base_len = verts[0].length
    if base_len <= 1e-9:
        scale = 1.0
    else:
        scale = float(radius) / base_len
    verts = [v * scale for v in verts]

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


def unique_edges(tri_faces: List[Tuple[int, int, int]]) -> List[Tuple[int, int]]:
    edges = set()
    for a, b, c in tri_faces:
        edges.add(tuple(sorted((a, b))))
        edges.add(tuple(sorted((b, c))))
        edges.add(tuple(sorted((c, a))))
    return sorted(edges)


def build_edge_objects(
    verts: List[Vector],
    tri_faces: List[Tuple[int, int, int]],
    edge_radius: float,
    edge_sides: int,
    mat_edges: bpy.types.Material,
    collection: bpy.types.Collection,
):
    # Shared mesh for all edge cylinders: unit cylinder (radius=1, half-length=1)
    cyl_mesh = create_unit_cylinder_mesh("EdgeCylinderMesh", sides=edge_sides, cap_ends=True)
    set_mesh_material(cyl_mesh, mat_edges)

    z_axis = Vector((0.0, 0.0, 1.0))

    for i, j in unique_edges(tri_faces):
        v1 = verts[i]
        v2 = verts[j]
        d = v2 - v1
        length = d.length
        if length <= 1e-9:
            continue

        mid = (v1 + v2) * 0.5
        dir_n = d.normalized()

        obj = create_object(f"Edge_{i:02d}_{j:02d}", cyl_mesh, collection)
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
    # Shared mesh for all vertex spheres: unit UV sphere (radius=1)
    sph_mesh = create_unit_uv_sphere_mesh(
        "VertexSphereMesh",
        segments=sphere_segments,
        rings=sphere_rings,
    )
    set_mesh_material(sph_mesh, mat_verts)

    for idx, v in enumerate(verts):
        obj = create_object(f"Vertex_{idx:02d}", sph_mesh, collection)
        obj.location = (v.x, v.y, v.z)
        obj.scale = (float(vertex_radius), float(vertex_radius), float(vertex_radius))


def build_face_plates(
    verts: List[Vector],
    tri_faces: List[Tuple[int, int, int]],
    thickness: float,
    mat_faces: bpy.types.Material,
    face_alpha: float,
    collection: bpy.types.Collection,
) -> bpy.types.Object:
    """
    Build a single object containing 20 separate triangles (no shared vertices).
    Solidify then makes each triangle a "plate" with thickness and rim walls.
    """
    mesh = bpy.data.meshes.new("FacePlatesMesh")

    plate_verts: List[Tuple[float, float, float]] = []
    plate_faces: List[Tuple[int, int, int]] = []

    for (a, b, c) in tri_faces:
        base = len(plate_verts)
        va, vb, vc = verts[a], verts[b], verts[c]
        plate_verts.extend([(va.x, va.y, va.z), (vb.x, vb.y, vb.z), (vc.x, vc.y, vc.z)])
        plate_faces.append((base, base + 1, base + 2))

    mesh.from_pydata(plate_verts, [], plate_faces)
    mesh.update()

    # Flat shading looks "faceted" like plates
    smooth_shade_mesh(mesh, False)
    set_mesh_material(mesh, mat_faces)

    obj = create_object("FacePlates", mesh, collection)

    # Wireframe mode: hide plates entirely
    if face_alpha <= 0.0 or thickness <= 0.0:
        obj.hide_viewport = True
        obj.hide_render = True
        return obj

    mod = obj.modifiers.new(name="Solidify", type="SOLIDIFY")
    mod.thickness = float(thickness)
    mod.offset = 0.0  # centered thickness
    if hasattr(mod, "use_even_offset"):
        mod.use_even_offset = True
    if hasattr(mod, "use_rim"):
        mod.use_rim = True

    return obj


def look_at(obj: bpy.types.Object, target=(0.0, 0.0, 0.0)):
    target_v = Vector(target)
    direction = target_v - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def create_camera(distance: float, height: float, lens_mm: float, collection: bpy.types.Collection) -> bpy.types.Object:
    cam_data = bpy.data.cameras.new("Camera")
    cam_obj = bpy.data.objects.new("Camera", cam_data)
    collection.objects.link(cam_obj)

    cam_obj.location = (0.0, -float(distance), float(height))
    cam_data.lens = float(lens_mm)

    look_at(cam_obj, (0.0, 0.0, 0.0))
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


def apply_render_settings(cfg: dict, project_root: str):
    scn, _ = scene_collection()
    r = scn.render
    rcfg = cfg.get("render", {}) if isinstance(cfg.get("render", {}), dict) else {}

    engine = str(rcfg.get("engine", "CYCLES"))
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

    if engine.upper() == "CYCLES" and hasattr(scn, "cycles"):
        scn.cycles.samples = int(rcfg.get("samples", 64))


def main():
    args = parse_args()
    manifest_path = os.path.abspath(args.manifest)
    project_root = os.getcwd()

    cfg = load_manifest(manifest_path)

    # Core size
    ico_radius = float(cfg.get("radius", 1.0))

    edges_cfg = cfg.get("edges", {}) if isinstance(cfg.get("edges", {}), dict) else {}
    verts_cfg = cfg.get("vertices", {}) if isinstance(cfg.get("vertices", {}), dict) else {}
    faces_cfg = cfg.get("faces", {}) if isinstance(cfg.get("faces", {}), dict) else {}
    detail_cfg = cfg.get("detail", {}) if isinstance(cfg.get("detail", {}), dict) else {}

    edge_radius = float(edges_cfg.get("radius", 0.05))
    edge_color = parse_color_rgb(edges_cfg.get("color"), default=(1.0, 1.0, 1.0))
    edge_alpha = clamp01(edges_cfg.get("alpha", 1.0))

    vertex_radius = float(verts_cfg.get("radius", 0.08))
    vertex_color = parse_color_rgb(verts_cfg.get("color"), default=(1.0, 0.2, 0.2))
    vertex_alpha = clamp01(verts_cfg.get("alpha", 1.0))

    face_thickness = float(faces_cfg.get("thickness", 0.03))
    face_color = parse_color_rgb(faces_cfg.get("color"), default=(0.2, 0.6, 1.0))
    face_alpha = clamp01(faces_cfg.get("alpha", 0.12))

    edge_sides = int(detail_cfg.get("edge_cylinder_sides", 24))
    sphere_segs = int(detail_cfg.get("vertex_sphere_segments", 32))
    sphere_rings = int(detail_cfg.get("vertex_sphere_rings", 16))

    # Clear everything
    clear_scene_data()
    scn, coll = scene_collection()

    # Materials
    mat_edges = make_transparent_material("Mat_Edges", edge_color, edge_alpha, roughness=0.25)
    mat_verts = make_transparent_material("Mat_Vertices", vertex_color, vertex_alpha, roughness=0.20)
    mat_faces = make_transparent_material("Mat_Faces", face_color, face_alpha, roughness=0.45)

    # Icosahedron topology (math, no operators)
    verts, tri_faces = icosahedron_topology(radius=ico_radius)

    # Geometry
    build_edge_objects(verts, tri_faces, edge_radius=edge_radius, edge_sides=edge_sides, mat_edges=mat_edges, collection=coll)
    build_vertex_objects(verts, vertex_radius=vertex_radius, sphere_segments=sphere_segs, sphere_rings=sphere_rings, mat_verts=mat_verts, collection=coll)
    build_face_plates(verts, tri_faces, thickness=face_thickness, mat_faces=mat_faces, face_alpha=face_alpha, collection=coll)

    # Camera/light defaults based on model extent
    extent = ico_radius + max(edge_radius, vertex_radius) * 3.0
    camera_cfg = cfg.get("camera", {}) if isinstance(cfg.get("camera", {}), dict) else {}
    light_cfg = cfg.get("light", {}) if isinstance(cfg.get("light", {}), dict) else {}

    cam_distance = float(camera_cfg.get("distance", extent * 3.2))
    cam_height = float(camera_cfg.get("height", extent * 1.2))
    cam_lens = float(camera_cfg.get("lens_mm", 50.0))

    light_type = str(light_cfg.get("type", "SUN"))
    light_energy = float(light_cfg.get("energy", 3.0))
    light_loc = light_cfg.get("location", [extent * 3.0, -extent * 3.0, extent * 4.0])

    create_camera(distance=cam_distance, height=cam_height, lens_mm=cam_lens, collection=coll)
    create_light(light_type=light_type, energy=light_energy, location=light_loc, collection=coll)

    apply_render_settings(cfg, project_root=project_root)

    if args.render:
        bpy.ops.render.render(write_still=True)
        bpy.ops.wm.quit_blender()


if __name__ == "__main__":
    main()
