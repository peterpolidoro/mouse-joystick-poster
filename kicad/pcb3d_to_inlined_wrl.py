#!/usr/bin/env python3
"""
pcb3d_to_inlined_wrl.py

Convert a KiCad/pcb2blender .pcb3d export into a single self-contained VRML2 (.wrl)
file by:

- extracting pcb.wrl and all referenced components/*.wrl from the .pcb3d (it's a ZIP)
- replacing each Inline { url "components/..." } with the referenced component VRML content
- prefixing all DEF/USE identifiers inside each inserted component instance so there are
  no name collisions when everything is in one file.

This is useful when Blender can't import .pcb3d directly, or when a VRML/X3D importer
doesn't resolve Inline references.

Usage:
    python pcb3d_to_inlined_wrl.py input.pcb3d output.wrl
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path


RE_INLINE = re.compile(
    r'(?P<indent>[ \t]*)Inline\s*{\s*url\s*"(?P<url>[^"]+)"\s*}\s*',
    re.MULTILINE,
)

RE_DEF_USE = re.compile(r"\b(DEF|USE)\s+([A-Za-z_][A-Za-z0-9_]*)")


def strip_vrml_header(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("\ufeff"):
        lines[0] = lines[0].lstrip("\ufeff")
    if lines and lines[0].strip().startswith("#VRML"):
        lines = lines[1:]
    while lines and lines[0].strip() == "":
        lines = lines[1:]
    return "\n".join(lines).rstrip() + "\n"


def prefix_def_use(text: str, prefix: str) -> str:
    def repl(m: re.Match[str]) -> str:
        return f"{m.group(1)} {prefix}{m.group(2)}"

    return RE_DEF_USE.sub(repl, text)


def convert(pcb3d_path: Path, out_wrl_path: Path) -> None:
    with zipfile.ZipFile(pcb3d_path, "r") as z:
        pcb_text = z.read("pcb.wrl").decode("utf-8", errors="replace")

        counter = {"i": 0}

        def replace_inline(m: re.Match[str]) -> str:
            counter["i"] += 1
            indent = m.group("indent")
            url = m.group("url")
            try:
                raw = z.read(url).decode("utf-8", errors="replace")
            except KeyError:
                # If a referenced model isn't inside the pcb3d, keep the Inline as-is.
                return m.group(0)

            comp = strip_vrml_header(raw)
            prefix = f"I{counter['i']:03d}_"
            comp = prefix_def_use(comp, prefix)

            # Keep indentation nice (not required for correctness)
            comp_indented = "\n".join(
                (indent + line if line.strip() != "" else line) for line in comp.splitlines()
            )
            return comp_indented + "\n" + indent

        out_text = RE_INLINE.sub(replace_inline, pcb_text)

    out_wrl_path.write_text(out_text, encoding="utf-8")
    print(f"Replaced {counter['i']} Inline nodes.")
    print(f"Wrote: {out_wrl_path} ({out_wrl_path.stat().st_size/1024/1024:.2f} MB)")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip())
        return 2

    pcb3d_path = Path(argv[1]).expanduser().resolve()
    out_wrl_path = Path(argv[2]).expanduser().resolve()

    if not pcb3d_path.is_file():
        print(f"Input file not found: {pcb3d_path}")
        return 2

    convert(pcb3d_path, out_wrl_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
