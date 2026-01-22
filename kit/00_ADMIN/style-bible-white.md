# Style Bible — MBM Comic Poster (White Paper + Icosahedron Boundary Edition)

This poster is a **graphic‑novel page** about:

**Science with Mechatronics: _power + information → datasets → papers_.**

All 10 panels are generated in separate chats, so this file defines the **non‑negotiable visual grammar**.

---

## 0) Print intent (white paper)

- Final print is on **white paper**. Treat the page as white (#FFFFFF).
- Use **very light gray** as “gutter air” if needed (suggested #F3F4F6 to #F8FAFC).
- Avoid big dark fills (ink‑heavy). Prefer: outlines, soft shadows, subtle gradients.

---

## 1) MBM diagram grammar (do not change meaning midstream)

MBM is a hierarchical boundary/port model: draw a boundary around an entity, enumerate its **ports**, and classify what crosses each port as **power** and/or **information**.

### 1.1 Boundary (signature motif)
- Visual metaphor: a **3D icosahedron boundary token** (platonic solid).
- Recommended form: **wireframe / strut icosahedron** (thin rods + corner nodes), so the viewer can see inside.
- The boundary must read as a *chosen abstraction cut* — not a container UI.

### 1.2 Ports (where flows attach)
- Ports live at **icosahedron vertices**.
- Each active vertex has a small **connector node / jack** (a little “port puck” or grommet).
- Color-code the port node rim:
  - **cyan rim = information**
  - **amber rim = power**
  - if a port carries both, show a split rim (half cyan / half amber).

### 1.3 Flows (replace arrows with tangible connectors)
Instead of arrow glyphs, flows are **semi‑realistic 3D tethers**: cables, wires, or chain‑sleeved hoses.

**Information flow (I)**
- Form: **thin fiber / wire harness**.
- Material: translucent sheath or braided sleeve.
- Accent: **cyan** (#06B6D4).
- Direction cue: tiny **light pulses / beads** traveling along the cable (like packets), or a subtle cyan gradient.

**Power flow (P)**
- Form: **thicker braided power cable** or **chain‑sleeved hose**.
- Material: braided copper texture, rubberized sheath, or chainmail sleeve.
- Accent: **amber** (#F59E0B).
- Direction cue: warm **glow pulses**, faint sparks, or a heat‑gradient band moving along the cable.

**Important:**
- A single port can carry both power and information (allowed). If so, show two parallel tethers (thin cyan + thick amber), or one tether with dual accents.

### 1.4 Artifacts (datasets/figures/paper are physical)
- Papers, figures, datasets, configs are **physical objects** in the scene:
  - floating printed sheets
  - glass cards / acrylic slabs
  - “data crystal” blocks
- Artifacts should feel like they come *from the boundary* (produced), not like UI screenshots pasted on top.

### 1.5 Optional (Panel 10 / theory)
- Dissipation / entropy export can be shown as subtle **heat shimmer**, drifting particles, or a faint red haze.
- Always secondary to the P/I tethers.

---

## 2) Materials + finish (new signature look)

### 2.1 Icosahedron boundary material
Avoid “soap bubble” and avoid “brushed nickel sphere.”

Recommended material stack (pick one and stick with it across all panels):

**Option A — Carbon‑fiber strut frame (recommended)**
- Thin, matte **carbon‑fiber rods** for edges.
- Small satin‑black corner nodes.
- Reads as engineered, modern, and prints cleanly.

**Option B — Frosted acrylic strut frame**
- Translucent frosted rods with bright edge highlights.
- Slight refraction but not glass‑heavy.

**Option C — Ceramic/porcelain frame**
- Warm off‑white matte rods with gentle shading.
- Works well on white paper if shadows are present.

### 2.2 Flow tether material
- Cables must look like **objects in space**:
  - thickness
  - curvature
  - soft shadow
  - occlusion when they pass behind things
- Prefer “interesting tactile surfaces”:
  - braided sleeve
  - twisted pair
  - chainmail sleeve
  - segmented beads

### 2.3 Palette (accents)
- Information accent: **cyan** #06B6D4
- Power accent: **amber** #F59E0B
- Dissipation accent (optional): **muted red** #DC2626
- Ink/outline: near‑black #111827
- Gutter air: #F3F4F6 – #F8FAFC

---

## 3) Rendering style (avoid block diagrams)

- Semi‑realistic 3D with:
  - perspective depth
  - rim light / key light
  - soft ambient occlusion
- Mild “ink line” is OK, but **do not** flatten into a schematic.
- Use **big shapes**; few tethers; strong silhouettes.

---

## 4) Composition rules (poster readability)

- One clear focal object per panel (paper, dataset constellation, rig, PCB, MCU, motor, etc.).
- Prefer **1–6 tethers per panel** (rarely more than 8).
- Keep **text minimal** inside the generated panel image:
  - 0–2 tiny labels max (icons preferred)
  - Add longer labels later in Inkscape.

---

## 5) Continuity across panels

- The “camera” can change, but keep:
  - consistent boundary token (icosahedron frame)
  - consistent tether semantics (cyan=information, amber=power)
  - consistent artifact style (glass/data objects)
- Suggest transitions by letting a tether **aim toward a panel edge** that leads to the next panel.
