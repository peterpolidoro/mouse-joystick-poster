# P07 — PCB internal boundaries: motor + brake control loops

## 0) Narrative role (why this panel exists)
This panel is where MBM becomes a design tool: inside the PCB, we draw smaller boundaries around functional units
(driver stage, sensing front-end, microcontroller domain).
The viewer should see at least two concrete closed loops: (1) joystick motor positioning/load, and (2) brake control,
each with command in, feedback out, and power delivered to a physical actuator.

**Incoming from previous panel:** Use a visual echo from the prior panel (artifacts, tethers, or boundary token) so the zoom feels continuous.

**Outgoing to next panel:** Let the MCU area glow subtly as a ‘portal’ into the next panel about firmware actors/state machines (P08).

---

## 1) Viewer takeaway (one sentence)
After 3 seconds, the viewer should be able to say what crosses the boundary here (power and/or information) and *what it becomes*.

---

## 2) What this panel MUST show (non‑negotiable)
- A 3D PCB as the stage (angled perspective, not a flat schematic).
- Two highlighted functional zones with their own small icosahedron boundary tokens or ring callouts:
- • Motor drive + feedback (stepper/encoder/switch)
- • Brake drive + feedback (current sense / status)
- Power tethers (amber) feeding the driver stages; info tethers (cyan) between MCU ↔ drivers ↔ sensors.

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
- This file: `03_PANELS/P07_pcb_functional_units/context.md` (the one you’re reading)

### Panel‑specific REQUIRED uploads
- [ ] PCB layout image (KiCad/Altium screenshot) OR a photo of the populated PCB.
- [ ] A short list of the 2–4 most important PCB functional units to feature.

### Panel‑specific OPTIONAL uploads (helps accuracy)
- [ ] Schematic snippets for the motor driver and brake driver sections.
- [ ] Images of the motor driver IC, brake driver components, or connectors.

### Text info to paste into the chat (if you want accuracy)
- Names of functional units (e.g., ‘MCU’, ‘Motor Driver’, ‘Brake Driver’, ‘Sensor ADC’).

---

## 5) Output spec (so it drops into the template cleanly)
- **Panel physical size in template:** ~17.19×9.69 inches
- **Aspect ratio (approx):** 1.774 (W/H)
- **Suggested render size:** 4096×2309 px (or the **largest** your image tool allows at this aspect ratio)
- Background: **transparent** preferred; otherwise pure white (#FFFFFF).
- Leave a ~3–5% safe margin inside edges (it will be clipped by the SVG mask).

---

## 6) Prompt block (copy/paste into the panel chat)
> Create ONE comic panel illustration (semi‑realistic 3D, print‑friendly on white) for a 48×48 inch poster.  
> Use the MBM grammar: boundaries are **3D icosahedron boundary tokens** (wireframe/strut platonic solids) with small connector nodes at vertices (ports). Replace arrow glyphs with **tangible 3D tethers**: **information** is a thin fiber/wire harness with cyan accent (#06B6D4) and tiny light pulses/beads indicating direction; **power** is a thicker braided cable or chain‑sleeved hose with amber accent (#F59E0B) and warm glow pulses indicating direction.  
> Avoid flat block-diagram aesthetics. Use perspective depth, soft shadows, and a clean white/very light background. Keep embedded text minimal (0–2 tiny labels max).  
> Use any uploaded reference images faithfully where applicable (paper title page, rig photo, PCB screenshot, etc.).  
> Panel content requirements:  
> > - A 3D PCB as the stage (angled perspective, not a flat schematic).
> - Two highlighted functional zones with their own small icosahedron boundary tokens or ring callouts:
> - • Motor drive + feedback (stepper/encoder/switch)
> - • Brake drive + feedback (current sense / status)
> - Power tethers (amber) feeding the driver stages; info tethers (cyan) between MCU ↔ drivers ↔ sensors.  
> Include a subtle transition cue toward the next panel: Let the MCU area glow subtly as a ‘portal’ into the next panel about firmware actors/state machines (P08).

---

## 7) Don’ts (negative constraints)
- No PowerPoint / UML / SysML block diagram look.
- No dense paragraphs of text inside the image.
- Don’t swap the color semantics (cyan=information, amber=power).
- Don’t render the boundary as a soap bubble or metallic sphere; it must read as a **wireframe/strut icosahedron boundary token** with vertex ports.
