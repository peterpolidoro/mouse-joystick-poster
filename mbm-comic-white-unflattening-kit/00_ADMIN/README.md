# MBM Comic Poster (White / Unflattening Layout) — Project Kit

You will generate **10 panel images** in 10 separate chats, then place them into the Inkscape template.

## Quick start (Inkscape)
1. Open: `01_INKSCAPE/mbm-comic-poster-template-unflattening-white.svg`
2. Keep the folder structure intact so the title bar image stays linked:
   - `02_ASSETS/titlebar/poster-title.png`
3. Insert each panel image:
   - `File → Import…` and pick `P01.png` (etc.)
   - Move the image above the correct panel group.
   - Select the imported image, then *Shift-select* the panel’s `PXX_CLIP` shape (it’s an invisible shape in that panel group).
   - `Object → Clip → Set`
   - The panel’s `PXX_FRAME` stroke stays visible as the border.
4. Repeat for P01…P10.
5. Edit the footer band (authors/affiliations/QRs) in the `FOOTER` layer.
6. Export for print:
   - `File → Save As…` PDF (recommended), or
   - `File → Export…` PNG at 300 dpi.

## Generating each panel image (10 separate chats)
For each panel **PXX**, upload:
- `03_PANELS/_GLOBAL/global-context.md` (or paste it)
- `00_ADMIN/style-bible-white.md` (optional but helps consistency)
- The panel’s context file: `03_PANELS/PXX_*/context.md`
- Any panel-specific reference images listed inside that context file (photos, figure crops, etc.)

Then prompt the model: “Generate the panel image following the attached context.md and global-context.md.”

## Files you will create as outputs
Save each generated panel image as:
- `03_PANELS/PXX_*/output/PXX.png`

Use the naming `P01.png` … `P10.png` exactly — the SVG labels match.

## Helpful style references
- `02_ASSETS/style/palette-white.svg`
- `02_ASSETS/style/arrow-grammar.svg`
