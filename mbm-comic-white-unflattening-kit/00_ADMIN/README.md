# MBM Comic Poster — Project Kit (White Paper + Metallic Boundaries)

You will generate **10 panel images** in 10 separate chats, then place them into the Inkscape template.
The panels are designed to read like a **graphic novel page** (non-uniform layout) rather than a traditional poster.

---

## 1) Quick start (Inkscape)

1. Open: `01_INKSCAPE/mbm-comic-poster-template-unflattening-white.svg`
2. Keep the folder structure intact so linked assets stay linked:
   - Title bar: `02_ASSETS/titlebar/poster-title.png`
3. Insert each panel image:
   - `File → Import…` and pick `P01.png` (etc.)
   - Move the image above the correct panel group.
   - Select the imported image, then *Shift-select* that panel’s `PXX_CLIP` shape (an invisible clipping shape).
   - `Object → Clip → Set`
   - The panel’s `PXX_FRAME` stroke stays visible as the border.
4. Repeat for P01…P10.
5. Edit the footer band (authors/affiliations/QRs) in the `FOOTER` layer.
6. Export for print:
   - `File → Save As…` PDF (recommended), or
   - `File → Export…` PNG at 300 dpi.

---

## 2) Generating each panel image (10 separate chats)

For each panel **PXX**, upload (or paste):

**Always**
- `03_PANELS/_GLOBAL/global-context.md`
- `00_ADMIN/style-bible-white.md`
- The panel’s context file: `03_PANELS/PXX_*/context.md`

**Plus panel-specific references**
- Photos / screenshots / CAD renders / figure crops listed in that panel’s `context.md`.

Then prompt the model with something like:
> “Generate the panel image following global-context.md and this panel’s context.md.”

### Core visual grammar (what every panel must obey)
- Boundaries = **3D brushed‑nickel armillary spheres**
- Information arrows = **thin metallic arrows with cyan accent**
- Power arrows = **thick metallic arrows with amber accent**
- Background = **white/transparent**, print friendly
- Avoid flat block diagrams

---

## 3) Files you will create as outputs

Save each generated panel image as:
- `03_PANELS/PXX_*/output/PXX.png`

Use the naming `P01.png` … `P10.png` exactly — the SVG labels match.

---

## 4) Optional style references

- `02_ASSETS/style/palette-white.svg`
- `02_ASSETS/style/arrow-grammar.svg`
