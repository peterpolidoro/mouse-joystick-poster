# P01 — Paper as final information artifact

## 0) Narrative role (why this panel exists)
This opening panel establishes the *end of the pipeline*: a peer‑reviewed paper.
The viewer should immediately understand that the entire science+mechatronics stack ultimately produces a durable information artifact (the paper),
and that MBM is about making the chain of boundary crossings that produce that artifact explicit.

**Incoming from previous panel:** — (first panel)

**Outgoing to next panel:** Let the information tether ‘aim’ toward the right edge (or bottom‑right) to cue flow into the next panel where the paper decomposes into figures/datasets.

---

## 1) Viewer takeaway (one sentence)
After 3 seconds, the viewer should be able to say what crosses the boundary here (power and/or information) and *what it becomes*.

---

## 2) What this panel MUST show (non‑negotiable)
- A single icosahedron boundary token representing “the system” as an abstract producer of information.
- ONE thin **information** tether (cyan accent) exiting the boundary and pointing directly to the **paper title page** (the artifact).
- The paper appears as a physical object (a printed page or floating glossy sheet), not a UI screenshot.

---

## 3) Composition & “Unflattening” cues (make it feel like a graphic novel)
- Semi‑realistic 3D scene with depth, perspective, and soft studio lighting.
- Use **one strong focal object** + a few supporting objects.
- Let tethers curve in **3D space** (not straight flat connectors).
- Boundaries are **3D icosahedron boundary tokens** (wireframe/strut platonic solids). Use vertex ports; keep the interior visible.
- Keep backgrounds clean (white/very light gray). Avoid heavy textures.

---

## 4) Assets YOU should upload in the panel‑generation chat

### Always upload
- `03_PANELS/_GLOBAL/global-context.md`
- `00_ADMIN/style-bible-white.md`
- This file: `03_PANELS/P01_paper_artifact/context.md` (the one you’re reading)

### Panel‑specific REQUIRED uploads
- [ ] A clean image of the **paper title page** (cropped screenshot from the PDF).

### Panel‑specific OPTIONAL uploads (helps accuracy)
- [ ] Any cover-art / journal branding you want to match (optional).
- [ ] A small icon/image of the joystick rig to hint at the physical origin (optional).

### Text info to paste into the chat (if you want accuracy)
- Paper title (exact).
- Author list (optional, can be omitted in the panel image).

---

## 5) Output spec (so it drops into the template cleanly)
- **Panel physical size in template:** ~9.38×10.94 inches
- **Aspect ratio (approx):** 0.857 (W/H)
- **Suggested render size:** 3511×4096 px (or the **largest** your image tool allows at this aspect ratio)
- Background: **transparent** preferred; otherwise pure white (#FFFFFF).
- Leave a ~3–5% safe margin inside edges (it will be clipped by the SVG mask).

---

## 6) Prompt block (copy/paste into the panel chat)
> Create ONE comic panel illustration (semi‑realistic 3D, print‑friendly on white) for a 48×48 inch poster.  
> Use the MBM grammar: boundaries are **3D icosahedron boundary tokens** (wireframe/strut platonic solids) with small connector nodes at vertices (ports). Replace arrow glyphs with **tangible 3D tethers**: **information** is a thin fiber/wire harness with cyan accent (#06B6D4) and tiny light pulses/beads indicating direction; **power** is a thicker braided cable or chain‑sleeved hose with amber accent (#F59E0B) and warm glow pulses indicating direction.  
> Avoid flat block-diagram aesthetics. Use perspective depth, soft shadows, and a clean white/very light background. Keep embedded text minimal (0–2 tiny labels max).  
> Use any uploaded reference images faithfully where applicable (paper title page, rig photo, PCB screenshot, etc.).  
> Panel content requirements:  
> > - A single icosahedron boundary token representing “the system” as an abstract producer of information.
> - ONE thin **information** tether (cyan accent) exiting the boundary and pointing directly to the **paper title page** (the artifact).
> - The paper appears as a physical object (a printed page or floating glossy sheet), not a UI screenshot.  
> Include a subtle transition cue toward the next panel: Let the information tether ‘aim’ toward the right edge (or bottom‑right) to cue flow into the next panel where the paper decomposes into figures/datasets.

---

## 7) Don’ts (negative constraints)
- No PowerPoint / UML / SysML block diagram look.
- No dense paragraphs of text inside the image.
- Don’t swap the color semantics (cyan=information, amber=power).
- Don’t render the boundary as a soap bubble or metallic sphere; it must read as a **wireframe/strut icosahedron boundary token** with vertex ports.
