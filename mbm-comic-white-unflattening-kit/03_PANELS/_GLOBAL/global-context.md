# GLOBAL CONTEXT (paste or upload into every panel-generation chat)

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
- Represent every MBM boundary as a **3D brushed‑nickel armillary sphere** (intersecting rings forming a sphere).
- Boundary rings may be partial / occluded to keep the interior visible.
- Ports appear as small **metal collars** on the ring where arrows connect.

**Flows**
- **Information**: thin metallic 3D arrows/tubes with **cyan accent** (#06B6D4).
  - Think: anodized titanium/aluminum with cyan inlay.
- **Power**: thick metallic 3D arrows/tubes with **amber accent** (#F59E0B).
  - Think: copper/brass with warm amber inlay.
- Optional **dissipation / entropy export**: faint heat shimmer or red haze (#DC2626), subtle.

**Artifacts**
- “Paper”, “Figures”, “Datasets”, “Configs” are **physical objects** (glass cards, acrylic slabs, data crystals).
- Artifacts should feel like they come *from* the system boundary, not like floating UI screenshots.

---

## C) Style (white paper, print friendly)

- Background: **white or transparent**.
- Lighting: soft studio light + mild rim light.
- Use soft shadows; avoid heavy black fills.
- Minimal text inside the rendered panel image (0–2 tiny labels max).

---

## D) Reusable visual motifs (helps continuity)

- **Cyan = information**, **Amber = power** (never swap).
- Nickel boundary spheres recur at every scale.
- “Data crystals / glass cards” recur wherever artifacts appear.
- Transition cue: arrows that point toward a panel edge can “imply” continuation into the next panel.

---

## E) When you lack a reference asset

If a required reference image isn’t available yet:
- substitute a **generic but believable** placeholder (generic PCB, generic stepper motor, generic chart thumbnails),
- keep composition + arrow grammar correct,
- leave open space for later replacement in Inkscape if needed.
