# Beamline — demo runbook (4:00 pm)

## Setup (by 3:30)
- Backend **without reload**: `cd backend && uv run uvicorn server:app --port 8001` (never demo on a `--reload` server — file saves kill in-flight runs).
- Web: `cd web && npm run build` then open **http://localhost:8001** (backend serves `web/dist`), or `VITE_API_TARGET=http://localhost:8001 npx vite --port 5180`.
- Browser: Chrome, full screen, 1440×900+, light theme for projector (moon/sun toggle top-right). Close the console drawer before starting.
- Pre-load tabs: (1) app with `aom_doublepass`, (2) `demo/rb_sas_fig2a.png` open in Finder for drag-and-drop.
- Fallbacks: **Recorded runs** buttons (Workflow tab) replay real captured runs offline. `?mock=1` = fully offline app.

## Script (~4 min) — headline flow: paper → bench → build

**0:00 — Hook (15 s).** "Building a laser-optics bench for atomic physics takes weeks of layout by hand. Watch an AI read a paper and build it."

**0:15 — Find a paper (20 s).** Type `optical tweezers` in **1 · Find a paper** → Search (live arXiv). Point at setup-scored figure thumbnails + license chips. Click Gieseler et al. 2020, Fig. 5 (score 16) → caption preview → **Build this setup**. The paper PDF opens in the small viewer (bottom-right).

**0:35 — Fly-in (60–75 s, open Console with ` first).** The figure lies flat above the table; scan boxes find the 16 parts. Console: 3 vision agents in parallel → 2 synthesizers → verifier → autofix → repair (rationale shown). Parts drop from the drawing onto the bench in beam order; lasers switch on, beams grow and split. (Press **D** for Director mode.)

**1:50 — Tuning tour (30 s).** Bench auto-detunes then aligns: camera visits each optic, knob turns, live power meter in mW climbs, "+x %" flags, before→after summary.

**2:20 — Verified physics (25 s).** Verify panel: PASS, every Gaussian beam's waist/power/polarization. Load `aom_doublepass` → FAIL: 3.2 mW stray beam (laser safety) → `aom_doublepass_fixed` PASS.

**2:45 — Build it for real (25 s).** **Build kit** → Parts (≈$4k BOM with part numbers) → 3D print: keyed baseplate tiles with beam-path grooves → Download zip (BOM.csv, STLs, PyOpticL/FreeCAD script, assembly README).

**3:10 — Scale (15 s).** Load `sr_ion_apparatus`: 7 subsystems, 121 optics, traced + verified in 6 ms (architect + parallel module agents, shared laser power budgets).

**3:25 — Light computes (20 s).** `alloptical_half_adder`: toggle A/B in Logic I/O — CARRY = 631 nm red from sum-frequency generation, SUM = depleted IR. 1 + 1 = 10, computed by photons.

**3:45 — Cover (15 s).** **Cover art** → Nano Banana 2 (faithful) + 2.1 (cinematic) journal-cover renders of the bench, BEAMLINE masthead. Close.

## Numbers to quote (measured today)
- Tracer: 121-element apparatus traced + verified in **6.1 ms**; 104 backend tests.
- Goal → verified design: **~45–85 s**, best-of-4 candidates, scores 97–98.
- Figure → verified design: **41–92 s**, PASS 95–96, 14–16/16 components matched; reliability check after final fixes: **3/3 PASS (41–55 s, run concurrently)**.
- Real-paper benchmark (8 open-access figures): 3/8 reproduce pass (incl. hard dual-trap optical tweezers, 22 parts), **4/4 goal designs pass**.
- argon grounding: PyOpticL API hallucination **95 % zero-shot → 0 %** grounded; read 15/15 components and 9/9 printed part numbers from paper figures.
- Hierarchical: 6 modules in parallel, 96 optics, PASS 98.5, ~100 s; shared-laser power budget (3 W → 6 modules) balances exactly.
- Paper URL → bench: tweezers (arXiv:2004.05246) PASS 95.4 in 73 s, 14/14 matched.
- Alignment tuner: detuned double-pass recovers 102 % of fiber power in 75 steps / 35 ms.
- Build kit: double-pass = 18 parts + 58 hardware, ≈$4.1k (est.), 2 watertight tiles, 38 h / 566 g PLA.
- Cover art: ~10 s (faithful), ~15–30 s (cinematic).

## Honest caveats (if asked)
- Planar (2D) table model; Gaussian beams are round; thin lenses; no interference/coherence.
- Nonlinear models are textbook steady-state (SOA gain saturation, χ(2) SFG with perfect phase matching, CW). The SOA NAND has ~5 dB contrast and isn't cascadable in our model; the half adder uses one PPLN crystal with optimistic η.
- Reproduce succeeds on clean schematics; dense multi-panel figures can still fail (3/8 on the benchmark).

## Credits
PyOpticL (UMass Ion Trappers, Quantum 2026, CC-BY). Figures: arXiv CC-BY 4.0 / Wikimedia (see `demo/figures/catalog.json`). Model: Gemini `gemini-4-argon`.
