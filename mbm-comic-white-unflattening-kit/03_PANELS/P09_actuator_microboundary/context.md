# P09 — Micro-boundary: a single actuator (motor or brake)

## 0) Narrative role (why this panel exists)
This panel proves scale‑invariance: the same MBM grammar works at the smallest scale.
A motor/brake is a boundary: electrical power in, mechanical power out, information in (commands) and out (feedback/encoder/current sense),
with inevitable dissipation.

**Incoming from previous panel:** Use a visual echo from the prior panel (artifacts, arrows, or boundary sphere) so the zoom feels continuous.

**Outgoing to next panel:** Let the dissipation hint/heat shimmer guide into the final theory panel (P10).

---

## 1) Viewer takeaway (one sentence)
After 3 seconds, the viewer should be able to say what crosses the boundary here (power and/or information) and *what it becomes*.

---

## 2) What this panel MUST show (non‑negotiable)
- A close-up, semi-realistic 3D depiction of ONE actuator (choose stepper motor OR brake).
- A small brushed‑nickel boundary sphere around the actuator.
- Power arrow (amber) entering electrically; mechanical output implied (shaft/torque) possibly as a subtle arrow.
- Information arrow(s) (cyan) for command in and sensor feedback out (encoder, limit switch, current sense).
- Optional: tiny red heat shimmer as dissipation.

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
- This file: `03_PANELS/P09_actuator_microboundary/context.md` (the one you’re reading)

### Panel‑specific REQUIRED uploads
- [ ] A photo or datasheet image of the stepper motor or brake you want depicted (one is enough).

### Panel‑specific OPTIONAL uploads (helps accuracy)
- [ ] Wiring diagram/pinout (optional).
- [ ] Encoder/limit switch photo if separate.

### Text info to paste into the chat (if you want accuracy)
- Actuator name (e.g., ‘Pitch Stepper’, ‘Brake’).
- Feedback signals (encoder A/B, switch, current sense).

---

## 5) Output spec (so it drops into the template cleanly)
- **Panel physical size in template:** ~8.12×8.12 inches
- **Aspect ratio (approx):** 1.000 (W/H)
- **Suggested render size:** 4096×4096 px (or the **largest** your image tool allows at this aspect ratio)
- Background: **transparent** preferred; otherwise pure white (#FFFFFF).
- Leave a ~3–5% safe margin inside edges (it will be clipped by the SVG mask).

---

## 6) Prompt block (copy/paste into the panel chat)
> Create ONE comic panel illustration (semi‑realistic 3D, print‑friendly on white) for a 48×48 inch poster.  
> Use the MBM grammar: boundaries are **3D brushed‑nickel armillary spheres** with small port collars; **information** crossings are thin metallic arrows/tubes with a cyan accent (#06B6D4); **power** crossings are thicker metallic arrows/tubes with an amber accent (#F59E0B).  
> Avoid flat block-diagram aesthetics. Use perspective depth, soft shadows, and a clean white/very light background. Keep embedded text minimal (0–2 tiny labels max).  
> Use any uploaded reference images faithfully where applicable (paper title page, rig photo, PCB screenshot, etc.).  
> Panel content requirements:  
> > - A close-up, semi-realistic 3D depiction of ONE actuator (choose stepper motor OR brake).
> - A small brushed‑nickel boundary sphere around the actuator.
> - Power arrow (amber) entering electrically; mechanical output implied (shaft/torque) possibly as a subtle arrow.
> - Information arrow(s) (cyan) for command in and sensor feedback out (encoder, limit switch, current sense).
> - Optional: tiny red heat shimmer as dissipation.  
> Include a subtle transition cue toward the next panel: Let the dissipation hint/heat shimmer guide into the final theory panel (P10).

---

## 7) Don’ts (negative constraints)
- No PowerPoint / UML / SysML block diagram look.
- No dense paragraphs of text inside the image.
- Don’t swap the color semantics (cyan=information, amber=power).
- Don’t make the boundary a soap-bubble rainbow; it must read as **brushed nickel metal**.
