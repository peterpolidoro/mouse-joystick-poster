# GLOBAL CONTEXT (upload into every panel-generation chat)

This file defines the **shared story + visual grammar** across all panels so each panel can be generated in an independent chat but still looks like one coherent comic.

---

## A) Poster story (one-sentence arc)

**Science with Mechatronics: _power + information → datasets → papers_.**

We zoom inward through **nested boundaries**:
system → rig → PCB → firmware → actuator → theory.

Each panel should feel like a *camera move* (closer / more specific boundary), not like “another block diagram.”

---

## B) MBM grammar (fixed meaning)

**Boundaries**
- Represent every MBM boundary as a **3D icosahedron boundary token** (platonic solid).
- Prefer a **wireframe/strut icosahedron** (thin rods + corner nodes) so the viewer can see the interior.
- Boundaries can be nested: a smaller icosahedron inside a larger one (optional when it helps tell the zoom story).

**Ports**
- Ports live at **icosahedron vertices**.
- Active vertices show a small **connector node / jack** (a little port puck/grommet).
- Port rims are color-coded:
  - **cyan rim = information**
  - **amber rim = power**
  - split rim if both.

**Flows (no arrow glyphs; use tangible tethers)**
- **Information**: thin **fiber/wire harness** with cyan accent (#06B6D4).
  - Show direction with tiny moving **light pulses / beads** along the tether.
- **Power**: thicker **braided cable** or **chain‑sleeved hose** with amber accent (#F59E0B).
  - Show direction with warm glow pulses or a subtle heat gradient.
- A single port can carry both (allowed). Show two parallel tethers or one dual-accent tether.

**Artifacts**
- “Paper”, “Figures”, “Datasets”, “Configs” are **physical objects** (glass cards, acrylic slabs, data crystals).
- Artifacts should feel like they come *from* the system boundary, not like floating UI screenshots.

**Optional (Panel 10 / theory)**
- Dissipation / entropy export: subtle heat shimmer or faint red haze (#DC2626). Keep it secondary.

---

## C) Style (white paper, print friendly)

- Background: **white or transparent**.
- Lighting: soft studio light + mild rim light.
- Use soft shadows; avoid heavy black fills.
- Minimal text inside the rendered panel image (0–2 tiny labels max).

---

## D) Reusable visual motifs (continuity)

- **Cyan = information**, **Amber = power** (never swap).
- Icosahedron boundary tokens recur at every scale.
- “Data crystals / glass cards” recur wherever artifacts appear.
- Transition cue: tethers that point toward a panel edge can imply continuation into the next panel.

---

## E) When you lack a reference asset

If a required reference image isn’t available yet:
- substitute a **generic but believable** placeholder (generic PCB, generic stepper motor, generic chart thumbnails),
- keep composition + tether grammar correct,
- leave open space for later replacement in Inkscape if needed.
