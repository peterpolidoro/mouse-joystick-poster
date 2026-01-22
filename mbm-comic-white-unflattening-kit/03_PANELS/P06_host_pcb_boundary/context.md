# P06 — Boundary between host computer and PCB: protocol vs power

## 0) Narrative role (why this panel exists)
This panel makes a clean MBM point: the host/PC and the embedded PCB are separated by a boundary where **information** (commands, telemetry)
and **power** (supply rails) cross in very different ways.
The viewer should understand that datasets emerge because the protocol boundary is explicit and well-designed, not accidental.

**Incoming from previous panel:** Use a visual echo from the prior panel (artifacts, arrows, or boundary sphere) so the zoom feels continuous.

**Outgoing to next panel:** Visually push the viewer toward the PCB surface so the next panel can dive into PCB functional units (P07).

---

## 1) Viewer takeaway (one sentence)
After 3 seconds, the viewer should be able to say what crosses the boundary here (power and/or information) and *what it becomes*.

---

## 2) What this panel MUST show (non‑negotiable)
- A brushed‑nickel boundary sphere around the PCB (or around the host↔PCB link, whichever reads better).
- Host computer on one side; PCB on the other; a cable between them.
- **Information** arrows (cyan) along the data link: commands → PCB, telemetry/events → host.
- **Power** arrow (amber) entering the PCB from a supply connector/rail.
- Keep this panel uncluttered: 2–4 arrows total.

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
- This file: `03_PANELS/P06_host_pcb_boundary/context.md` (the one you’re reading)

### Panel‑specific REQUIRED uploads
- [ ] A top-down photo, render, or board-view screenshot of your PCB (preferred).

### Panel‑specific OPTIONAL uploads (helps accuracy)
- [ ] Connector pinout image or photo of the wiring harness.
- [ ] A short description of the protocol (USB, UART, SPI, etc.).
- [ ] Voltage/current info (for labeling).

### Text info to paste into the chat (if you want accuracy)
- Protocol name(s).
- Supply rail(s) (e.g., 5V logic, 12V motor).

---

## 5) Output spec (so it drops into the template cleanly)
- **Panel physical size in template:** ~14.38×7.08 inches
- **Aspect ratio (approx):** 2.029 (W/H)
- **Suggested render size:** 4096×2018 px (or the **largest** your image tool allows at this aspect ratio)
- Background: **transparent** preferred; otherwise pure white (#FFFFFF).
- Leave a ~3–5% safe margin inside edges (it will be clipped by the SVG mask).

---

## 6) Prompt block (copy/paste into the panel chat)
> Create ONE comic panel illustration (semi‑realistic 3D, print‑friendly on white) for a 48×48 inch poster.  
> Use the MBM grammar: boundaries are **3D brushed‑nickel armillary spheres** with small port collars; **information** crossings are thin metallic arrows/tubes with a cyan accent (#06B6D4); **power** crossings are thicker metallic arrows/tubes with an amber accent (#F59E0B).  
> Avoid flat block-diagram aesthetics. Use perspective depth, soft shadows, and a clean white/very light background. Keep embedded text minimal (0–2 tiny labels max).  
> Use any uploaded reference images faithfully where applicable (paper title page, rig photo, PCB screenshot, etc.).  
> Panel content requirements:  
> > - A brushed‑nickel boundary sphere around the PCB (or around the host↔PCB link, whichever reads better).
> - Host computer on one side; PCB on the other; a cable between them.
> - **Information** arrows (cyan) along the data link: commands → PCB, telemetry/events → host.
> - **Power** arrow (amber) entering the PCB from a supply connector/rail.
> - Keep this panel uncluttered: 2–4 arrows total.  
> Include a subtle transition cue toward the next panel: Visually push the viewer toward the PCB surface so the next panel can dive into PCB functional units (P07).

---

## 7) Don’ts (negative constraints)
- No PowerPoint / UML / SysML block diagram look.
- No dense paragraphs of text inside the image.
- Don’t swap the color semantics (cyan=information, amber=power).
- Don’t make the boundary a soap-bubble rainbow; it must read as **brushed nickel metal**.
