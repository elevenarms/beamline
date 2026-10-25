# Beamline — demo runbook (4:00 pm)

## Setup (by 3:30)
- Backend **without reload**: `cd backend && uv run uvicorn server:app --port 8001` (never demo on a `--reload` server — file saves kill in-flight runs).
- Web: `cd web && npm run build` then open **http://localhost:8001** (backend serves `web/dist`), or `VITE_API_TARGET=http://localhost:8001 npx vite --port 5180`.
- Browser: Chrome, full screen, 1440×900+, light theme for projector (moon/sun toggle top-right). Close the console drawer before starting.
- Pre-load tabs: (1) app with `aom_doublepass`, (2) `demo/rb_sas_fig2a.png` open in Finder for drag-and-drop.
- Fallbacks: **Recorded runs** buttons (Workflow tab) replay real captured runs offline. `?mock=1` = fully offline app.

## Script (~4 min)

**0:00 — Problem (20 s).** Building a laser-optics setup for atomic physics takes weeks of hand layout, and mistakes (a stray 3 mW beam, a clipped mount) are found on the table. PyOpticL (Quantum 2026, used at MIT/Stanford/Harvard) made optics code-to-CAD. We made it *agentic and verified*.

**0:20 — Verified physics (40 s).** Load `aom_doublepass`. Top view. "Every beam is a Gaussian — waist, polarization, power, AOM frequency shift." Point at the verify panel: **FAIL — 3.2 mW unterminated beam leaves the table** (laser safety). Switch to `aom_doublepass_fixed` → PASS 98. Toggle Iso/Front/Side (keys 1–4).

**1:00 — Design from a goal (60 s).** Type: *"AOM double-pass at 780 nm on one baseplate, fiber in and fiber out, at least 5 mW into the output fiber"* → Design. Open the **Agent Console** (`): planner → 4 designer agents in parallel → verifier scores each → autofix adds beam dumps → repair agent with its rationale. ~45–85 s. Hit **Replay** on the iteration scrubber: parts glide into place as the agents converge.

**2:00 — Reproduce a published figure (60 s).** Drag `rb_sas_fig2a.png` (PyOpticL paper Fig. 2a, CC-BY). Three vision agents read it in parallel → synthesis → verify → repair. **Compare** view: original figure beside our layout, "Matched 16/16 components". ~55–90 s. (If slow: Recorded runs → Reproduce run.)

**3:00 — Scale (30 s).** Load `sr_ion_apparatus`: full Sr⁺ trapped-ion laser system, 7 subsystems, 121 optics, traces + verifies in 6 ms. Outline tab, solo a module. (Live hierarchical run = ~100 s; mention: architect + 6 module agents in parallel, shared laser power budgets.)

**3:30 — Fun: light computes (30 s).** Load `alloptical_half_adder`: 1064 nm + 1550 nm in a PPLN crystal. Toggle A, B in the Logic I/O strip: SUM is leftover IR (XOR via pump depletion), CARRY is 631 nm red light from sum-frequency generation (AND). **1 + 1 = 10, computed by photons.**

**3:50 — Close.** Export PyOpticL → runnable FreeCAD script; back to real hardware.

## Numbers to quote (measured today)
- Tracer: 121-element apparatus traced + verified in **6.1 ms**; 104 backend tests.
- Goal → verified design: **~45–85 s**, best-of-4 candidates, scores 97–98.
- Figure → verified design: **55–92 s**, PASS 95–96, 14–16/16 components matched.
- Real-paper benchmark (8 open-access figures): 3/8 reproduce pass (incl. hard dual-trap optical tweezers, 22 parts), **4/4 goal designs pass**.
- argon grounding: PyOpticL API hallucination **95 % zero-shot → 0 %** grounded; read 15/15 components and 9/9 printed part numbers from paper figures.
- Hierarchical: 6 modules in parallel, 96 optics, PASS 98.5, ~100 s.

## Honest caveats (if asked)
- Planar (2D) table model; Gaussian beams are round; thin lenses; no interference/coherence.
- Nonlinear models are textbook steady-state (SOA gain saturation, χ(2) SFG with perfect phase matching, CW). The SOA NAND has ~5 dB contrast and isn't cascadable in our model; the half adder uses one PPLN crystal with optimistic η.
- Reproduce succeeds on clean schematics; dense multi-panel figures can still fail (3/8 on the benchmark).

## Credits
PyOpticL (UMass Ion Trappers, Quantum 2026, CC-BY). Figures: arXiv CC-BY 4.0 / Wikimedia (see `demo/figures/catalog.json`). Model: Gemini `gemini-4-argon`.
