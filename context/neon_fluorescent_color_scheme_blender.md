# Neon / Fluorescent Technical Color Scheme (Blender)

This file captures the final recommended 6‑color scheme for a polyhedron + three line types intended for documentation renders. The priorities were:

- **Neon / fluorescent look**
- **Distinct colors** that remain easy to tell apart when adjacent
- **Readable on white** (your primary background) while still being workable on **dark backgrounds**
- Clear role separation: **faces vs edges vs vertices**, and **three different line types**

---

## Final palette (with Blender values)

Blender’s color picker commonly uses **RGB in 0–1** (and also supports **Hex**). Values below are in both formats.

| Role | Color name | Hex | Blender RGB (0–1) | Rationale |
|---|---:|---:|---:|---|
| **Polyhedron faces** | Magenta | `#FF00FF` | **(1.000, 0.000, 1.000)** | Your requested face color; strong “neon” identity and easy to read. |
| **Polyhedron edges** | Graphite (near-black) | `#333333` | **(0.200, 0.200, 0.200)** | Clean wireframe contrast on white; doesn’t compete with neon accents. Still visible on many dark backgrounds. |
| **Polyhedron vertices** | Neon lime | `#39FF14` | **(0.224, 1.000, 0.078)** | Highly visible and *complements magenta* well (excellent “pop” against faces). Distinct from cyan/red. |
| **Face-center lines** | Neon orange | `#FF7A00` | **(1.000, 0.478, 0.000)** | Chosen specifically because it reads better than neon yellow on white while staying vibrant and distinct from red/cyan/magenta. |
| **Vertex line type A** | Cyan | `#00FFFF` | **(0.000, 1.000, 1.000)** | Your requested cyan; high separation from magenta and lime. |
| **Vertex line type B** | Red | `#FF0000` | **(1.000, 0.000, 0.000)** | Your requested red; unmistakable and balanced against cyan/magenta. |

---

## Background compatibility notes

### White background (primary)
- The only common “neon” color that tends to wash out on pure white is **neon yellow**.  
  That’s why **neon orange** was selected for the face-center lines.
- **Graphite edges** (`#333333`) keep the wireframe readable without visually overpowering the neon elements.

### Dark background (secondary)
- The palette remains distinct on dark backgrounds, but edge visibility depends on how dark your background is.

**Optional edge swap for very dark backgrounds**
- If the background is near-black and graphite edges feel too subtle, swap edges to a light neutral:
  - **Edges (light neutral):** `#E6E6E6` → **(0.902, 0.902, 0.902)**

---

## Blender material tips for a “fluorescent” look

### 1) Use emission for lines/points (and optionally vertices)
For line objects and vertices, an **Emission** shader makes the colors read as fluorescent in renders.

Suggested starting points:
- **Emission Color:** the palette color above
- **Emission Strength:** **2–5** (increase if you want stronger glow)

### 2) Eevee “Bloom” for neon glow
If you render in **Eevee**, enable:
- **Render Properties → Bloom**

This is usually the fastest way to get a neon sign-like glow.

### 3) Face transparency for technical diagrams (optional)
If you want to see interior lines/vertices through faces:
- Set face material **Alpha ~0.2–0.4**
- For Eevee: **Material → Settings → Blend Mode** (Alpha Blend or Alpha Hashed depending on your needs)

---

## Quick copy/paste list

- Faces (Magenta): `#FF00FF` → (1.000, 0.000, 1.000)  
- Edges (Graphite): `#333333` → (0.200, 0.200, 0.200)  
- Vertices (Neon Lime): `#39FF14` → (0.224, 1.000, 0.078)  
- Face-center lines (Neon Orange): `#FF7A00` → (1.000, 0.478, 0.000)  
- Vertex line A (Cyan): `#00FFFF` → (0.000, 1.000, 1.000)  
- Vertex line B (Red): `#FF0000` → (1.000, 0.000, 0.000)  

---

## Final thought

This scheme keeps your requested **magenta / cyan / red** anchors, then adds:
- **Graphite** for structure (edges),
- **Neon lime** for vertex emphasis (especially strong against magenta faces),
- **Neon orange** for face-center normals so they remain bright and readable on white.

Together, the set stays “fluoro” without becoming visually noisy, and each role remains identifiable at a glance.
