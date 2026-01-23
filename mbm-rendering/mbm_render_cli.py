"""MBM manifest → Blender render (headless CLI).

Run inside Blender:

  blender -b --factory-startup --python mbm_render_cli.py -- \
    --manifest path/to/manifest.json \
    --out output/renders/panel.png

Notes:
- This script intentionally does *not* require installing the add-on.
- It loads the importer module from mbm_blender_manifest_importer_v0.1.py
  and calls build_scene_from_manifest().
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

import bpy  # type: ignore


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--manifest",
        required=True,
        help="Path to an MBM render manifest JSON file.",
    )
    parser.add_argument(
        "--out",
        required=True,
        help=(
            "Output image path. If it has an extension, that extension controls "
            "the output format (png/jpg/jpeg/tif/tiff/exr). If it has no extension, "
            "PNG is used and '.png' is appended."
        ),
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        default=True,
        help="Clear existing MBM_* collections/objects before building (default: true).",
    )
    parser.add_argument(
        "--no-clear",
        dest="clear",
        action="store_false",
        help="Do not clear existing MBM_* collections/objects.",
    )
    parser.add_argument(
        "--write-blend",
        default="",
        help="Optional: write a .blend next to the render for debugging.",
    )
    return parser.parse_args(argv)


def _blender_argv_after_doubledash() -> list[str]:
    """Blender passes its own args in sys.argv; script args come after '--'."""
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _load_importer_module() -> object:
    """Load mbm_blender_manifest_importer_v0.1.py as a module."""
    here = Path(__file__).resolve().parent
    importer_path = here / "mbm_blender_manifest_importer_v0.1.py"
    if not importer_path.exists():
        raise FileNotFoundError(f"Importer not found: {importer_path}")

    spec = importlib.util.spec_from_file_location("mbm_importer", str(importer_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load importer module spec for {importer_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def _format_from_ext(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    return {
        "png": "PNG",
        "jpg": "JPEG",
        "jpeg": "JPEG",
        "tif": "TIFF",
        "tiff": "TIFF",
        "exr": "OPEN_EXR",
    }.get(ext, "PNG")


def main() -> None:
    args = _parse_args(_blender_argv_after_doubledash())

    manifest_path = Path(args.manifest).expanduser().resolve()
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    out_path = Path(args.out).expanduser().resolve()

    # Decide output format from extension (default to PNG).
    ext = out_path.suffix.lower()
    if ext:
        fmt = _format_from_ext(ext)
        base_out = out_path.with_suffix("")  # let Blender append extension
        expected_out = out_path
    else:
        fmt = "PNG"
        base_out = out_path
        expected_out = out_path.with_suffix(".png")

    os.makedirs(str(base_out.parent), exist_ok=True)

    importer = _load_importer_module()
    if not hasattr(importer, "build_scene_from_manifest"):
        raise AttributeError("Importer module missing build_scene_from_manifest()")

    print(f"[MBM_CLI] Building scene from: {manifest_path}")
    importer.build_scene_from_manifest(str(manifest_path), clear_existing=bool(args.clear))

    scene = bpy.context.scene
    scene.render.image_settings.file_format = fmt
    # Preserve alpha if background is transparent; otherwise it'll just be opaque.
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"

    # Blender uses filepath as a *base* and appends the extension when
    # render.use_file_extension is enabled.
    scene.render.use_file_extension = True
    scene.render.filepath = str(base_out)

    print(f"[MBM_CLI] Rendering still → {expected_out} (format={fmt})")
    bpy.ops.render.render(write_still=True)

    if args.write_blend:
        blend_path = Path(args.write_blend).expanduser().resolve()
        os.makedirs(str(blend_path.parent), exist_ok=True)
        print(f"[MBM_CLI] Writing debug .blend → {blend_path}")
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    print("[MBM_CLI] Done.")


if __name__ == "__main__":
    main()
