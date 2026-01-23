bl_info = {
    "name": "MBM Manifest Importer",
    "author": "OpenAI (generated)",
    "version": (0, 1, 0),
    "blender": (4, 1, 0),
    "location": "View3D > Sidebar > MBM",
    "description": "Import an MBM render manifest JSON and build a ready-to-render scene (wireframe polyhedron + rays + endcap assets).",
    "category": "Import-Export",
}

import bpy
import bmesh
import json
import os
import math
from mathutils import Vector, Matrix

# -------------------------
# Utility
# -------------------------

def _hex_to_rgba(hex_str, alpha=1.0):
    if not hex_str:
        return (1.0, 1.0, 1.0, alpha)
    s = hex_str.strip()
    if s.startswith("#"):
        s = s[1:]
    if len(s) == 3:
        s = "".join([c*2 for c in s])
    r = int(s[0:2], 16) / 255.0
    g = int(s[2:4], 16) / 255.0
    b = int(s[4:6], 16) / 255.0
    return (r, g, b, alpha)

def _ensure_collection(name, parent=None):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(col)
    return col

def _clear_mbm_collections():
    # Remove objects in collections starting with "MBM_"
    scene = bpy.context.scene
    mbm_cols = [c for c in bpy.data.collections if c.name.startswith("MBM_")]
    mbm_objs = set()
    for c in mbm_cols:
        for o in c.objects:
            mbm_objs.add(o)
    for o in mbm_objs:
        bpy.data.objects.remove(o, do_unlink=True)
    for c in mbm_cols:
        bpy.data.collections.remove(c)

def _ensure_material(name, color_rgba=(1,1,1,1), emission=False, emission_strength=1.0, use_alpha=False):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links

    # clear nodes
    for n in list(nodes):
        nodes.remove(n)

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)

    if emission:
        em = nodes.new("ShaderNodeEmission")
        em.location = (0, 0)
        em.inputs["Color"].default_value = color_rgba
        em.inputs["Strength"].default_value = emission_strength
        links.new(em.outputs["Emission"], out.inputs["Surface"])
    else:
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (0, 0)
        bsdf.inputs["Base Color"].default_value = color_rgba
        bsdf.inputs["Roughness"].default_value = 0.4
        bsdf.inputs["Metallic"].default_value = 0.0
        if use_alpha:
            bsdf.inputs["Alpha"].default_value = color_rgba[3]
            mat.blend_method = 'BLEND'
            mat.shadow_method = 'HASHED'
        links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    # Disable backface culling for readability
    mat.use_backface_culling = False
    return mat

def _ensure_image_material(name, image_path, fallback_color=(1,1,1,1), emission_strength=1.0):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links

    for n in list(nodes):
        nodes.remove(n)

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)

    em = nodes.new("ShaderNodeEmission")
    em.location = (350, 0)
    em.inputs["Strength"].default_value = emission_strength

    tex = nodes.new("ShaderNodeTexImage")
    tex.location = (0, 0)

    img = None
    if image_path and os.path.exists(image_path):
        try:
            img = bpy.data.images.load(image_path, check_existing=True)
        except Exception:
            img = None
    if img is None:
        tex.image = None
        em.inputs["Color"].default_value = fallback_color
    else:
        tex.image = img
        links.new(tex.outputs["Color"], em.inputs["Color"])

    links.new(em.outputs["Emission"], out.inputs["Surface"])

    mat.use_backface_culling = False
    return mat

def _new_mesh_object(name, bm, collection, material=None):
    mesh = bpy.data.meshes.new(name + "_mesh")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    if material is not None:
        if obj.data.materials:
            obj.data.materials[0] = material
        else:
            obj.data.materials.append(material)
    return obj

def _create_uv_sphere(name, radius, location, collection, material=None, segments=24, rings=12):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=radius)
    bm.transform(Matrix.Translation(Vector(location)))
    return _new_mesh_object(name, bm, collection, material)

def _create_cylinder_z(name, radius, depth, location, rotation_quat, collection, material=None, segments=24):
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=segments,
        radius1=radius,
        radius2=radius,
        depth=depth,
    )
    bm.transform(rotation_quat.to_matrix().to_4x4())
    bm.transform(Matrix.Translation(Vector(location)))
    return _new_mesh_object(name, bm, collection, material)

def _cylinder_between(name, p0, p1, radius, collection, material=None):
    p0 = Vector(p0); p1 = Vector(p1)
    d = p1 - p0
    length = d.length
    if length < 1e-9:
        return None
    direction = d.normalized()
    rot = Vector((0,0,1)).rotation_difference(direction)
    mid = (p0 + p1) * 0.5
    return _create_cylinder_z(name, radius, length, mid, rot, collection, material)

def _dashed_between(name_prefix, p0, p1, radius, dash_len, gap_len, collection, material=None):
    p0 = Vector(p0); p1 = Vector(p1)
    d = p1 - p0
    total = d.length
    if total < 1e-9:
        return []
    direction = d.normalized()
    # Build segments along the ray
    segs = []
    t = 0.0
    i = 0
    while t < total:
        seg_start = t
        seg_end = min(t + dash_len, total)
        if seg_end > seg_start + 1e-6:
            a = p0 + direction * seg_start
            b = p0 + direction * seg_end
            seg = _cylinder_between(f"{name_prefix}_dash_{i:02d}", a, b, radius, collection, material)
            if seg:
                segs.append(seg)
        t += dash_len + gap_len
        i += 1
    return segs

def _set_object_world_matrix(obj, origin, right, up, normal):
    # Build a right-handed basis so local X=right, Y=up, Z=normal
    rot3 = Matrix((right, up, normal)).transposed()
    mat = Matrix.Translation(Vector(origin)) @ rot3.to_4x4()
    obj.matrix_world = mat

def _project_onto_plane(v, n):
    # remove component along normal
    return v - n * v.dot(n)

# -------------------------
# Platonic solids (canonical)
# -------------------------

def _ico_vertices_faces():
    phi = (1.0 + 5.0 ** 0.5) / 2.0
    verts = [
        (0, +1, +phi),  # 0
        (0, +1, -phi),  # 1
        (0, -1, +phi),  # 2
        (0, -1, -phi),  # 3
        (+1, +phi, 0),  # 4
        (+1, -phi, 0),  # 5
        (-1, +phi, 0),  # 6
        (-1, -phi, 0),  # 7
        (+phi, 0, +1),  # 8
        (+phi, 0, -1),  # 9
        (-phi, 0, +1),  # 10
        (-phi, 0, -1),  # 11
    ]
    # Canonical faces from v0.2 context
    faces = [
        (0, 2, 8),
        (0, 10, 2),
        (0, 4, 6),
        (0, 8, 4),
        (0, 6, 10),
        (1, 9, 3),
        (1, 3, 11),
        (1, 6, 4),
        (1, 4, 9),
        (1, 11, 6),
        (2, 7, 5),
        (2, 5, 8),
        (2, 10, 7),
        (3, 5, 7),
        (3, 9, 5),
        (3, 7, 11),
        (4, 8, 9),
        (5, 9, 8),
        (6, 11, 10),
        (7, 10, 11),
    ]
    return verts, faces

def _dodeca_from_ico():
    ico_verts, ico_faces = _ico_vertices_faces()
    V = [Vector(v) for v in ico_verts]
    # Dodeca vertices are face centers of icosahedron faces
    dodeca_verts = []
    for f in ico_faces:
        c = (V[f[0]] + V[f[1]] + V[f[2]]) / 3.0
        dodeca_verts.append(c)

    # Dodeca faces correspond to each icosahedron vertex -> the 5 adjacent ico faces
    faces = []
    for vi in range(len(V)):
        adjacent = [fi for fi, f in enumerate(ico_faces) if vi in f]
        # should be 5
        axis = V[vi].normalized()
        # basis for sorting
        ref = Vector((0,0,1))
        if abs(ref.dot(axis)) > 0.9:
            ref = Vector((0,1,0))
        u = (ref - axis * ref.dot(axis)).normalized()
        w = axis.cross(u).normalized()

        def angle_for_face_center(face_idx):
            p = dodeca_verts[face_idx]
            p_perp = p - axis * p.dot(axis)
            x = p_perp.dot(u)
            y = p_perp.dot(w)
            return math.atan2(y, x)

        ordered = sorted(adjacent, key=angle_for_face_center)

        # Ensure outward orientation (normal roughly aligned with axis)
        # Compute face normal from first three points
        p0, p1, p2 = (dodeca_verts[ordered[0]], dodeca_verts[ordered[1]], dodeca_verts[ordered[2]])
        n = (p1 - p0).cross(p2 - p0)
        if n.dot(axis) < 0:
            ordered.reverse()

        faces.append(tuple(ordered))

    # Convert verts to tuples
    dodeca_verts = [tuple(v) for v in dodeca_verts]
    return dodeca_verts, faces

def _tetra_vertices_faces():
    verts = [
        (1, 1, 1),
        (1, -1, -1),
        (-1, 1, -1),
        (-1, -1, 1),
    ]
    faces = [
        (0, 2, 3),
        (0, 3, 1),
        (0, 1, 2),
        (1, 3, 2),
    ]
    return verts, faces

def _cube_vertices_faces():
    # canonical vertex order
    verts = [
        (-1, -1, -1),  # 0
        (-1, -1,  1),  # 1
        (-1,  1, -1),  # 2
        (-1,  1,  1),  # 3
        ( 1, -1, -1),  # 4
        ( 1, -1,  1),  # 5
        ( 1,  1, -1),  # 6
        ( 1,  1,  1),  # 7
    ]
    faces = [
        (0, 1, 3, 2),  # -X
        (4, 6, 7, 5),  # +X
        (0, 4, 5, 1),  # -Y
        (2, 3, 7, 6),  # +Y
        (0, 2, 6, 4),  # -Z
        (1, 5, 7, 3),  # +Z
    ]
    return verts, faces

def _octa_vertices_faces():
    verts = [
        ( 1, 0, 0),  # 0
        (-1, 0, 0),  # 1
        (0,  1, 0),  # 2
        (0, -1, 0),  # 3
        (0, 0,  1),  # 4
        (0, 0, -1),  # 5
    ]
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

def get_polyhedron(type_name):
    t = (type_name or "").lower()
    if t in ("icosahedron", "iscosahedron", "ico"):
        return _ico_vertices_faces()
    if t in ("dodecahedron", "dodeca", "dodec"):
        return _dodeca_from_ico()
    if t in ("tetrahedron", "tetra", "tet"):
        return _tetra_vertices_faces()
    if t in ("cube", "hexahedron"):
        return _cube_vertices_faces()
    if t in ("octahedron", "octa", "oct"):
        return _octa_vertices_faces()
    raise ValueError(f"Unsupported polyhedron type: {type_name}")

def _fix_face_orientation(verts, face):
    # Ensure face normal points outward (dot(normal, center) > 0)
    V = [Vector(verts[i]) for i in face]
    center = sum(V, Vector((0,0,0))) / len(V)
    n = (V[1] - V[0]).cross(V[2] - V[0])
    if n.dot(center) < 0:
        return tuple(reversed(face))
    return tuple(face)

def _compute_radii(verts, faces):
    V = [Vector(v) for v in verts]
    circum = max(v.length for v in V)
    # inradius from face planes
    inr = None
    for f in faces:
        f = _fix_face_orientation(verts, f)
        p0 = Vector(verts[f[0]])
        p1 = Vector(verts[f[1]])
        p2 = Vector(verts[f[2]])
        n = (p1 - p0).cross(p2 - p0)
        if n.length < 1e-9:
            continue
        n = n.normalized()
        d = abs(n.dot(p0))  # plane distance to origin
        inr = d if inr is None else min(inr, d)
    return circum, (inr or 0.0)

def _scale_polyhedron(verts, faces, radius_kind, radius_value):
    circum, inr = _compute_radii(verts, faces)
    cur = circum if radius_kind == "circumradius" else inr
    if cur <= 1e-9:
        return verts, 1.0
    s = radius_value / cur
    scaled = [tuple(Vector(v) * s) for v in verts]
    return scaled, s

def _edges_from_faces(faces):
    edges = set()
    for f in faces:
        n = len(f)
        for i in range(n):
            a = f[i]; b = f[(i+1) % n]
            edges.add(tuple(sorted((a,b))))
    return sorted(list(edges))

def _face_center_normal(verts, face):
    V = [Vector(verts[i]) for i in face]
    center = sum(V, Vector((0,0,0))) / len(V)
    n = (V[1] - V[0]).cross(V[2] - V[0])
    if n.length < 1e-9:
        n = center
    if n.length < 1e-9:
        n = Vector((0,0,1))
    n = n.normalized()
    if n.dot(center) < 0:
        n = -n
    return center, n

# -------------------------
# Camera / Lights
# -------------------------

def _ensure_camera(cam_cfg, collection):
    scene = bpy.context.scene
    cam_obj = None
    for o in bpy.data.objects:
        if o.type == 'CAMERA' and o.name.startswith("MBM_Camera"):
            cam_obj = o
            break
    if cam_obj is None:
        cam_data = bpy.data.cameras.new("MBM_CameraData")
        cam_obj = bpy.data.objects.new("MBM_Camera", cam_data)
        collection.objects.link(cam_obj)
    cam = cam_obj.data

    projection = (cam_cfg.get("projection") or "ORTHO").upper()
    cam.type = 'ORTHO' if projection == "ORTHO" else 'PERSP'

    if cam.type == 'ORTHO':
        cam.ortho_scale = float(cam_cfg.get("ortho_scale", 6.0))

    loc = cam_cfg.get("location", [3.0, -3.0, 2.2])
    look = cam_cfg.get("look_at", [0.0, 0.0, 0.0])
    cam_obj.location = Vector(loc)

    # Point camera at look_at
    target = Vector(look)
    direction = (target - cam_obj.location).normalized()
    # Camera looks along -Z local axis; align -Z to direction
    rot = Vector((0,0,-1)).rotation_difference(direction)
    cam_obj.rotation_mode = 'QUATERNION'
    cam_obj.rotation_quaternion = rot

    scene.camera = cam_obj
    return cam_obj

def _ensure_lights(mode, collection, cam_obj):
    # Simple 3-point: key, fill, rim (area lights)
    # Keep it minimal; user can tweak later.
    if mode != "simple_3point":
        return

    # Remove existing MBM lights
    for o in list(collection.objects):
        if o.type == 'LIGHT':
            bpy.data.objects.remove(o, do_unlink=True)

    def add_area(name, loc, power=500.0, size=2.0):
        data = bpy.data.lights.new(name, type='AREA')
        data.energy = power
        data.shape = 'SQUARE'
        data.size = size
        obj = bpy.data.objects.new(name, data)
        obj.location = Vector(loc)
        collection.objects.link(obj)
        return obj

    cam_loc = cam_obj.location
    # Key light: above/right of camera
    add_area("MBM_Light_Key", cam_loc + Vector((2.0, 2.0, 2.0)), power=800.0, size=3.0)
    # Fill: opposite side
    add_area("MBM_Light_Fill", cam_loc + Vector((-2.0, 1.5, 1.0)), power=300.0, size=4.0)
    # Rim: behind object
    add_area("MBM_Light_Rim", Vector((0.0, 3.5, 2.5)), power=250.0, size=4.0)

# -------------------------
# Endcap construction
# -------------------------

def _estimate_plane_size(assets, default=(0.8, 0.45)):
    # Simple heuristic; user can specify explicit sizes.
    # If image exists and loads, match its aspect.
    w, h = default
    for a in assets:
        if a.get("type") == "image" and a.get("file"):
            # Leave aspect correction to image loading stage; keep safe default here.
            pass
    return float(w), float(h)

def _create_endcap(ray_end, ray_dir, cam_obj, assets, plane_cfg, mats, collection, manifest_dir):
    ray_end = Vector(ray_end)
    ray_dir = Vector(ray_dir).normalized()

    cam_pos = cam_obj.location
    to_cam = cam_pos - ray_end

    n = ray_dir if to_cam.dot(ray_dir) > 0 else -ray_dir  # plane normal facing camera

    # Camera right/up vectors in world
    cam_right = cam_obj.matrix_world.to_3x3() @ Vector((1,0,0))
    cam_up = cam_obj.matrix_world.to_3x3() @ Vector((0,1,0))

    up_proj = _project_onto_plane(cam_up, n)
    if up_proj.length < 1e-6:
        up_proj = _project_onto_plane(cam_right, n)
    up = up_proj.normalized()
    right = (up.cross(n)).normalized()

    # Ensure non-mirrored orientation by matching camera-right projection
    right_proj = _project_onto_plane(cam_right, n)
    if right_proj.length > 1e-6 and right.dot(right_proj) < 0:
        right = -right
        up = -up

    size = plane_cfg.get("size") if plane_cfg else None
    if isinstance(size, (list, tuple)) and len(size) == 2:
        w, h = float(size[0]), float(size[1])
    else:
        w, h = _estimate_plane_size(assets, default=(0.8, 0.45))

    # Base plane (emissive white or emissive image)
    base_plane_mat = mats["plane_emission"]
    img_asset = next((a for a in assets if a.get("type") == "image"), None)
    if img_asset and img_asset.get("file"):
        img_path = img_asset.get("file")
        if not os.path.isabs(img_path):
            img_path = os.path.join(manifest_dir, img_path)
        base_plane_mat = _ensure_image_material("MBM_Mat_PlaneImage", img_path, fallback_color=mats["plane_color"], emission_strength=1.0)

    # Create plane mesh with UVs
    bm = bmesh.new()
    v0 = bm.verts.new((-w/2, -h/2, 0))
    v1 = bm.verts.new(( w/2, -h/2, 0))
    v2 = bm.verts.new(( w/2,  h/2, 0))
    v3 = bm.verts.new((-w/2,  h/2, 0))
    face = bm.faces.new((v0, v1, v2, v3))
    bm.faces.ensure_lookup_table()

    uv_layer = bm.loops.layers.uv.new("UVMap")
    uvs = [(0,0),(1,0),(1,1),(0,1)]
    for loop, uv in zip(face.loops, uvs):
        loop[uv_layer].uv = uv

    plane_obj = _new_mesh_object("MBM_EndcapPlane", bm, collection, base_plane_mat)
    _set_object_world_matrix(plane_obj, ray_end, right, up, n)

    # Small offset for content in front of plane
    z_off = float(plane_cfg.get("content_offset", 0.01)) if plane_cfg else 0.01

    # Text assets
    for a in assets:
        if a.get("type") != "text":
            continue
        txt = a.get("text", "")
        if not txt:
            continue
        size_txt = float(a.get("size", 0.18))
        extrude = float(a.get("extrude", 0.02))
        bevel = float(a.get("bevel", 0.0))

        curve = bpy.data.curves.new("MBM_TextCurve", type='FONT')
        curve.body = txt
        curve.size = size_txt
        curve.extrude = extrude
        curve.bevel_depth = bevel
        curve.align_x = a.get("align_x", "CENTER")
        curve.align_y = a.get("align_y", "CENTER")

        txt_obj = bpy.data.objects.new("MBM_Text", curve)
        collection.objects.link(txt_obj)

        # Material
        if curve.materials:
            curve.materials[0] = mats["text"]
        else:
            curve.materials.append(mats["text"])

        # Parent to plane and place slightly in front (local +Z is plane normal)
        txt_obj.parent = plane_obj
        txt_obj.matrix_parent_inverse = plane_obj.matrix_world.inverted()
        txt_obj.location = Vector((0.0, 0.0, z_off))
        txt_obj.rotation_mode = 'QUATERNION'
        txt_obj.rotation_quaternion = (0.0, 0.0, 0.0, 1.0)

    # Model assets
    for a in assets:
        if a.get("type") != "model":
            continue
        f = a.get("file")
        if not f:
            continue
        model_path = f if os.path.isabs(f) else os.path.join(manifest_dir, f)

        imported = _import_model_file(model_path)
        if not imported:
            continue

        # Parent + position near plane center
        for obj in imported:
            obj.parent = plane_obj
            obj.matrix_parent_inverse = plane_obj.matrix_world.inverted()
            obj.location = Vector((0.0, 0.0, z_off + float(a.get("offset_z", 0.08))))
            obj.rotation_mode = 'QUATERNION'
            obj.rotation_quaternion = (0.0, 0.0, 0.0, 1.0)

            # Optional fit-to-box
            fit = a.get("fit_max", None)
            if fit is not None:
                fit = float(fit)
                # compute current bounding box max dimension
                dims = obj.dimensions
                max_dim = max(dims.x, dims.y, dims.z, 1e-9)
                s = fit / max_dim
                obj.scale = Vector((s, s, s))

    return plane_obj

# -------------------------
# Model importers (STL / OBJ / FBX / GLTF / STEP optional)
# -------------------------

def _import_model_file(path):
    if not os.path.exists(path):
        print(f"[MBM] Model file not found: {path}")
        return []

    ext = os.path.splitext(path)[1].lower()
    before = set(bpy.data.objects)

    # Try new IO operators first (Blender 4.1+)
    try:
        if ext == ".stl":
            if hasattr(bpy.ops.wm, "stl_import"):
                bpy.ops.wm.stl_import(filepath=path)
            elif hasattr(bpy.ops.import_mesh, "stl"):
                bpy.ops.import_mesh.stl(filepath=path)
            else:
                print("[MBM] STL import operator not found (enable STL add-on if needed).")
                return []
        elif ext == ".obj":
            if hasattr(bpy.ops.wm, "obj_import"):
                bpy.ops.wm.obj_import(filepath=path)
            elif hasattr(bpy.ops.import_scene, "obj"):
                bpy.ops.import_scene.obj(filepath=path)
            else:
                print("[MBM] OBJ import operator not found.")
                return []
        elif ext == ".fbx":
            bpy.ops.import_scene.fbx(filepath=path)
        elif ext in (".glb", ".gltf"):
            bpy.ops.import_scene.gltf(filepath=path)
        elif ext in (".step", ".stp"):
            # STEP is not built-in in vanilla Blender; requires an add-on.
            # We try a few common operator names; otherwise skip with message.
            if hasattr(bpy.ops.import_scene, "step"):
                bpy.ops.import_scene.step(filepath=path)
            elif hasattr(bpy.ops.import_scene, "stp"):
                bpy.ops.import_scene.stp(filepath=path)
            else:
                print("[MBM] STEP import not available. Install a STEP importer add-on or convert to STL.")
                return []
        else:
            print(f"[MBM] Unsupported model format: {ext}")
            return []
    except Exception as e:
        print(f"[MBM] Import failed for {path}: {e}")
        return []

    after = set(bpy.data.objects)
    new_objs = list(after - before)
    # Filter only mesh objects for placement
    return [o for o in new_objs if o.type in {'MESH', 'CURVE', 'EMPTY'}]

# -------------------------
# Scene builder
# -------------------------

def build_scene_from_manifest(manifest_path, clear_existing=True):
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))

    if clear_existing:
        _clear_mbm_collections()

    col_root = _ensure_collection("MBM_Root")
    col_boundary = _ensure_collection("MBM_Boundary", parent=col_root)
    col_rays = _ensure_collection("MBM_Rays", parent=col_root)
    col_endcaps = _ensure_collection("MBM_Endcaps", parent=col_root)
    col_lights = _ensure_collection("MBM_Lights", parent=col_root)
    col_camera = _ensure_collection("MBM_Camera", parent=col_root)

    colors = (manifest.get("style", {}).get("colors", {}) or {})
    mat_boundary = _ensure_material("MBM_Mat_Boundary", _hex_to_rgba(colors.get("boundary", "#2B2F36")), emission=False)
    mat_power = _ensure_material("MBM_Mat_Power", _hex_to_rgba(colors.get("power", "#E07A1F")), emission=False)
    mat_info = _ensure_material("MBM_Mat_Info", _hex_to_rgba(colors.get("information", "#2A9D8F")), emission=False)
    mat_label = _ensure_material("MBM_Mat_Label", _hex_to_rgba(colors.get("label", "#6C757D")), emission=False)

    plane_color = _hex_to_rgba(colors.get("plane", "#FFFFFF"))
    mat_plane = _ensure_material("MBM_Mat_PlaneBase", plane_color, emission=False)
    mat_plane_em = _ensure_material("MBM_Mat_PlaneEmission", plane_color, emission=True, emission_strength=1.0)

    mat_text = _ensure_material("MBM_Mat_Text", _hex_to_rgba(colors.get("text", "#111111")), emission=False)

    mats = {
        "boundary": mat_boundary,
        "power": mat_power,
        "info": mat_info,
        "label": mat_label,
        "plane": mat_plane,
        "plane_emission": mat_plane_em,
        "plane_color": plane_color,
        "text": mat_text,
    }

    # Camera
    render_cfg = manifest.get("render", {}) or {}
    cam_cfg = render_cfg.get("camera", {}) or {}
    cam_obj = _ensure_camera(cam_cfg, col_camera)

    # Lights
    lights_mode = (render_cfg.get("lights", {}) or {}).get("mode", "simple_3point")
    _ensure_lights(lights_mode, col_lights, cam_obj)

    # Render output settings (minimal)
    output_cfg = render_cfg.get("output", {}) or {}
    scene = bpy.context.scene
    scene.render.resolution_x = int(output_cfg.get("width_px", 2000))
    scene.render.resolution_y = int(output_cfg.get("height_px", 1400))
    bg = (output_cfg.get("background") or "white").lower()
    scene.render.film_transparent = (bg == "transparent")

    engine = (render_cfg.get("engine") or "BLENDER_EEVEE").upper()
    if engine == "CYCLES":
        scene.render.engine = 'CYCLES'
    else:
        scene.render.engine = 'BLENDER_EEVEE'

    # Build boundary polyhedron
    boundary = manifest.get("boundary", {}) or {}
    poly = boundary.get("polyhedron", {}) or {}

    poly_type = poly.get("type", "icosahedron")
    radius_cfg = poly.get("radius", {}) or {}
    r_kind = (radius_cfg.get("kind") or "circumradius").lower()
    r_val = float(radius_cfg.get("value", 1.0))
    wire_radius = float(poly.get("wire_radius", 0.03))
    vertex_radius = float(poly.get("vertex_radius", wire_radius))

    verts, faces = get_polyhedron(poly_type)
    faces = [_fix_face_orientation(verts, f) for f in faces]
    verts, scale = _scale_polyhedron(verts, faces, r_kind, r_val)
    R_circum = max(Vector(v).length for v in verts)

    edges = _edges_from_faces(faces)

    # Parent empty for boundary
    empty_boundary = bpy.data.objects.new("MBM_Boundary_Empty", None)
    col_boundary.objects.link(empty_boundary)

    # Vertices
    vertex_objs = []
    for i, v in enumerate(verts):
        s = _create_uv_sphere(f"MBM_Vertex_{i:02d}", vertex_radius, v, col_boundary, mat_boundary)
        s.parent = empty_boundary
        vertex_objs.append(s)

    # Edges
    for ei, (a, b) in enumerate(edges):
        eobj = _cylinder_between(f"MBM_Edge_{ei:02d}", verts[a], verts[b], wire_radius, col_boundary, mat_boundary)
        if eobj:
            eobj.parent = empty_boundary

    # Ports (vertex rays)
    ports = boundary.get("ports", []) or []
    # Determine auto vertex assignment ordering by camera-facing score
    view_dir = (cam_obj.location - Vector((0,0,0))).normalized()
    vertex_order = sorted(range(len(verts)), key=lambda i: Vector(verts[i]).normalized().dot(view_dir), reverse=True)
    used_vertices = set()

    def alloc_vertex(preferred):
        if isinstance(preferred, int):
            return int(preferred)
        # "auto" or missing
        for vi in vertex_order:
            if vi not in used_vertices:
                used_vertices.add(vi)
                return vi
        return vertex_order[0] if vertex_order else 0

    for pi, p in enumerate(ports):
        flow = (p.get("flow") or "information").lower()
        vertex = p.get("vertex", "auto")
        vi = alloc_vertex(vertex)
        anchor = Vector(verts[vi])
        dir_vec = anchor.normalized()
        ray_cfg = p.get("ray", {}) or {}
        ray_len = ray_cfg.get("length", "auto")
        if ray_len == "auto":
            ray_len = 1.6 * R_circum
        else:
            ray_len = float(ray_len)
        ray_rad = float(ray_cfg.get("radius", 0.8 * wire_radius))

        # Start slightly outside the vertex sphere
        start = anchor + dir_vec * (vertex_radius * 0.9)
        end = anchor + dir_vec * ray_len

        # Material + style
        if flow == "power":
            mat = mats["power"]
            dashed = False
        elif flow == "information":
            mat = mats["info"]
            dashed = True
        elif flow == "both":
            # draw two rays: power + info
            mat = None
            dashed = False
        else:
            mat = mats["label"]
            dashed = False

        if flow == "both":
            # Compute a small offset perpendicular to dir_vec (prefer camera up)
            cam_up = cam_obj.matrix_world.to_3x3() @ Vector((0,1,0))
            off_dir = dir_vec.cross(cam_up)
            if off_dir.length < 1e-6:
                cam_right = cam_obj.matrix_world.to_3x3() @ Vector((1,0,0))
                off_dir = dir_vec.cross(cam_right)
            off_dir = off_dir.normalized()
            off = off_dir * (ray_rad * 2.2)

            # Power (solid)
            _cylinder_between(f"MBM_Port_{pi:02d}_Power", start + off, end + off, ray_rad, col_rays, mats["power"])
            # Info (dashed)
            dash = (ray_cfg.get("dash", {}) or {})
            dash_len = float(dash.get("dash_length", 4.0 * ray_rad))
            gap_len = float(dash.get("gap_length", 2.5 * ray_rad))
            _dashed_between(f"MBM_Port_{pi:02d}_Info", start - off, end - off, ray_rad * 0.9, dash_len, gap_len, col_rays, mats["info"])

            ray_end_for_endcap = end  # center endcap between? we use end.
            ray_dir_for_endcap = dir_vec
        else:
            if dashed:
                dash = (ray_cfg.get("dash", {}) or {})
                dash_len = float(dash.get("dash_length", 4.0 * ray_rad))
                gap_len = float(dash.get("gap_length", 2.5 * ray_rad))
                _dashed_between(f"MBM_Port_{pi:02d}", start, end, ray_rad, dash_len, gap_len, col_rays, mat)
            else:
                _cylinder_between(f"MBM_Port_{pi:02d}", start, end, ray_rad, col_rays, mat)
            ray_end_for_endcap = end
            ray_dir_for_endcap = dir_vec

        # Endcap
        endcap = p.get("endcap", {}) or {}
        assets = endcap.get("assets", []) or []
        plane_cfg = endcap.get("plane", {}) or {}
        if assets:
            _create_endcap(ray_end_for_endcap, ray_dir_for_endcap, cam_obj, assets, plane_cfg, mats, col_endcaps, manifest_dir)

    # Face labels
    face_labels = boundary.get("face_labels", []) or []
    # Sort faces by camera-facing score
    face_normals = []
    for fi, f in enumerate(faces):
        c, n = _face_center_normal(verts, f)
        score = n.dot(view_dir)
        face_normals.append((score, fi, c, n))
    face_normals.sort(reverse=True, key=lambda x: x[0])
    used_faces = set()

    def alloc_face(face_pref):
        if isinstance(face_pref, int):
            return int(face_pref)
        # "auto"
        for _, fi, _, _ in face_normals:
            if fi not in used_faces:
                used_faces.add(fi)
                return fi
        return face_normals[0][1] if face_normals else 0

    for li, L in enumerate(face_labels):
        fi = alloc_face(L.get("face", "auto"))
        center, n = _face_center_normal(verts, faces[fi])

        ray_cfg = L.get("ray", {}) or {}
        ray_len = float(ray_cfg.get("length", 0.9 * R_circum))
        ray_rad = float(ray_cfg.get("radius", 0.6 * wire_radius))

        start = center + n * (wire_radius * 0.2)
        end = center + n * ray_len

        _cylinder_between(f"MBM_FaceLabel_{li:02d}", start, end, ray_rad, col_rays, mats["label"])

        endcap = L.get("endcap", {}) or {}
        assets = endcap.get("assets", []) or []
        plane_cfg = endcap.get("plane", {}) or {}
        if assets:
            _create_endcap(end, n, cam_obj, assets, plane_cfg, mats, col_endcaps, manifest_dir)

    print("[MBM] Scene build complete.")

# -------------------------
# Blender Operator / UI
# -------------------------

from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, BoolProperty

class MBM_OT_BuildFromManifest(bpy.types.Operator, ImportHelper):
    """Build MBM render scene from JSON manifest"""
    bl_idname = "mbm.build_from_manifest"
    bl_label = "Build from Manifest"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})
    clear_existing: BoolProperty(name="Clear existing MBM objects", default=True)

    def execute(self, context):
        try:
            build_scene_from_manifest(self.filepath, clear_existing=self.clear_existing)
        except Exception as e:
            self.report({'ERROR'}, f"MBM import failed: {e}")
            raise
        return {'FINISHED'}

class MBM_PT_Panel(bpy.types.Panel):
    bl_label = "MBM Manifest Importer"
    bl_idname = "MBM_PT_manifest_importer"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MBM"

    def draw(self, context):
        layout = self.layout
        layout.label(text="Build MBM scene from JSON manifest:")
        op = layout.operator(MBM_OT_BuildFromManifest.bl_idname, text="Build from Manifest", icon='IMPORT')
        layout.separator()
        layout.label(text="Tip: keep assets next to the manifest JSON.")

classes = (MBM_OT_BuildFromManifest, MBM_PT_Panel)

def register():
    for c in classes:
        bpy.utils.register_class(c)

def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

if __name__ == "__main__":
    register()
