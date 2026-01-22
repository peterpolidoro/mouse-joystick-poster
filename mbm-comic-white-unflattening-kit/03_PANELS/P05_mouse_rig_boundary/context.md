# P05 — Boundary around mouse + joystick rig + sensors/actuators

## 0) Narrative role (why this panel exists)
This panel foregrounds the *biophysical interface*: the mouse interacting with the joystick while the rig senses and actuates.
The viewer should feel that “the experiment” is a coupled cyber-physical system: mechanics + animal + sensors + actuators,
and that meaningful information (events, kinematics, force) is created at this boundary.

**Incoming from previous panel:** Use a visual echo from the prior panel (artifacts, tethers, or boundary token) so the zoom feels continuous.

**Outgoing to next panel:** Let one cable/tether lead out toward the electronics/PCB (P06).

---

## 1) Viewer takeaway (one sentence)
After 3 seconds, the viewer should be able to say what crosses the boundary here (power and/or information) and *what it becomes*.

---

## 2) What this panel MUST show (non‑negotiable)
- A icosahedron boundary token enclosing the mouse + joystick rig (or a simplified mouse silhouette if you prefer).
- Clearly visible joystick end-effector and at least one sensor/actuator element (motor/brake/encoder).
- Info tethers (cyan) exiting the boundary labeled by *types* of information (e.g., kinematics, force, events) — labels optional.
- Power tethers (amber) entering the boundary to actuators (motor/brake).

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
- This file: `03_PANELS/P05_mouse_rig_boundary/context.md` (the one you’re reading)

### Panel‑specific REQUIRED uploads
- [ ] A reference image/render of the joystick apparatus (Figure crop from the paper works well).

### Panel‑specific OPTIONAL uploads (helps accuracy)
- [ ] A photo of the real rig in the lab.
- [ ] Any preferred depiction style for the mouse (photo, silhouette, stylized).

### Text info to paste into the chat (if you want accuracy)
- List of sensors at the rig boundary (encoder, force sensor, cameras, etc.).
- List of actuators at the rig boundary (stepper motors, brake).

---

## 5) Output spec (so it drops into the template cleanly)
- **Panel physical size in template:** ~15.62×15.10 inches
- **Aspect ratio (approx):** 1.034 (W/H)
- **Suggested render size:** 4096×3959 px (or the **largest** your image tool allows at this aspect ratio)
- Background: **transparent** preferred; otherwise pure white (#FFFFFF).
- Leave a ~3–5% safe margin inside edges (it will be clipped by the SVG mask).

---

## 6) Prompt block (copy/paste into the panel chat)
> Create ONE comic panel illustration (semi‑realistic 3D, print‑friendly on white) for a 48×48 inch poster.  
> Use the MBM grammar: boundaries are **3D icosahedron boundary tokens** (wireframe/strut platonic solids) with small connector nodes at vertices (ports). Replace arrow glyphs with **tangible 3D tethers**: **information** is a thin fiber/wire harness with cyan accent (#06B6D4) and tiny light pulses/beads indicating direction; **power** is a thicker braided cable or chain‑sleeved hose with amber accent (#F59E0B) and warm glow pulses indicating direction.  
> Avoid flat block-diagram aesthetics. Use perspective depth, soft shadows, and a clean white/very light background. Keep embedded text minimal (0–2 tiny labels max).  
> Use any uploaded reference images faithfully where applicable (paper title page, rig photo, PCB screenshot, etc.).  
> Panel content requirements:  
> > - A icosahedron boundary token enclosing the mouse + joystick rig (or a simplified mouse silhouette if you prefer).
> - Clearly visible joystick end-effector and at least one sensor/actuator element (motor/brake/encoder).
> - Info tethers (cyan) exiting the boundary labeled by *types* of information (e.g., kinematics, force, events) — labels optional.
> - Power tethers (amber) entering the boundary to actuators (motor/brake).  
> Include a subtle transition cue toward the next panel: Let one cable/tether lead out toward the electronics/PCB (P06).

---

## 7) Don’ts (negative constraints)
- No PowerPoint / UML / SysML block diagram look.
- No dense paragraphs of text inside the image.
- Don’t swap the color semantics (cyan=information, amber=power).
- Don’t render the boundary as a soap bubble or metallic sphere; it must read as a **wireframe/strut icosahedron boundary token** with vertex ports.
