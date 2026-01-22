# P03 — Reduce artifacts to variables + transducers

## 0) Narrative role (why this panel exists)
This panel performs the key conceptual compression: figures/datasets are built from *measured and controlled variables*,
and those variables only exist because transducers convert physical reality into signals (and signals back into physical action).
The viewer should feel a ‘zoom’ from floating artifacts to a more technical but still cinematic layer: symbols + sensors + actuators.

**Incoming from previous panel:** Use a visual echo from the prior panel (artifacts, tethers, or boundary token) so the zoom feels continuous.

**Outgoing to next panel:** Let the variable/transducer cluster ‘pull’ the camera toward the physical rig boundary in P04/P05 (e.g., a motor icon enlarged near one edge).

---

## 1) Viewer takeaway (one sentence)
After 3 seconds, the viewer should be able to say what crosses the boundary here (power and/or information) and *what it becomes*.

---

## 2) What this panel MUST show (non‑negotiable)
- A few artifact objects from P02 in the background/edge, breaking apart into:
- • variable symbols (force F, position x, velocity, angle θ, time stamps, events)
- • transducer icons (encoder, load cell/force sensor, motor, brake, camera)
- One or more small icosahedron boundary tokens around a ‘measurement/control layer’ subset (optional).
- Information tethers linking transducers → variables → artifacts (cyan). Power tethers should be minimal here (save for later panels).

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
- This file: `03_PANELS/P03_variables_transducers/context.md` (the one you’re reading)

### Panel‑specific REQUIRED uploads
- [ ] A list of the **key variables** (measured + controlled).
- [ ] A list of the **transducers/actuators** (sensor/actuator names).

### Panel‑specific OPTIONAL uploads (helps accuracy)
- [ ] Photos or renders of the encoder, stepper motor, brake, load cell, etc.
- [ ] A crop of a figure panel that shows variables (e.g., kinematics/force traces) for authenticity.

### Text info to paste into the chat (if you want accuracy)
- Variable names with units if you care (e.g., x [mm], F [g], θ [deg], t [ms]).
- Event names (e.g., reach start, pull threshold, reward).

---

## 5) Output spec (so it drops into the template cleanly)
- **Panel physical size in template:** ~7.92×10.73 inches
- **Aspect ratio (approx):** 0.738 (W/H)
- **Suggested render size:** 3022×4096 px (or the **largest** your image tool allows at this aspect ratio)
- Background: **transparent** preferred; otherwise pure white (#FFFFFF).
- Leave a ~3–5% safe margin inside edges (it will be clipped by the SVG mask).

---

## 6) Prompt block (copy/paste into the panel chat)
> Create ONE comic panel illustration (semi‑realistic 3D, print‑friendly on white) for a 48×48 inch poster.  
> Use the MBM grammar: boundaries are **3D icosahedron boundary tokens** (wireframe/strut platonic solids) with small connector nodes at vertices (ports). Replace arrow glyphs with **tangible 3D tethers**: **information** is a thin fiber/wire harness with cyan accent (#06B6D4) and tiny light pulses/beads indicating direction; **power** is a thicker braided cable or chain‑sleeved hose with amber accent (#F59E0B) and warm glow pulses indicating direction.  
> Avoid flat block-diagram aesthetics. Use perspective depth, soft shadows, and a clean white/very light background. Keep embedded text minimal (0–2 tiny labels max).  
> Use any uploaded reference images faithfully where applicable (paper title page, rig photo, PCB screenshot, etc.).  
> Panel content requirements:  
> > - A few artifact objects from P02 in the background/edge, breaking apart into:
> - • variable symbols (force F, position x, velocity, angle θ, time stamps, events)
> - • transducer icons (encoder, load cell/force sensor, motor, brake, camera)
> - One or more small icosahedron boundary tokens around a ‘measurement/control layer’ subset (optional).
> - Information tethers linking transducers → variables → artifacts (cyan). Power tethers should be minimal here (save for later panels).  
> Include a subtle transition cue toward the next panel: Let the variable/transducer cluster ‘pull’ the camera toward the physical rig boundary in P04/P05 (e.g., a motor icon enlarged near one edge).

---

## 7) Don’ts (negative constraints)
- No PowerPoint / UML / SysML block diagram look.
- No dense paragraphs of text inside the image.
- Don’t swap the color semantics (cyan=information, amber=power).
- Don’t render the boundary as a soap bubble or metallic sphere; it must read as a **wireframe/strut icosahedron boundary token** with vertex ports.
