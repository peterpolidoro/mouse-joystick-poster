# Mouse Joystick Poster — Context + Current Decisions (Print 48×48)

**Last updated:** 2026-01-20

This file captures the *current, agreed direction* for a printed engineering-forward poster about a **mouse pull joystick experimental rig** and the broader value proposition: **Science with Mechatronics**.

It is intended to be pasted into a fresh chat to quickly re-establish context, constraints, and the plan.

---

## 1) Final title + abstract (locked)

### Title
**Science with Mechatronics: power and information -> datasets -> papers**

### Abstract (≤200 words)
Modern neuroscience depends on custom experimental rigs. This poster targets neuroscience collaborations between scientists and engineers by presenting a mouse pull joystick rig as a case study in Science with Mechatronics: designing the entire stack (mechanics, transducers, power electronics, real-time firmware, and host protocols) as a single precision instrument. The rig positions and loads a joystick with motorized actuation and braking, measures pull kinematics and force/torque, and logs time-aligned events to produce trial-structured, analysis-ready datasets. We highlight two practices that make the pipeline robust and maintainable: (1) the Mechatronic Boundary Model (MBM), which makes boundary crossings explicit as power or information ports and treats datasets/figures as first-class outputs; and (2) event-driven firmware built on QP actors and hierarchical state machines to enforce deterministic timing, explicit safety handling, and clear experiment orchestration. By automating experimental tedium and making artifacts and interfaces explicit, mechatronics helps scientists move from transducers to publishable figures, and ultimately papers, faster. The same approach generalizes to other behavioral rigs.

---

## 2) High-level goal

### Primary goal
**Drive neuroscience collaborations.** Convince primarily-neuroscience viewers that we can make their rigs more reliable and productive: less tedium, less downtime, and more trustworthy data.

### Secondary goals
- Keep the poster visually **engineering-forward** (not “science-results pasted on a board”).
- Still be **immediately relevant** to neuroscientists (credible evidence that the rig produces publishable datasets).
- Showcase end-to-end capability: mechanics → PCB → firmware → host protocol → datasets → figures → papers.
- Emphasize two differentiators:
  - **MBM (Mechatronic Boundary Model):** explicit boundary/port thinking with **power + information** flows.
  - **QP firmware:** event-driven **actors + hierarchical state machines** for deterministic timing, safety handling, and maintainable control logic.

---

## 3) Audience + tone

### Audience
- Primary: **neuroscientists** at a conference poster session.
- Secondary: engineers / instrumentation people.

### Tone / vocabulary
- Collaboration-forward, practical, not buzzwordy.
- Prefer: **instrument**, **workflow**, **interfaces**, **timing**, **calibration**, **reliability**, **datasets**.
- Avoid: “synergy”, “revolutionary”, “AI-first”, long paragraphs.

---

## 4) Format + file workflow (locked)

### Print format
- **Printed poster only**
- Max size: **48 in × 48 in**
- Chosen format: **48×48 square** to maximize area and make **joystick + PCB** heroes large.

### Source of truth
- Master layout: **Inkscape SVG** (`poster/print48.svg`)
- Export deliverable: **PDF for print** (`output/print48.pdf`)
- Optional preview: PNG (`output/print48.png`)

### Asset philosophy
- Keep **text + arrows + boundaries** as vector in Inkscape.
- Keep **hero renders** as high-res PNG (transparent background ideal).
- Keep plots as **SVG/PDF** when possible.

---

## 5) Main story arc (what the poster should communicate)

### One-sentence north star
**Mechatronics turns power and information into trustworthy datasets, and trustworthy datasets become papers.**

### Three-layer narrative
1) **Concrete proof (case study):** mouse pull joystick rig produces analysis-ready datasets.
2) **Why it works (differentiators):**
   - **QP**: deterministic timing + explicit states + safety.
   - **MBM**: explicit ports/interfaces + explicit artifacts (datasets/figures) as outputs.
3) **Generalizes:** same pipeline applies to other behavioral rigs.

---

## 6) Visual design grammar (keep consistent everywhere)

### Replace prose with a few repeatable visual rules
- Big **hero renders** + sparse labels.
- Two arrow types everywhere:
  - **Power** = thick arrow.
  - **Information** = thin arrow.
  - Optional “mouse interaction” = **dashed thick** (highlighted mechanical power).
- Boundaries (MBM) used sparingly:
  - No giant translucent bubbles over the hero renders.
  - Use MBM boundaries in a dedicated strip and/or in small subsystem insets.

### “Hang-on-the-wall” aesthetic
- Strong grid, lots of whitespace.
- Short noun-phrase headings.
- Minimal text: title + abstract block + labels + small “deliverables cards”.

---

## 7) Planned module set for the 48×48 layout

Target: ~5–7 visuals + small cards.

### A) Hero: Mechanics (large)
- Exploded render emphasizing:
  - stepper motors (pitch + yaw)
  - brake
  - encoder
  - torque sensor
  - limit switches
  - speaker
  - torque/force path to the handle
- Hide/fade support scaffolding.

### B) Hero: Electronics (large)
- PCB hero render (isometric) to show 3D, connectors, and “instrument-grade” electronics.
- PCB top view used for **functional zoning overlays**.

### C) “Science with Mechatronics” pipeline strip
A compact left→right flow:
**Power + Information → Datasets → Figures → Papers**
- Keep “datasets” visually central (data product concept).

### D) Integration loop (collaboration visual)
Two swimlanes:
- **Mechatronics (our group):** instrument/firmware/interfaces.
- **Science (your lab):** protocol, experiments, analysis, publication.
Key handoffs:
- Requirements/protocol → (science → engineering)
- Datasets + metadata + reliability → (engineering → science)
- Iterate from paper → new questions.

### E) MBM strip (differentiator, not headline)
- Nested boundaries (rig / electronics+mechanics / firmware+host).
- Explicit **ports** with thick (power) and thin (info) arrows.
- Tiny legend reused everywhere.

### F) Firmware vignette (tiny but credibility-heavy)
- 4–6 actor tiles (e.g., TrialConductor, Sensing, Actuation, Telemetry, Safety, HostLink).
- Thin arrows = events/messages.
- Tiny HSM stamp (IDLE → ARMED → ACTIVE → COMPLETE → ERROR).
- Note: firmware is being rewritten from earlier Arduino code into QP actors/HSMs (optionally BT for high-level orchestration).

### G) Timing & “data trust” strip
- Trial timeline: cue → set load → pull detect → log window → outcome.
- Show time-aligned event markers (what makes datasets defensible).
- Include ONE small plot (vector preferred).

### H) “What collaboration delivers” cards
6 small cards (icons + one-liners), e.g.:
- Deterministic timing
- Explicit interfaces (ports/protocols)
- Calibration artifacts
- Debuggability (power vs info vs timing)
- Maintainable firmware architecture
- Higher throughput / less downtime

---

## 8) PCB + schematic inclusion plan (latest)

Goal: communicate **MBM-style power/info interfaces** without dumping full schematics.

### PCB visual plan
- Use **PCB isometric render** as the “cool” object.
- Use **PCB top view** with **spotlight zoning** to show functional regions.

### Schematic plan
- Include **top-level hierarchical schematic** (poster-friendly port map).
- Include **one subsystem zoom card**:
  - highlight PCB region (spotlight overlay)
  - show the corresponding subsystem schematic (cropped; no title block)
  - show a render/photo of the transducer(s) it interfaces with
  - overlay 2–4 arrows: thick power in/out; thin information in/out

Suggested subsystem choice order:
1) **Brake channel** (best “information modulates power” exemplar)
2) **Torque sensor chain** (best “transducer → conditioned signal → I²C” exemplar)

---

## 9) MBM (Mechatronic Boundary Model) — poster-ready spec

### What MBM is (one line)
MBM is a hierarchical boundary/port model where **power** and **information** flows crossing boundaries are made explicit; artifacts (datasets/figures/paper) are modeled as high-level information outputs.

### Core vocabulary
- **Entity**: scale-neutral “thing inside a boundary”.
- **Boundary**: nested containment hierarchy.
- **Port**: boundary crossing.
- Two flow types:
  - **Power** (thick)
  - **Information** (thin)

Computation framing:
- Computation is primarily **information → information** inside a boundary.
- Control is **information used to modulate power**.

---

## 10) QP firmware message (poster-friendly)

Positioning:
- QP (event-driven actor model + HSMs) yields:
  - deterministic timing
  - explicit safety/error states
  - maintainable structure vs Arduino “superloop” complexity

Depiction:
- Tiny actor diagram + tiny HSM, minimal text.

---

## 11) How much science content to include

Keep science as *proof*, not the headline.
- Include one small “proof-of-output” plot with event markers.
- Avoid large grids of results or deep methods text.

---

## 12) Toolchain + repo workflow (recommended)

- Keep layout in **Inkscape**.
- Generate renders from CAD tools (FreeCAD/Blender) and PCB renders from KiCad.
- Optional: reproducible environment via Guix (Inkscape, KiCad, FreeCAD, Blender, GIMP, utilities).

---

## 13) Assets needed next (highest leverage)

1) Joystick **exploded** hero render (transparent PNG preferred).
2) Joystick **assembled** iso render (context).
3) Close-up render of the **transducer cluster**.
4) PCB: KiCad 3D viewer **isometric** render.
5) PCB: **top view** render (for zoning overlays).
6) **Top-level schematic** image (vector/PDF preferred).
7) One **subsystem schematic** crop (brake or torque sensor).
8) One small **data plot** (vector preferred).
9) Author list, affiliations, required logos, QR targets.

---

## 14) Open questions (still to decide)

- Final selection of the 4–6 firmware actors to display (names & roles).
- Whether to include a tiny **behavior tree** callout (if it clarifies orchestration).
- Which subsystem to use for the PCB+schematic zoom card (brake vs torque sensor vs both).
- Final “deliverables cards” wording (6 one-liners).
- QR destinations (repo/demo/contact/paper).

---

## 15) One-sentence elevator pitch (for the poster + conversation)

“We design rigs end-to-end—mechanics, PCB, deterministic real-time firmware, and explicit interfaces—so power and information become trustworthy datasets that become papers.”

