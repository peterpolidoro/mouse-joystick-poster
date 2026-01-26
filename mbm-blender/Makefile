# Makefile
# Run Blender inside a reproducible Guix environment (channels.scm + manifest.scm),
# using scripts/setup_scene.py + manifest.json to set up a scene.

PROJECT_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

CHANNELS      := $(PROJECT_ROOT)/channels.scm
GUIX_MANIFEST := $(PROJECT_ROOT)/manifest.scm

SCENE_SCRIPT  := $(PROJECT_ROOT)/setup_scene.py
SCENE_JSON    := $(PROJECT_ROOT)/manifest-1.json

# Use guix time-machine so channels.scm is respected.
GUIX_TM       := guix time-machine -C $(CHANNELS) --
GUIX_SHELL    := $(GUIX_TM) shell -m $(GUIX_MANIFEST) --

BLENDER       := blender

.PHONY: help shell open render clean

help:
	@printf "%s\n" "Targets:"
	@printf "%s\n" "  make shell   - drop into a Guix shell (from channels.scm + manifest.scm)"
	@printf "%s\n" "  make open    - open Blender GUI and set up scene from manifest.json"
	@printf "%s\n" "  make render  - headless render to a 2D image using manifest.json"
	@printf "%s\n" "  make clean   - remove ./output"

shell:
	$(GUIX_TM) shell -m $(GUIX_MANIFEST)

open:
	$(GUIX_SHELL) $(BLENDER) --python $(SCENE_SCRIPT) -- --manifest $(SCENE_JSON)

render:
	mkdir -p $(PROJECT_ROOT)/output
	$(GUIX_SHELL) $(BLENDER) --background --python $(SCENE_SCRIPT) -- --manifest $(SCENE_JSON) --render

clean:
	rm -rf $(PROJECT_ROOT)/output
