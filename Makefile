# mouse-joystick-poster — reproducible poster toolchain (Guix)
#
# This Makefile is intentionally “batteries included” for day-to-day use:
#   - enter reproducible Guix shells
#   - launch GUI tools (KiCad / FreeCAD / Blender / Inkscape / GIMP)
#   - run common export helpers (SVG→PDF, trimming, etc.)
#
# Usage:
#   make help
#   make shell
#   make freecad
#   make kicad
#   make poster-print
#
# Notes:
# - Targets that spawn a shell will open an interactive subshell. Exit to return.
# - GUI programs run inside the Guix environment, but still use your host graphics stack.

MAKEFILE_PATH := $(abspath $(lastword $(MAKEFILE_LIST)))
REPO_ROOT     := $(patsubst %/,%,$(abspath $(dir $(MAKEFILE_PATH))))

GUIX        ?= guix
CHANNELS    ?= $(REPO_ROOT)/guix/channels.scm
MANIFEST    ?= $(REPO_ROOT)/guix/manifest.scm

# Use user's default shell inside the Guix environment.
HOST_SHELL  ?= $(SHELL)

# Convenience: platform-appropriate "open".
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
OPEN ?= open
else
OPEN ?= xdg-open
endif

GUIX_TIME_MACHINE := $(GUIX) time-machine -C $(CHANNELS)
GUIX_SHELL        := $(GUIX_TIME_MACHINE) -- shell -m $(MANIFEST)

# Containerized shell (useful if you want a cleaner separation from host libs).
# This mirrors the style from your other CAD/EDA Makefiles.
CONTAINER_ARGS ?= --container -F \
	-E '^DISPLAY$$' \
	-E '^WAYLAND_DISPLAY$$' \
	-E '^XAUTHORITY$$' \
	-E '^XDG_RUNTIME_DIR$$' \
	--expose="$${XAUTHORITY}" \
	--expose=/tmp/.X11-unix/ \
	--expose=$$HOME/.Xauthority \
	--expose=/etc/machine-id

GUIX_CONTAINER := $(GUIX_SHELL) $(CONTAINER_ARGS)

# Per-project app config homes (keeps ~/.config cleaner and makes projects more portable).
KICAD_CONFIG_HOME   ?= $(REPO_ROOT)/.config/kicad
FREECAD_USER_HOME   ?= $(REPO_ROOT)/.config/freecad

# Suggested project files (override from CLI if you use different paths).
FREECAD_PROJECT ?= $(firstword $(wildcard $(REPO_ROOT)/freecad/*.FCStd $(REPO_ROOT)/freecad/*.fcstd))
JOYSTICK_STEP   ?= $(firstword $(wildcard $(REPO_ROOT)/cad/joystick/*.step $(REPO_ROOT)/cad/joystick/*.stp))
PCB_STEP        ?= $(firstword $(wildcard $(REPO_ROOT)/cad/pcb/*.step $(REPO_ROOT)/cad/pcb/*.stp))

KICAD_PROJECT   ?= $(firstword $(wildcard $(REPO_ROOT)/kicad/*.kicad_pro $(REPO_ROOT)/*.kicad_pro))
KICAD_PCB       ?= $(firstword $(wildcard $(REPO_ROOT)/kicad/*.kicad_pcb))
KICAD_SCH       ?= $(firstword $(wildcard $(REPO_ROOT)/kicad/*.kicad_sch))

BLENDER_FILE    ?= $(firstword $(wildcard $(REPO_ROOT)/blender/*.blend))

# MBM (Mechatronic Boundary Model) manifest-driven Blender renders
#
# The mbm-rendering/ directory contains a Blender-side importer that can build
# a scene from a JSON manifest. We wrap it with a small CLI so it can be used
# headlessly from Make.
MBM_DIR           ?= $(REPO_ROOT)/mbm-rendering
MBM_RENDER_CLI    ?= $(MBM_DIR)/mbm_render_cli.py
MBM_TEST_DIR      ?= $(MBM_DIR)/test_scene
MBM_TEST_MANIFEST ?= $(MBM_TEST_DIR)/manifest.json

# Default inputs for `make mbm-render` (override from CLI)
MBM_RENDER_MANIFEST ?= $(MBM_TEST_MANIFEST)
MBM_RENDER_OUT      ?= $(RENDERS_DIR)/mbm-test.png

POSTER_PRINT_SVG    ?= $(REPO_ROOT)/poster/print.svg
POSTER_IPOSTER_SVG  ?= $(REPO_ROOT)/poster/iposter.svg
POSTER_SVG        ?= $(firstword $(wildcard $(POSTER_PRINT_SVG) $(POSTER_IPOSTER_SVG) $(REPO_ROOT)/poster/*.svg))

OUT_DIR        ?= $(REPO_ROOT)/output
RENDERS_DIR    ?= $(OUT_DIR)/renders
EXPORTS_DIR    ?= $(OUT_DIR)/exports
PREVIEW_W      ?= 2400

.PHONY: help \
	guix-version describe lock-channels \
	shell shell-pure shell-container shell-container-net \
	config-dirs dirs clean \
	freecad freecad-joystick-step freecad-pcb-step \
	kicad pcbnew eeschema \
	blender \
	mbm-render mbm-render-test \
	poster poster-print poster-iposter inkscape gimp \
	export-print-pdf export-iposter-pdf export-print-png export-iposter-png \
	svg-plain trim-png qr \
	open open-renders open-exports open-cad open-poster

help:
	@printf "%s\n" \
	"Core:" \
	"  make shell                Enter a Guix dev shell (impure; easiest for GUI apps)" \
	"  make shell-pure           Enter a pure Guix dev shell (more reproducible)" \
	"  make shell-container      Enter a containerized Guix dev shell (X11/Wayland passthrough)" \
	"  make shell-container-net  Same as above, but with network enabled" \
	"  make lock-channels        Pin guix/channels.scm to your current Guix revision" \
	"" \
	"Launch tools (in Guix env):" \
	"  make freecad              Launch FreeCAD (opens freecad/*.FCStd if present)" \
	"  make freecad-joystick-step  Open cad/joystick/*.step in FreeCAD (if present)" \
	"  make freecad-pcb-step       Open cad/pcb/*.step in FreeCAD (if present)" \
	"  make kicad                Launch KiCad (opens kicad/*.kicad_pro if present)" \
	"  make pcbnew               Launch pcbnew (opens kicad/*.kicad_pcb if present)" \
	"  make eeschema             Launch eeschema (opens kicad/*.kicad_sch if present)" \
	"  make blender              Launch Blender (opens blender/*.blend if present)" \
	"  make poster-print         Launch Inkscape on poster/print.svg" \
	"  make poster-iposter       Launch Inkscape on poster/iposter.svg" \
	"  make gimp FILE=path.xcf   Launch GIMP (optionally open a file)" \
	"" \
	"Exports/helpers:" \
	"  make mbm-render MBM_RENDER_MANIFEST=path.json MBM_RENDER_OUT=output/renders/x.png  Render an MBM manifest (headless Blender)" \
	"  make mbm-render-test        Render the included MBM test manifest" \
	"  make export-print-pdf     Export poster/print.svg → output/exports/print.pdf" \
	"  make export-iposter-pdf   Export poster/iposter.svg → output/exports/iposter.pdf" \
	"  make export-print-png     Export a preview PNG (width PREVIEW_W)" \
	"  make svg-plain DIR=docs   Convert SVGs in DIR to plain SVG (Inkscape)" \
	"  make trim-png DIR=output/renders  Trim PNGs in DIR (ImageMagick mogrify)" \
	"  make qr TEXT='...' OUT=output/renders/qr.png  Generate a QR code" \
	"" \
	"Open folders/files (host open):" \
	"  make open FILE=path       Open a file with the OS default handler" \
	"  make open-renders         Open output/renders" \
	"  make open-exports         Open output/exports"

guix-version:
	@$(GUIX) --version

describe:
	@$(GUIX) describe

# Development shells ---------------------------------------------------------

# Impure shell:
# - Inherits your host environment (PATH, DISPLAY, Wayland vars, etc.)
# - Often the least-friction choice for GUI programs.
shell:
	@$(GUIX_SHELL) -- $(HOST_SHELL)

# Pure shell:
# - Starts from a mostly clean environment; still preserves GUI-relevant vars.
shell-pure:
	@$(GUIX_TIME_MACHINE) -- shell --pure -m $(MANIFEST) \
		--preserve='^DISPLAY$$' \
		--preserve='^WAYLAND_DISPLAY$$' \
		--preserve='^XAUTHORITY$$' \
		--preserve='^XDG_RUNTIME_DIR$$' \
		--preserve='^DBUS_SESSION_BUS_ADDRESS$$' \
		--preserve='^SSH_AUTH_SOCK$$' \
		--preserve='^HOME$$' \
		--preserve='^USER$$' \
		--preserve='^LOGNAME$$' \
		--preserve='^LANG$$' \
		--preserve='^LC_.*$$' \
		--preserve='^TZ$$' \
		--preserve='^TERM$$' \
		--preserve='^COLORTERM$$' \
		--preserve='^EDITOR$$' \
		--preserve='^VISUAL$$' \
		-- $(HOST_SHELL)

shell-container:
	@$(GUIX_CONTAINER) -- $(HOST_SHELL)

shell-container-net:
	@$(GUIX_CONTAINER) --network -- $(HOST_SHELL)

# Channel pinning ------------------------------------------------------------

# Writes an exact channels.scm (commit + intro) matching your current Guix.
# Commit this file to make the environment reproducible for others.
lock-channels:
	@$(GUIX) describe --format=channels > $(CHANNELS)
	@echo "Wrote pinned channels to $(CHANNELS)"

# Housekeeping --------------------------------------------------------------

config-dirs:
	@mkdir -p "$(KICAD_CONFIG_HOME)" "$(FREECAD_USER_HOME)"

dirs:
	@mkdir -p "$(RENDERS_DIR)" "$(EXPORTS_DIR)"

clean:
	@rm -rf "$(OUT_DIR)"
	@echo "Removed $(OUT_DIR)"

# Launchers (Guix env) ------------------------------------------------------

freecad: config-dirs
	@set -e; \
	FC="$(FREECAD_PROJECT)"; \
	if [ -n "$$FC" ]; then \
		echo "Opening FreeCAD project: $$FC"; \
		HOME="$(REPO_ROOT)" FREECAD_USER_HOME="$(FREECAD_USER_HOME)" \
			$(GUIX_SHELL) -E '^HOME$$' -E '^FREECAD_USER_HOME$$' -- FreeCAD "$$FC"; \
	else \
		echo "Opening FreeCAD (no freecad/*.FCStd found)"; \
		HOME="$(REPO_ROOT)" FREECAD_USER_HOME="$(FREECAD_USER_HOME)" \
			$(GUIX_SHELL) -E '^HOME$$' -E '^FREECAD_USER_HOME$$' -- FreeCAD; \
	fi

freecad-joystick-step: config-dirs
	@set -e; \
	STP="$(JOYSTICK_STEP)"; \
	if [ -z "$$STP" ]; then \
		echo "No STEP found in cad/joystick/. Put your assembly there (e.g., cad/joystick/joystick.step)."; \
		exit 2; \
	fi; \
	echo "Opening joystick STEP in FreeCAD: $$STP"; \
	HOME="$(REPO_ROOT)" FREECAD_USER_HOME="$(FREECAD_USER_HOME)" \
		$(GUIX_SHELL) -E '^HOME$$' -E '^FREECAD_USER_HOME$$' -- FreeCAD "$$STP"

freecad-pcb-step: config-dirs
	@set -e; \
	STP="$(PCB_STEP)"; \
	if [ -z "$$STP" ]; then \
		echo "No STEP found in cad/pcb/. Put your PCB assembly there (e.g., cad/pcb/pcb.step)."; \
		exit 2; \
	fi; \
	echo "Opening PCB STEP in FreeCAD: $$STP"; \
	HOME="$(REPO_ROOT)" FREECAD_USER_HOME="$(FREECAD_USER_HOME)" \
		$(GUIX_SHELL) -E '^HOME$$' -E '^FREECAD_USER_HOME$$' -- FreeCAD "$$STP"

kicad: config-dirs
	@set -e; \
	PRO="$(KICAD_PROJECT)"; \
	if [ -n "$$PRO" ]; then \
		echo "Opening KiCad project: $$PRO"; \
		KICAD_CONFIG_HOME="$(KICAD_CONFIG_HOME)" \
			$(GUIX_SHELL) -E '^KICAD_CONFIG_HOME$$' -- kicad "$$PRO"; \
	else \
		echo "Opening KiCad (no kicad/*.kicad_pro found)"; \
		KICAD_CONFIG_HOME="$(KICAD_CONFIG_HOME)" \
			$(GUIX_SHELL) -E '^KICAD_CONFIG_HOME$$' -- kicad; \
	fi

pcbnew: config-dirs
	@set -e; \
	PCB="$(KICAD_PCB)"; \
	if [ -n "$$PCB" ]; then \
		echo "Opening pcbnew: $$PCB"; \
		KICAD_CONFIG_HOME="$(KICAD_CONFIG_HOME)" \
			$(GUIX_SHELL) -E '^KICAD_CONFIG_HOME$$' -- pcbnew "$$PCB"; \
	else \
		echo "Opening pcbnew"; \
		KICAD_CONFIG_HOME="$(KICAD_CONFIG_HOME)" \
			$(GUIX_SHELL) -E '^KICAD_CONFIG_HOME$$' -- pcbnew; \
	fi

eeschema: config-dirs
	@set -e; \
	SCH="$(KICAD_SCH)"; \
	if [ -n "$$SCH" ]; then \
		echo "Opening eeschema: $$SCH"; \
		KICAD_CONFIG_HOME="$(KICAD_CONFIG_HOME)" \
			$(GUIX_SHELL) -E '^KICAD_CONFIG_HOME$$' -- eeschema "$$SCH"; \
	else \
		echo "Opening eeschema"; \
		KICAD_CONFIG_HOME="$(KICAD_CONFIG_HOME)" \
			$(GUIX_SHELL) -E '^KICAD_CONFIG_HOME$$' -- eeschema; \
	fi

blender: dirs
	@set -e; \
	BL="$(BLENDER_FILE)"; \
	if [ -n "$$BL" ]; then \
		echo "Opening Blender file: $$BL"; \
		$(GUIX_SHELL) -- blender "$$BL"; \
	else \
		echo "Opening Blender (no blender/*.blend found)"; \
		$(GUIX_SHELL) -- blender; \
	fi

# MBM renders (headless Blender) -------------------------------------------

# Render an MBM scene from a manifest JSON using Blender in background mode.
#
# Examples:
#   make mbm-render-test
#   make mbm-render MBM_RENDER_MANIFEST=mbm-rendering/test_scene/manifest.json \
#        MBM_RENDER_OUT=output/renders/mbm-test.png
#
# Tip: if something looks off, write a debug .blend to inspect interactively:
#   make mbm-render MBM_RENDER_OUT=output/renders/mbm-test.png \
#        MBM_RENDER_WRITE_BLEND=output/renders/mbm-test.blend
MBM_RENDER_WRITE_BLEND ?=

mbm-render: dirs
	@set -e; \
	if [ ! -f "$(MBM_RENDER_MANIFEST)" ]; then \
		echo "Missing MBM_RENDER_MANIFEST: $(MBM_RENDER_MANIFEST)"; \
		echo "(Tip: the repo includes $(MBM_TEST_MANIFEST))"; \
		exit 2; \
	fi; \
	if [ ! -f "$(MBM_RENDER_CLI)" ]; then \
		echo "Missing MBM_RENDER_CLI: $(MBM_RENDER_CLI)"; \
		exit 2; \
	fi; \
	OUT="$(MBM_RENDER_OUT)"; \
	if [ -z "$$OUT" ]; then \
		echo "Set MBM_RENDER_OUT=output/path.png"; \
		exit 2; \
	fi; \
	mkdir -p "$$(dirname "$$OUT")"; \
	echo "MBM render: $(MBM_RENDER_MANIFEST) → $$OUT"; \
	if [ -n "$(MBM_RENDER_WRITE_BLEND)" ]; then \
		BLEND="$(MBM_RENDER_WRITE_BLEND)"; \
		mkdir -p "$$(dirname "$$BLEND")"; \
		$(GUIX_SHELL) -- blender -b --factory-startup --python "$(MBM_RENDER_CLI)" -- \
			--manifest "$(MBM_RENDER_MANIFEST)" --out "$$OUT" --write-blend "$$BLEND"; \
	else \
		$(GUIX_SHELL) -- blender -b --factory-startup --python "$(MBM_RENDER_CLI)" -- \
			--manifest "$(MBM_RENDER_MANIFEST)" --out "$$OUT"; \
	fi; \
	echo "Wrote $$OUT"

mbm-render-test:
	@$(MAKE) mbm-render \
		MBM_RENDER_MANIFEST="$(MBM_TEST_MANIFEST)" \
		MBM_RENDER_OUT="$(RENDERS_DIR)/mbm-test.png"

# Poster/layout -------------------------------------------------------------

poster: inkscape

inkscape: dirs
	@set -e; \
	SVG="$(POSTER_SVG)"; \
	if [ -z "$$SVG" ]; then \
		echo "No SVG found in poster/. Create poster/print.svg or poster/iposter.svg."; \
		exit 2; \
	fi; \
	echo "Opening Inkscape: $$SVG"; \
	$(GUIX_SHELL) -- inkscape "$$SVG"

poster-print: dirs
	@set -e; \
	if [ ! -f "$(POSTER_PRINT_SVG)" ]; then \
		echo "Missing $(POSTER_PRINT_SVG)."; \
		exit 2; \
	fi; \
	echo "Opening Inkscape: $(POSTER_PRINT_SVG)"; \
	$(GUIX_SHELL) -- inkscape "$(POSTER_PRINT_SVG)"

poster-iposter: dirs
	@set -e; \
	if [ ! -f "$(POSTER_IPOSTER_SVG)" ]; then \
		echo "Missing $(POSTER_IPOSTER_SVG)."; \
		exit 2; \
	fi; \
	echo "Opening Inkscape: $(POSTER_IPOSTER_SVG)"; \
	$(GUIX_SHELL) -- inkscape "$(POSTER_IPOSTER_SVG)"

gimp: dirs
	@set -e; \
	if [ -n "$(FILE)" ]; then \
		echo "Opening GIMP: $(FILE)"; \
		$(GUIX_SHELL) -- gimp "$(FILE)"; \
	else \
		echo "Opening GIMP"; \
		$(GUIX_SHELL) -- gimp; \
	fi

# Exports/helpers -----------------------------------------------------------

export-print-pdf: dirs
	@set -e; \
	if [ ! -f "$(POSTER_PRINT_SVG)" ]; then \
		echo "Missing $(POSTER_PRINT_SVG)."; \
		exit 2; \
	fi; \
	OUT="$(EXPORTS_DIR)/print.pdf"; \
	echo "Exporting $$OUT"; \
	$(GUIX_SHELL) -- inkscape --export-overwrite -o "$$OUT" "$(POSTER_PRINT_SVG)"

export-iposter-pdf: dirs
	@set -e; \
	if [ ! -f "$(POSTER_IPOSTER_SVG)" ]; then \
		echo "Missing $(POSTER_IPOSTER_SVG)."; \
		exit 2; \
	fi; \
	OUT="$(EXPORTS_DIR)/iposter.pdf"; \
	echo "Exporting $$OUT"; \
	$(GUIX_SHELL) -- inkscape --export-overwrite -o "$$OUT" "$(POSTER_IPOSTER_SVG)"

export-print-png: dirs
	@set -e; \
	if [ ! -f "$(POSTER_PRINT_SVG)" ]; then \
		echo "Missing $(POSTER_PRINT_SVG)."; \
		exit 2; \
	fi; \
	OUT="$(EXPORTS_DIR)/print-preview.png"; \
	echo "Exporting $$OUT (width=$(PREVIEW_W)px)"; \
	$(GUIX_SHELL) -- inkscape --export-overwrite -w $(PREVIEW_W) -o "$$OUT" "$(POSTER_PRINT_SVG)"

export-iposter-png: dirs
	@set -e; \
	if [ ! -f "$(POSTER_IPOSTER_SVG)" ]; then \
		echo "Missing $(POSTER_IPOSTER_SVG)."; \
		exit 2; \
	fi; \
	OUT="$(EXPORTS_DIR)/iposter-preview.png"; \
	echo "Exporting $$OUT (width=$(PREVIEW_W)px)"; \
	$(GUIX_SHELL) -- inkscape --export-overwrite -w $(PREVIEW_W) -o "$$OUT" "$(POSTER_IPOSTER_SVG)"

# Convert SVGs in DIR to "plain SVG" (handy for making the SVGs more portable)
svg-plain:
	@set -e; \
	DIR="$(DIR)"; \
	if [ -z "$$DIR" ]; then DIR="docs"; fi; \
	if [ ! -d "$$DIR" ]; then echo "No such DIR=$$DIR"; exit 2; fi; \
	echo "Converting $$DIR/*.svg → plain SVG (in-place)"; \
	$(GUIX_SHELL) -- sh -c 'ls "'$$DIR'"/*.svg >/dev/null 2>&1 && inkscape -D --export-overwrite --export-plain-svg "'$$DIR'"/*.svg || echo "(no .svg files found in $$DIR)"'

# Trim PNG whitespace in DIR (defaults to output/renders)
trim-png:
	@set -e; \
	DIR="$(DIR)"; \
	if [ -z "$$DIR" ]; then DIR="$(RENDERS_DIR)"; fi; \
	if [ ! -d "$$DIR" ]; then echo "No such DIR=$$DIR"; exit 2; fi; \
	echo "Trimming $$DIR/*.png (in-place)"; \
	$(GUIX_SHELL) -- sh -c 'ls "'$$DIR'"/*.png >/dev/null 2>&1 && mogrify -trim "'$$DIR'"/*.png || echo "(no .png files found in $$DIR)"'

# QR code helper:
#   make qr TEXT='https://example.com' OUT=output/renders/qr.png
qr: dirs
	@set -e; \
	if [ -z "$(TEXT)" ]; then echo "Set TEXT='...'"; exit 2; fi; \
	OUT="$(OUT)"; \
	if [ -z "$$OUT" ]; then OUT="$(RENDERS_DIR)/qr.png"; fi; \
	echo "Writing $$OUT"; \
	$(GUIX_SHELL) -- qrencode -o "$$OUT" "$(TEXT)"

# Openers (host OS) ---------------------------------------------------------

open:
	@set -e; \
	if [ -z "$(FILE)" ]; then echo "Usage: make open FILE=path"; exit 2; fi; \
	$(OPEN) "$(FILE)"

open-renders: dirs
	@$(OPEN) "$(RENDERS_DIR)"

open-exports: dirs
	@$(OPEN) "$(EXPORTS_DIR)"

open-cad:
	@$(OPEN) "$(REPO_ROOT)/cad"

open-poster:
	@$(OPEN) "$(REPO_ROOT)/poster"
