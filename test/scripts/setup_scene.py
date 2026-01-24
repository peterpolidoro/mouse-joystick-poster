# scripts/setup_scene.py
import argparse
import json
import os
import sys

import bpy
from mathutils import Vector


def parse_args():
        argv = sys.argv
        if "--" in argv:
                argv = argv[argv.index("--") + 1:]
        else:
                argv = []

        p = argparse.ArgumentParser(
                description="Set up a Blender scene from a JSON manifest.")
        p.add_argument("--manifest",
                       default="manifest.json",
                       help="Path to manifest.json")
        p.add_argument("--render",
                       action="store_true",
                       help="Render a still image and quit")
        return p.parse_args(argv)


def load_manifest(path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if not isinstance(data, dict):
                raise ValueError(
                        "manifest.json must contain a JSON object at the top level."
                )
        return data


def reset_scene():
        # Start from a clean empty file (no cube/camera/light).
        bpy.ops.wm.read_factory_settings(use_empty=True)


def look_at(obj, target=(0.0, 0.0, 0.0)):
        target_v = Vector(target)
        direction = target_v - obj.location
        # Track -Z toward target, with Y as up (typical for cameras/lights).
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def add_icosahedron(radius: float):
        # Blender's "Ico Sphere" at its lowest level is an icosahedron (20 triangular faces).
        # The UI/manual describes the lowest level as an icosahedron. We use subdivisions=1.
        #
        # Parameter names vary by Blender version ('radius' vs 'size'), so we try both.
        try:
                bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1,
                                                      radius=radius,
                                                      location=(0.0, 0.0, 0.0))
        except TypeError:
                bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1,
                                                      size=radius,
                                                      location=(0.0, 0.0, 0.0))

        obj = bpy.context.object
        obj.name = "Icosahedron"
        return obj


def add_camera(distance: float, height: float, lens_mm: float):
        bpy.ops.object.camera_add(location=(0.0, -distance, height))
        cam = bpy.context.object
        cam.name = "Camera"
        cam.data.lens = float(lens_mm)

        look_at(cam, (0.0, 0.0, 0.0))
        bpy.context.scene.camera = cam
        return cam


def add_light(light_type: str, energy: float, location):
        bpy.ops.object.light_add(type=light_type, location=tuple(location))
        light = bpy.context.object
        light.name = "KeyLight"
        light.data.energy = float(energy)
        look_at(light, (0.0, 0.0, 0.0))
        return light


def apply_render_settings(cfg: dict, project_root: str):
        scene = bpy.context.scene
        r = scene.render
        rcfg = cfg.get("render", {}) if isinstance(cfg.get("render", {}),
                                                   dict) else {}

        engine = rcfg.get("engine", "CYCLES")
        r.engine = engine

        r.resolution_x = int(rcfg.get("resolution_x", 1024))
        r.resolution_y = int(rcfg.get("resolution_y", 1024))
        r.resolution_percentage = 100

        # Output format
        file_format = rcfg.get("file_format", "PNG")
        r.image_settings.file_format = file_format

        # Transparency (works in Cycles; for Eevee, film_transparent is also honored in recent versions)
        r.film_transparent = bool(rcfg.get("transparent", False))

        # Keep Blender from inventing a second extension if the user included one.
        # Blender uses render.filepath as a base and (by default) appends the correct extension.
        raw_path = rcfg.get("filepath", "output/render.png")
        abs_path = os.path.abspath(os.path.join(project_root, raw_path))
        base, _ext = os.path.splitext(abs_path)

        out_dir = os.path.dirname(base)
        if out_dir:
                os.makedirs(out_dir, exist_ok=True)

        r.filepath = base
        r.use_file_extension = True

        # Cycles samples (only if Cycles is active)
        if engine == "CYCLES" and hasattr(scene, "cycles"):
                scene.cycles.samples = int(rcfg.get("samples", 64))


def main():
        args = parse_args()
        manifest_path = os.path.abspath(args.manifest)
        project_root = os.getcwd()

        cfg = load_manifest(manifest_path)

        radius = float(cfg.get("radius", 1.0))
        camera_cfg = cfg.get("camera", {}) if isinstance(
                cfg.get("camera", {}), dict) else {}
        light_cfg = cfg.get("light", {}) if isinstance(cfg.get("light", {}),
                                                       dict) else {}

        # Sensible defaults driven by radius
        cam_distance = float(camera_cfg.get("distance", radius * 3.2))
        cam_height = float(camera_cfg.get("height", radius * 1.2))
        cam_lens = float(camera_cfg.get("lens_mm", 50.0))

        light_type = str(light_cfg.get("type", "SUN"))
        light_energy = float(light_cfg.get("energy", 3.0))
        light_loc = light_cfg.get("location",
                                  [radius * 3.0, -radius * 3.0, radius * 4.0])

        reset_scene()

        add_icosahedron(radius=radius)
        add_camera(distance=cam_distance, height=cam_height, lens_mm=cam_lens)
        add_light(light_type=light_type,
                  energy=light_energy,
                  location=light_loc)

        apply_render_settings(cfg, project_root=project_root)

        # If requested, render and quit (useful for `make render`)
        if args.render:
                bpy.ops.render.render(write_still=True)
                bpy.ops.wm.quit_blender()


if __name__ == "__main__":
        main()
