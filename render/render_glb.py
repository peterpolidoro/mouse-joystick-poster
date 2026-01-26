"""
render_glb.py

Import a GLB, normalize it, set up a simple studio scene (camera + lights),
and optionally render a high-quality PNG with a transparent background.

Designed for two workflows:

1) GUI preview (open Blender and inspect the scene)
   blender -P render_glb.py -- --manifest manifest.json --setup-only

2) Headless render (no UI, writes PNG)
   blender -b -P render_glb.py -- --manifest manifest.json --render

Notes
- By default, the script renders only when Blender is run with -b/--background.
  In UI mode it just sets up the scene.
- Denoising defaults to "auto": uses OIDN if Blender was built with it,
  otherwise falls back to NLM (built-in).
"""

import bpy
import sys
import json
import math
from pathlib import Path
from mathutils import Vector


# ----------------------------
# CLI / Manifest
# ----------------------------
def _after_double_dash_argv():
    argv = sys.argv
    if "--" in argv:
        return argv[argv.index("--") + 1 :]
    return []


def parse_args():
    argv = _after_double_dash_argv()

    # Track which flags were explicitly passed on the CLI so we can give CLI precedence over manifest.json.
    cli_flags = {a for a in argv if a.startswith("--")}

    import argparse
    p = argparse.ArgumentParser()

    p.add_argument("--manifest", default=None)

    p.add_argument("--input", default=None)
    p.add_argument("--output", default=None)

    # Transform overrides
    p.add_argument("--rot", nargs=3, type=float, default=[0.0, 0.0, 0.0])  # degrees
    p.add_argument("--scale", type=float, default=1.0)  # extra multiplier after normalization
    p.add_argument("--size", type=float, default=2.0)   # target max dimension (Blender units)

    # Render settings
    p.add_argument("--res", nargs=2, type=int, default=[1024, 1024])
    p.add_argument("--samples", type=int, default=512)
    p.add_argument("--engine", default="cycles", choices=["cycles", "eevee"])

    p.add_argument("--gpu", action="store_true", help="Try to render with GPU (Cycles only). Falls back to CPU if unavailable.")

    # Denoising: auto|nlm|oidn|optix|off
    p.add_argument(
        "--denoiser",
        default="auto",
        help="Denoiser to use for Cycles: auto|nlm|oidn|optix|off (default: auto).",
    )

    # Mode controls
    p.add_argument("--render", action="store_true", help="Force rendering a still image (even in UI mode).")
    p.add_argument(
        "--setup-only", "--setup_only",
        dest="setup_only",
        action="store_true",
        help="Set up the scene only; do not render (even in background mode).",
    )
    p.add_argument(
        "--save-blend", "--save_blend",
        dest="save_blend",
        default=None,
        help="Optional path to save the .blend after scene setup.",
    )

    # Camera
    p.add_argument("--azimuth", type=float, default=0.0)     # degrees (0 = front)
    p.add_argument("--elevation", type=float, default=25.0)  # degrees
    p.add_argument("--fov", type=float, default=50.0)        # degrees

    # Lighting / world
    p.add_argument("--shadow-catcher", "--shadow_catcher", dest="shadow_catcher", action="store_true")
    p.add_argument("--hdri", default=None)
    p.add_argument("--hdri-strength", "--hdri_strength", dest="hdri_strength", type=float, default=1.0)

    args = p.parse_args(argv)
    return args, cli_flags


def _cli_provided(cli_flags: set, key: str) -> bool:
    """
    Returns True if the CLI included a flag that corresponds to `key`.
    Supports both --snake_case and --kebab-case forms.
    """
    snake = f"--{key}"
    kebab = f"--{key.replace('_', '-')}"
    return (snake in cli_flags) or (kebab in cli_flags)


def apply_manifest_overrides(args, cli_flags: set):
    """
    Apply manifest.json values as defaults, but do NOT override any setting
    explicitly provided on the CLI.
    """
    if not args.manifest:
        return args

    manifest_path = Path(args.manifest)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    # allow relative paths inside manifest to be relative to manifest file
    base = manifest_path.parent

    def norm_path(v):
        if v is None:
            return None
        p = Path(v)
        if not p.is_absolute():
            p = (base / p).resolve()
        return str(p)

    for k, v in data.items():
        if not hasattr(args, k):
            continue
        if _cli_provided(cli_flags, k):
            continue

        if k in ("input", "output", "hdri", "save_blend"):
            setattr(args, k, norm_path(v))
        else:
            setattr(args, k, v)

    return args


def default_output_for_input(input_path: str) -> str:
    """
    If no output is provided, default to ./output/<input_stem>.png
    relative to the current working directory.
    """
    p = Path(input_path)
    out = Path.cwd() / "output" / f"{p.stem}.png"
    return str(out.resolve())


def should_render(args) -> bool:
    """
    Decide whether to render.
    - --setup-only always disables render.
    - --render always enables render.
    - Otherwise: render in background mode, do setup-only in UI mode.
    """
    if getattr(args, "setup_only", False):
        return False
    if getattr(args, "render", False):
        return True
    return bool(bpy.app.background)


# ----------------------------
# Scene helpers
# ----------------------------
def wipe_scene():
    # Remove objects without relying on selection/context
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    # Ensure we have a World
    scene = bpy.context.scene
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")

    return scene


def enable_gltf_importer():
    # Usually enabled by default, but safe to try.
    try:
        if "io_scene_gltf2" not in bpy.context.preferences.addons:
            bpy.ops.preferences.addon_enable(module="io_scene_gltf2")
    except Exception:
        pass


def import_glb(filepath: str):
    enable_gltf_importer()

    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(filepath))
    after = set(bpy.data.objects)

    imported = list(after - before)
    meshes = [o for o in imported if o.type == "MESH"]
    return imported, meshes


def make_root_empty(name="ROOT"):
    root = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(root)
    return root


def parent_top_level_to_root(imported, root):
    for obj in imported:
        if obj.parent is None:
            obj.parent = root
            obj.matrix_parent_inverse = root.matrix_world.inverted()


def smooth_shade_meshes(meshes):
    # Avoid bpy.ops.* (context-sensitive) by flipping polygon smooth flags directly
    for obj in meshes:
        me = obj.data
        if hasattr(me, "polygons"):
            for poly in me.polygons:
                poly.use_smooth = True


def get_bounds_world(mesh_objects):
    deps = bpy.context.evaluated_depsgraph_get()
    min_v = Vector((math.inf, math.inf, math.inf))
    max_v = Vector((-math.inf, -math.inf, -math.inf))
    found = False

    for obj in mesh_objects:
        eval_obj = obj.evaluated_get(deps)
        for corner in eval_obj.bound_box:
            v = eval_obj.matrix_world @ Vector(corner)
            min_v.x = min(min_v.x, v.x)
            min_v.y = min(min_v.y, v.y)
            min_v.z = min(min_v.z, v.z)
            max_v.x = max(max_v.x, v.x)
            max_v.y = max(max_v.y, v.y)
            max_v.z = max(max_v.z, v.z)
            found = True

    if not found:
        return None, None

    return min_v, max_v


def set_world(scene, hdri_path=None, strength=1.0):
    world = scene.world
    world.use_nodes = True
    nt = world.node_tree
    nodes = nt.nodes
    links = nt.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputWorld")
    bg = nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = float(strength)

    if hdri_path:
        env = nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(hdri_path, check_existing=True)
        links.new(env.outputs["Color"], bg.inputs["Color"])
    else:
        # neutral gray so reflections look sane
        bg.inputs["Color"].default_value = (0.18, 0.18, 0.18, 1.0)

    links.new(bg.outputs["Background"], out.inputs["Surface"])


def look_at(obj, target: Vector):
    direction = (target - obj.location)
    if direction.length == 0:
        return
    rot = direction.to_track_quat("-Z", "Y")
    obj.rotation_euler = rot.to_euler()


def add_area_light(name, location, target, size, energy):
    data = bpy.data.lights.new(name=name, type="AREA")
    data.energy = float(energy)
    data.size = float(size)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = Vector(location)
    look_at(obj, Vector(target))
    return obj


def add_camera(target, distance, azimuth_deg, elevation_deg, fov_deg):
    cam_data = bpy.data.cameras.new("Camera")
    cam_obj = bpy.data.objects.new("Camera", cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    # Prefer FOV control if available
    try:
        cam_data.lens_unit = "FOV"
        cam_data.angle = math.radians(float(fov_deg))
    except Exception:
        cam_data.lens = 50.0

    az = math.radians(float(azimuth_deg))
    el = math.radians(float(elevation_deg))

    # Convention: azimuth=0 => camera in front (-Y), like Blender default
    x = target.x + distance * math.sin(az) * math.cos(el)
    y = target.y - distance * math.cos(az) * math.cos(el)
    z = target.z + distance * math.sin(el)

    cam_obj.location = Vector((x, y, z))
    look_at(cam_obj, target)

    cam_data.clip_start = max(0.001, distance / 100.0)
    cam_data.clip_end = distance * 100.0
    return cam_obj


# ----------------------------
# Render configuration
# ----------------------------
def _build_has_openimagedenoise() -> bool:
    try:
        return bool(getattr(bpy.app.build_options, "openimagedenoise", False))
    except Exception:
        return False


def _available_denoisers():
    """
    Returns list like ["OPTIX", "OPENIMAGEDENOISE", "NLM", ...] depending on build.
    """
    try:
        cyc = bpy.context.view_layer.cycles
        prop = cyc.bl_rna.properties.get("denoiser")
        if prop:
            return [i.identifier for i in prop.enum_items]
    except Exception:
        pass
    return []


def _set_denoising(enabled: bool, denoiser: str = None):
    # View-layer cycles denoise is the main path in Blender 3.6+
    try:
        cyc = bpy.context.view_layer.cycles
    except Exception:
        return

    try:
        cyc.use_denoising = bool(enabled)
    except Exception:
        return

    if enabled and denoiser:
        try:
            cyc.denoiser = denoiser
        except Exception:
            # If setting fails, disable denoise to avoid render-time errors
            try:
                cyc.use_denoising = False
            except Exception:
                pass
            return

    # Quality hint (if available)
    try:
        if hasattr(cyc, "denoising_input_passes"):
            cyc.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    except Exception:
        pass


def configure_denoising(scene, args):
    """
    Avoid selecting OIDN when Blender was built without it.
    Default behavior:
      - args.denoiser == "auto" -> OIDN if available, else NLM, else off
    """
    if scene.render.engine != "CYCLES":
        return

    requested = str(getattr(args, "denoiser", "auto")).strip().lower()
    denoisers = _available_denoisers()

    chosen = None

    if requested in ("off", "none", "false", "0"):
        chosen = None
    elif requested in ("nlm",):
        chosen = "NLM" if "NLM" in denoisers else None
    elif requested in ("optix",):
        chosen = "OPTIX" if "OPTIX" in denoisers else None
    elif requested in ("oidn", "openimagedenoise", "open_image_denoise", "openimagedenoiser"):
        if _build_has_openimagedenoise() and "OPENIMAGEDENOISE" in denoisers:
            chosen = "OPENIMAGEDENOISE"
        else:
            # fallback
            chosen = "NLM" if "NLM" in denoisers else None
    else:
        # auto / unknown -> safe default
        if _build_has_openimagedenoise() and "OPENIMAGEDENOISE" in denoisers:
            chosen = "OPENIMAGEDENOISE"
        elif "NLM" in denoisers:
            chosen = "NLM"
        else:
            chosen = None

    if chosen is None:
        _set_denoising(False)
        print("Denoising: OFF")
    else:
        _set_denoising(True, chosen)
        print(f"Denoising: {chosen}")


def setup_render(scene, args):
    # Engine
    engine_items = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    if str(args.engine).lower() == "cycles":
        scene.render.engine = "CYCLES"
    else:
        # Eevee name differs across versions
        if "BLENDER_EEVEE_NEXT" in engine_items:
            scene.render.engine = "BLENDER_EEVEE_NEXT"
        else:
            scene.render.engine = "BLENDER_EEVEE"

    # Resolution
    scene.render.resolution_x = int(args.res[0])
    scene.render.resolution_y = int(args.res[1])
    scene.render.resolution_percentage = 100

    # Transparent background
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "16"

    # Color management (Filmic is a good default for product renders)
    try:
        scene.view_settings.view_transform = "Filmic"
        scene.view_settings.look = "Medium High Contrast"
    except Exception:
        pass

    # Cycles quality
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = int(args.samples)
        if hasattr(scene.cycles, "use_adaptive_sampling"):
            scene.cycles.use_adaptive_sampling = True
        if hasattr(scene.cycles, "adaptive_threshold"):
            scene.cycles.adaptive_threshold = 0.01

        # Denoising: do NOT force OIDN; choose safely
        configure_denoising(scene, args)


def enable_gpu_if_requested(scene, gpu_requested: bool):
    """
    Enable GPU rendering in Cycles if possible.
    Important:
      - Do not disable CPU device blindly (it can be needed for OIDN denoising).
      - Fall back to CPU if no GPU device exists.
    """
    if not gpu_requested:
        return
    if scene.render.engine != "CYCLES":
        return

    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences

        # Pick best available compute backend
        enum_items = [i.identifier for i in prefs.bl_rna.properties["compute_device_type"].enum_items]
        chosen_backend = None
        for t in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
            if t in enum_items:
                chosen_backend = t
                break
        if chosen_backend:
            prefs.compute_device_type = chosen_backend

        # Query devices
        try:
            prefs.get_devices()
        except Exception:
            pass

        gpu_found = False
        if hasattr(prefs, "devices"):
            for d in prefs.devices:
                # Keep CPU enabled; enable any available GPU devices too
                try:
                    d.use = True
                except Exception:
                    pass
                if getattr(d, "type", "") != "CPU":
                    gpu_found = True

        if gpu_found:
            scene.cycles.device = "GPU"
            print("Cycles device: GPU")
        else:
            scene.cycles.device = "CPU"
            print("Requested GPU, but no GPU devices found. Falling back to CPU.")
    except Exception as e:
        print("GPU enable failed (continuing on CPU):", e)


def add_shadow_catcher_plane(plane_size=6.0):
    bpy.ops.mesh.primitive_plane_add(size=float(plane_size), location=(0, 0, 0))
    plane = bpy.context.active_object
    # Cycles-only feature; ignore if unavailable
    try:
        plane.cycles.is_shadow_catcher = True
    except Exception:
        pass
    return plane


# ----------------------------
# Scene setup + render
# ----------------------------
def setup_scene(args):
    scene = wipe_scene()
    setup_render(scene, args)
    enable_gpu_if_requested(scene, bool(args.gpu))

    # World lighting (HDRI optional, still transparent in final render)
    set_world(scene, args.hdri, float(getattr(args, "hdri_strength", 1.0)))

    imported, meshes = import_glb(args.input)
    if not meshes:
        raise RuntimeError("No mesh objects found in GLB (nothing to render).")

    smooth_shade_meshes(meshes)

    root = make_root_empty("MODEL_ROOT")
    parent_top_level_to_root(imported, root)

    # Apply user rotation to the whole model
    rx, ry, rz = [math.radians(v) for v in args.rot]
    root.rotation_euler = (rx, ry, rz)
    bpy.context.view_layer.update()

    # Normalize scale (so max dimension == args.size), then apply extra user scale
    min_v, max_v = get_bounds_world(meshes)
    dims = (max_v - min_v)
    max_dim = max(dims.x, dims.y, dims.z)
    if max_dim <= 1e-8:
        raise RuntimeError("Imported model bounds are too small/invalid.")

    scale_factor = (float(args.size) / float(max_dim)) * float(args.scale)
    root.scale = Vector((scale_factor, scale_factor, scale_factor))
    bpy.context.view_layer.update()

    # Recompute bounds after scaling
    min_v, max_v = get_bounds_world(meshes)
    center = (min_v + max_v) * 0.5

    # Move model so it's centered in X/Y and sits on ground (Z=0)
    shift = Vector((-center.x, -center.y, -min_v.z))
    root.location += shift
    bpy.context.view_layer.update()

    # Final bounds + target point for camera/lights
    min_v, max_v = get_bounds_world(meshes)
    dims = (max_v - min_v)
    target = Vector((0.0, 0.0, dims.z * 0.5))

    # Optional shadow catcher plane
    if scene.render.engine == "CYCLES" and getattr(args, "shadow_catcher", False):
        add_shadow_catcher_plane(plane_size=max(6.0, float(args.size) * 3.0))

    # Lights (simple 3-point studio)
    # Because we normalized to args.size, these positions/energies are reasonably consistent.
    radius = float(args.size) * 1.6
    add_area_light("Key",  ( radius, -radius, float(args.size) * 1.6), target, size=float(args.size) * 1.2, energy=1500)
    add_area_light("Fill", (-radius, -radius, float(args.size) * 1.0), target, size=float(args.size) * 1.5, energy=500)
    add_area_light("Rim",  ( 0.0,     radius, float(args.size) * 1.8), target, size=float(args.size) * 1.0, energy=900)

    # Camera distance to frame object
    cam = add_camera(target=target, distance=1.0, azimuth_deg=args.azimuth, elevation_deg=args.elevation, fov_deg=args.fov)

    # Compute a safe distance based on bounding sphere
    r = 0.5 * dims.length
    try:
        alpha = min(cam.data.angle_x, cam.data.angle_y) * 0.5
    except Exception:
        alpha = cam.data.angle * 0.5

    # avoid division by zero
    alpha = max(alpha, 0.01)
    distance = (r / math.sin(alpha)) * 1.15
    # Re-place camera at computed distance
    bpy.data.objects.remove(cam, do_unlink=True)
    add_camera(target=target, distance=distance, azimuth_deg=args.azimuth, elevation_deg=args.elevation, fov_deg=args.fov)

    return scene


def maybe_save_blend(args):
    path = getattr(args, "save_blend", None)
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(p.resolve()))
    print("Saved .blend:", str(p.resolve()))


def _disable_denoising_best_effort(scene):
    try:
        bpy.context.view_layer.cycles.use_denoising = False
    except Exception:
        pass
    try:
        scene.cycles.use_denoising = False
    except Exception:
        pass


def do_render(scene, output_path: str):
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(out_path.resolve())

    try:
        bpy.ops.render.render(write_still=True)
    except RuntimeError as e:
        # Some Blender builds (e.g. distro/Guix) can be built without OIDN.
        # If a denoiser choice triggers a render-time failure, retry without denoising.
        msg = str(e)
        if ("OpenImageDenoiser" in msg) or ("denoise" in msg.lower()):
            print("Render failed due to denoiser. Disabling denoising and retrying once...")
            _disable_denoising_best_effort(scene)
            bpy.ops.render.render(write_still=True)
        else:
            raise

    print("Rendered:", str(out_path.resolve()))


def main():
    args, cli_flags = parse_args()
    args = apply_manifest_overrides(args, cli_flags)

    if not args.input:
        raise SystemExit("Provide --input <model.glb> or a --manifest with an 'input' field.")

    # Decide mode
    render_now = should_render(args)

    # If we're going to render, ensure we have an output
    if render_now and not args.output:
        args.output = default_output_for_input(args.input)

    scene = setup_scene(args)
    maybe_save_blend(args)

    if render_now:
        do_render(scene, args.output)
    else:
        print("Scene setup complete (no render).")


if __name__ == "__main__":
    main()
