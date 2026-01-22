# P08 — Firmware: actors + hierarchical state machines

## 0) Narrative role (why this panel exists)
This panel explains why the system behaves deterministically and safely: firmware is an organized society of actors/state machines.
Instead of a code listing, show firmware as a spatial, layered control structure running inside the microcontroller,
coordinating timing, safety, and experiment orchestration.

**Incoming from previous panel:** Use a visual echo from the prior panel (artifacts, tethers, or boundary token) so the zoom feels continuous.

**Outgoing to next panel:** Have one actor/state machine connect outward to an actuator boundary (P09).

---

## 1) Viewer takeaway (one sentence)
After 3 seconds, the viewer should be able to say what crosses the boundary here (power and/or information) and *what it becomes*.

---

## 2) What this panel MUST show (non‑negotiable)
- A microcontroller chip (or PCB MCU region) as a physical object.
- Inside/around it, a diagram-like but 3D “hologram” of actors (nodes) and state machine layers (stacked translucent planes).
- Information tethers (cyan) representing events/messages between actors.
- Power is mostly implicit here (avoid heavy power tethers).

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
- This file: `03_PANELS/P08_firmware_actors_hsm/context.md` (the one you’re reading)

### Panel‑specific REQUIRED uploads
- [ ] A list of firmware ‘actors’ (or modules) and what they do.
- [ ] A rough state diagram screenshot OR a text description of main states (Idle, Armed, Trial, Fault, etc.).

### Panel‑specific OPTIONAL uploads (helps accuracy)
- [ ] Any existing state machine diagrams or QP actor diagrams.
- [ ] Timing details (loop rate, interrupt cadence) if you want a tiny label.

### Text info to paste into the chat (if you want accuracy)
- Actor names (e.g., ‘MotorCtrl’, ‘BrakeCtrl’, ‘Logger’, ‘TrialManager’, ‘Safety’).
- Key states/events (e.g., ReachStart, PullThreshold, Reward).

---

## 5) Output spec (so it drops into the template cleanly)
- **Panel physical size in template:** ~9.90×7.08 inches
- **Aspect ratio (approx):** 1.397 (W/H)
- **Suggested render size:** 4096×2932 px (or the **largest** your image tool allows at this aspect ratio)
- Background: **transparent** preferred; otherwise pure white (#FFFFFF).
- Leave a ~3–5% safe margin inside edges (it will be clipped by the SVG mask).

---

## 6) Prompt block (copy/paste into the panel chat)
> Create ONE comic panel illustration (semi‑realistic 3D, print‑friendly on white) for a 48×48 inch poster.  
> Use the MBM grammar: boundaries are **3D icosahedron boundary tokens** (wireframe/strut platonic solids) with small connector nodes at vertices (ports). Replace arrow glyphs with **tangible 3D tethers**: **information** is a thin fiber/wire harness with cyan accent (#06B6D4) and tiny light pulses/beads indicating direction; **power** is a thicker braided cable or chain‑sleeved hose with amber accent (#F59E0B) and warm glow pulses indicating direction.  
> Avoid flat block-diagram aesthetics. Use perspective depth, soft shadows, and a clean white/very light background. Keep embedded text minimal (0–2 tiny labels max).  
> Use any uploaded reference images faithfully where applicable (paper title page, rig photo, PCB screenshot, etc.).  
> Panel content requirements:  
> > - A microcontroller chip (or PCB MCU region) as a physical object.
> - Inside/around it, a diagram-like but 3D “hologram” of actors (nodes) and state machine layers (stacked translucent planes).
> - Information tethers (cyan) representing events/messages between actors.
> - Power is mostly implicit here (avoid heavy power tethers).  
> Include a subtle transition cue toward the next panel: Have one actor/state machine connect outward to an actuator boundary (P09).

---

## 7) Don’ts (negative constraints)
- No PowerPoint / UML / SysML block diagram look.
- No dense paragraphs of text inside the image.
- Don’t swap the color semantics (cyan=information, amber=power).
- Don’t render the boundary as a soap bubble or metallic sphere; it must read as a **wireframe/strut icosahedron boundary token** with vertex ports.
