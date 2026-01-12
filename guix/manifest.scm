;; manifest.scm — poster toolchain for mouse-joystick-poster
;;
;; Enter with:
;;   make shell
;;   make shell-pure
;;
;; Notes:
;; - Some GUI apps rely on host graphics drivers; Guix manages userland packages.
;; - Fonts/locales/certificates are included because they commonly bite "pure" shells.

(use-modules (guix packages)
             (guix profiles))

(packages->manifest
 (list
  ;; CAD / EDA / rendering
  freecad
  blender
  kicad
  kicad-doc
  kicad-symbols
  kicad-footprints
  kicad-packages3d
  kicad-templates

  ;; Layout / raster+vector
  inkscape
  gimp

  ;; Conversions / export helpers
  imagemagick
  ghostscript
  poppler
  ffmpeg
  qrencode

  ;; Version control helpers
  git
  git-lfs

  ;; Common runtime needs for GUI apps in (some) Guix shells
  fontconfig
  font-dejavu
  font-gnu-freefont
  font-ghostscript
  glibc-locales
  nss-certs

  ;; Quality-of-life tools
  bash
  coreutils
  findutils
  grep
  sed
  gawk
  less
  which
  file
  ))
