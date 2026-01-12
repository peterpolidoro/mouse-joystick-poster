# mouse-joystick-poster — reproducible poster toolchain (Guix)
#
# Usage:
#   make help
#   make shell
#   make shell-pure
#   make lock-channels
#
# Notes:
# - Targets that spawn a shell will open an interactive subshell. Exit to return.
# - This Makefile intentionally keeps the environment layer (Guix) separate from
#   your CAD / render / layout workflow scripts, so you can adapt freely.

GUIX        ?= guix
CHANNELS    ?= guix/channels.scm
MANIFEST    ?= guix/manifest.scm

# Use user's default shell inside the Guix environment.
HOST_SHELL  ?= $(SHELL)

.PHONY: help shell shell-pure lock-channels describe guix-version

help:
	@printf "%s\n" \
	"Targets:" \
	"  make shell          Enter a Guix dev shell (impure; easiest for GUI apps)" \
	"  make shell-pure     Enter a pure Guix dev shell (more reproducible)" \
	"  make lock-channels  Pin guix/channels.scm to your current Guix revision" \
	"  make describe       Show the active Guix channels (for debugging)" \
	"  make guix-version   Show guix --version"

guix-version:
	@$(GUIX) --version

describe:
	@$(GUIX) describe

# Development shells ---------------------------------------------------------

# Impure shell:
# - Inherits your host environment (PATH, DISPLAY, Wayland vars, etc.)
# - Often the least-friction choice for GUI programs (KiCad/FreeCAD/Blender).
shell:
	@$(GUIX) time-machine -C $(CHANNELS) -- shell -m $(MANIFEST) -- $(HOST_SHELL)

# Pure shell:
# - Starts from a mostly clean environment; still passes through DISPLAY vars.
# - If GUI apps fail to find fonts/locales, see README.org troubleshooting.
shell-pure:
	@$(GUIX) time-machine -C $(CHANNELS) -- shell --pure -m $(MANIFEST) \
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

# Channel pinning ------------------------------------------------------------

# Writes an exact channels.scm (commit + intro) matching your current Guix.
# Commit this file to make the environment reproducible for others:
#   git add guix/channels.scm && git commit -m "Pin Guix channel revision"
lock-channels:
	@$(GUIX) describe --format=channels > $(CHANNELS)
	@echo "Wrote pinned channels to $(CHANNELS)"
