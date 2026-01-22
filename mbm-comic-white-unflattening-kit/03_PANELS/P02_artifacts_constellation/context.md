# P02 — Artifacts constellation: datasets + figures as first‑class outputs

## 0) Narrative role (why this panel exists)
This panel reframes the “paper” as a bundle of intermediate artifacts: figures, datasets, code outputs.
The viewer should feel that the system doesn’t just make hardware signals — it makes *organized information products* that travel across boundaries.
This is the bridge between the high-level paper artifact (P01) and the deeper decomposition into variables/transducers (P03).

**Incoming from previous panel:** Use a visual echo from the prior panel (artifacts, arrows, or boundary sphere) so the zoom feels continuous.

**Outgoing to next panel:** Have a few artifacts ‘dissolve’ into symbols (x(t), F, θ) or sensor icons near the bottom/side to cue the variable/transducer reduction in P03.

---

## 1) Viewer takeaway (one sentence)
After 3 seconds, the viewer should be able to say what crosses the boundary here (power and/or information) and *what it becomes*.

---

## 2) What this panel MUST show (non‑negotiable)
- A brushed‑nickel boundary sphere representing the overall pipeline.
- Multiple thin metallic **information** arrows (cyan accent) radiating from the boundary to a *constellation* of artifacts:
- • figure thumbnails as framed glass panels
- • dataset objects as stacked translucent ‘data crystals’ or file blocks
- Optional: a subtle ‘paper’ object from P01 in the background or partially off-frame, implying this is the paper unpacked.

---

## 3) Composition & “Unflattening” cues (make it feel like a graphic novel)
- Semi‑realistic 3D scene with depth, perspective, and soft studio lighting.
- Use **one strong focal object** + a few supporting objects.
- Let arrows curve in **3D space** (not straight flat connectors).
- Boundaries are **brushed‑nickel armillary spheres** (intersecting rings). Keep the interior visible.
- Keep backgrounds clean (white/very light gray). Avoid heavy textures.

---

## 4) Assets YOU should upload in the panel‑generation chat

### Always upload
- `03_PANELS/_GLOBAL/global-context.md`
- `00_ADMIN/style-bible-white.md`
- This file: `03_PANELS/P02_artifacts_constellation/context.md` (the one you’re reading)

### Panel‑specific REQUIRED uploads
- [ ] 3–8 figure thumbnails or crops (from the paper) OR a single collage image of figures.
- [ ] 1–3 dataset exemplars (screenshots of file trees, HDF5 structure, or even placeholder ‘dataset’ icons if you prefer).

### Panel‑specific OPTIONAL uploads (helps accuracy)
- [ ] A screenshot/crop of the paper title page (so the panel can visually link back to P01).
- [ ] A short list of dataset names (e.g., ‘session_YYMMDD_mouseX…’).

### Text info to paste into the chat (if you want accuracy)
- A short label for the artifact cluster (e.g., ‘Figures’, ‘Datasets’). Optional — can be left blank.

---

## 5) Output spec (so it drops into the template cleanly)
- **Panel physical size in template:** ~26.04×13.44 inches
- **Aspect ratio (approx):** 1.938 (W/H)
- **Suggested render size:** 4096×2114 px (or the **largest** your image tool allows at this aspect ratio)
- Background: **transparent** preferred; otherwise pure white (#FFFFFF).
- Leave a ~3–5% safe margin inside edges (it will be clipped by the SVG mask).

---

## 6) Prompt block (copy/paste into the panel chat)
> Create ONE comic panel illustration (semi‑realistic 3D, print‑friendly on white) for a 48×48 inch poster.  
> Use the MBM grammar: boundaries are **3D brushed‑nickel armillary spheres** with small port collars; **information** crossings are thin metallic arrows/tubes with a cyan accent (#06B6D4); **power** crossings are thicker metallic arrows/tubes with an amber accent (#F59E0B).  
> Avoid flat block-diagram aesthetics. Use perspective depth, soft shadows, and a clean white/very light background. Keep embedded text minimal (0–2 tiny labels max).  
> Use any uploaded reference images faithfully where applicable (paper title page, rig photo, PCB screenshot, etc.).  
> Panel content requirements:  
> > - A brushed‑nickel boundary sphere representing the overall pipeline.
> - Multiple thin metallic **information** arrows (cyan accent) radiating from the boundary to a *constellation* of artifacts:
> - • figure thumbnails as framed glass panels
> - • dataset objects as stacked translucent ‘data crystals’ or file blocks
> - Optional: a subtle ‘paper’ object from P01 in the background or partially off-frame, implying this is the paper unpacked.  
> Include a subtle transition cue toward the next panel: Have a few artifacts ‘dissolve’ into symbols (x(t), F, θ) or sensor icons near the bottom/side to cue the variable/transducer reduction in P03.

---

## 7) Don’ts (negative constraints)
- No PowerPoint / UML / SysML block diagram look.
- No dense paragraphs of text inside the image.
- Don’t swap the color semantics (cyan=information, amber=power).
- Don’t make the boundary a soap-bubble rainbow; it must read as **brushed nickel metal**.
