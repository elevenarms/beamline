"""Prompts for the Gemini agents. The system prompt teaches the Design IR (ir.py source),
the tracer's orientation conventions (optics/trace.py module docstring, included verbatim),
a part catalog, AMO design heuristics and few-shot example Designs."""
from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from optics.ir import Design

BACKEND = Path(__file__).resolve().parents[1]
IR_FILE = BACKEND / "optics" / "ir.py"
TRACE_FILE = BACKEND / "optics" / "trace.py"
EXAMPLES_DIR = BACKEND / "examples"

PREFERRED_EXAMPLES = ["aom", "double", "sas", "saturated", "fiber", "pickoff"]


def _ir_source() -> str:
    """ir.py, design-IR part only (docstring + design classes, not trace/verify schemas)."""
    src = IR_FILE.read_text()
    cut = src.find("# ─────────────────────────────── trace result")
    return src[:cut] if cut > 0 else src


def _trace_doc() -> str:
    if not TRACE_FILE.exists():
        return "(tracer conventions not yet available)"
    m = re.match(r'\s*(?:#.*\n\s*)*(?:"""|\'\'\')(.*?)(?:"""|\'\'\')', TRACE_FILE.read_text(), re.S)
    return m.group(1).strip() if m else "(tracer module docstring missing)"


def _examples(n: int = 2) -> list[tuple[str, str]]:
    files = sorted(EXAMPLES_DIR.glob("*.json")) if EXAMPLES_DIR.exists() else []
    scored = []
    for f in files:
        try:
            d = Design.model_validate_json(f.read_text())
        except Exception:  # noqa: BLE001
            continue
        rank = next((i for i, k in enumerate(PREFERRED_EXAMPLES) if k in f.stem.lower()), 99)
        scored.append((rank, f.stem, d))
    scored.sort(key=lambda x: x[0])
    out = [(stem, d.model_dump_json(exclude_none=True, exclude_defaults=True)) for _, stem, d in scored[:n]]
    if not out:
        out = [("fallback_fold_to_dump", json.dumps(_INLINE_EXAMPLE))]
    return out


_INLINE_EXAMPLE = {
    "name": "Pickoff to photodiode",
    "sources": [{"id": "L1", "position": [20, 50], "direction_deg": 0, "wavelength_nm": 780, "power_mw": 20}],
    "elements": [
        {"id": "S1", "type": "sampler", "beam": "L1", "distance_mm": 60, "split_ratio": 0.05},
        {"id": "PD1", "type": "photodiode", "beam": "L1.r", "distance_mm": 40},
        {"id": "M1", "type": "mirror", "beam": "L1.t", "distance_mm": 80, "out_direction_deg": 90},
        {"id": "BD1", "type": "beam_dump", "beam": "L1.t", "distance_mm": 50},
    ],
    "targets": [{"element_id": "PD1", "kind": "min_power_mw", "value": 0.5}],
}

CATALOG = """\
Realistic default parts (use these part_number values unless the user/figure says otherwise):
- mirror: Thorlabs BB05-E03 (1/2" broadband dielectric, 750-1100 nm) in KM05 mount; 1" BB1-E03 in KM100.
- lens: Thorlabs LA1131-B (f=50 mm plano-convex), LA1509-B (f=100), LA1708-B (f=200), AC127-050-B (f=50 achromat 1/2").
- half_wave_plate: Thorlabs WPH05M-780 (zero-order λ/2 @780) in RSP05 rotation mount.
- quarter_wave_plate: Thorlabs WPQ05M-780.
- pbs: Thorlabs PBS251 (10 mm cube, 620-1000 nm) or PBS052 (1/2" 700-1300 nm).
- beamsplitter: Thorlabs BS010 (50:50 cube 700-1100 nm).
- sampler: Thorlabs BSF05-B (wedged pickoff, ~5% reflect) or a bare uncoated window.
- dichroic: Thorlabs DMLP805 (longpass, reflects < 805 nm).
- aom: Isomet 1205C-1 (80 MHz, TeO2, ~85% max diffraction) or Gooch & Housego 3080-125 (80 MHz); aperture ~1-2 mm, so
  focus or keep the beam small (waist < 0.5 mm) through it.
- iris: Thorlabs ID5MS.
- fiber_coupler: Thorlabs PAF2S-11B FiberPort (f=11 mm) or PAF2-A4B (f=4.5 mm), fiber 780HP / PM780-HP (MFD ~5.3 µm).
  Mode-matching: input waist w satisfies w ≈ f·λ/(π·MFD/2); for MFD 5.3 µm at 780 nm: f=11 mm → w≈1.03 mm, f=4.5 mm → w≈0.42 mm.
- photodiode: Thorlabs PDA36A2 (Si amplified) or SM05PD1A.
- beam_dump: Thorlabs LB1 or BT610 (or a razor blade dump for low power).
- vapor_cell: Thorlabs GC25075-RB (Rb, 25 mm × 75 mm) — transmission ~0.5 near resonance.
- isolator: Thorlabs IO-3D-780-VLP (transmission ~0.9).
- laser source: Toptica DL pro / Vescent / home-built ECDL; 780 nm Rb D2, 795 nm Rb D1, 852 nm Cs D2, 1064 nm, 532 nm.
"""

HEURISTICS = """\
AMO design heuristics:
- Every beam must END in a terminating element (fiber_coupler, photodiode, beam_dump). No stray beams: every PBS /
  beamsplitter / sampler / dichroic output and every AOM 0th order must be caught (dump the unused ones). Beams that
  leave the baseplate or end in nothing are errors.
- Waveplates: put a half_wave_plate before a PBS to set the split ratio (fast axis 22.5° turns H into D → 50:50;
  0° keeps H → all transmitted; 45° turns H into V → all reflected). A PBS transmits H and reflects V.
- AOM double pass (cat-eye): PBS → AOM → lens (f) placed f after the AOM → quarter_wave_plate (45°) → mirror at the
  focal plane of the lens retro-reflecting the +1 order. The return passes the QWP twice (H→V), re-diffracts in the
  AOM (total shift 2×f_AOM) and is now reflected by the PBS into the output arm. Block the 0th order with an iris or
  dump. Double-pass efficiency ≈ η². Keep the beam small through the AOM (lens-focused or waist ~0.3-0.5 mm).
- Saturated absorption spectroscopy: pickoff a few mW, split into strong pump and weak probe (PBS + λ/2, or a
  thick glass plate). Pump and probe counter-propagate through the vapor cell and overlap; probe goes to a
  photodiode, pump goes to a dump. Probe power ~ 0.1-0.5 mW, pump several times stronger.
- Fiber coupling: two steering mirrors before every fiber_coupler (walk the beam), and mode-match the beam waist to
  the coupler (see catalog). A telescope (two lenses separated by f1+f2) resizes the beam.
- Pick off a few percent with a sampler to a photodiode for power monitoring / intensity stabilisation.
- Optical isolator immediately after the laser.
- Leave ≥ 25 mm between optics (mount footprints), ≥ 15 mm clearance from the baseplate edges; fold with 90°
  mirror turns on the 25.4 mm grid where possible; keep everything on the baseplate.
- Clear apertures: 1/2" optics have 12.7 mm aperture; the beam diameter (2w) must be well below it.
- Set realistic targets (min_power_mw / min_coupling / polarization) on the delivered outputs; achievable
  fiber coupling is 0.6-0.85 with good mode matching.
"""

GUIDE = """\
How to write a Design:
- Output a single JSON object of the Design schema. Units mm, deg, nm, mW, MHz. Table frame: origin at the baseplate
  lower-left, +x right, +y up, angles CCW from +x (0=right, 90=up, 180=left, 270=down).
- Prefer beam-relative placement: {"beam": "<branch>", "distance_mm": d} where d is measured from the PREVIOUS
  interaction on that branch (or the source). Elements on the same branch are placed in list order, so list them
  in the order the beam meets them. After a splitter the incoming branch name ends; continue on "<name>.t" and
  "<name>.r" (AOM: "<name>.0" and "<name>.+1"/"<name>.-1"). Mirrors, lenses, waveplates, cells, isolators and
  irises keep the branch name.
- Use absolute "at" placement only for elements a beam reaches on a return/second pass or when beam-relative
  placement cannot express it; then also set angle_deg.
- Mirrors: give out_direction_deg (the direction the reflected beam should travel).
- Unique short ids (L1, M1, PBS1, AOM1, FC1, PD1, BD1 ...), human labels, and part_number from the catalog.
- Make sure every element lies on the baseplate (0..width, 0..height) — size the baseplate to fit (typical
  300×150, 450×300, up to 600×450 mm).
"""


@functools.lru_cache(maxsize=1)
def _system_cached(trace_mtime: float, n_examples: int) -> str:
    ex = "\n\n".join(f"### Example: {name}\n{js}" for name, js in _examples(n_examples))
    return f"""You are an expert experimental AMO physicist and optical engineer who designs tabletop laser
optics setups (breadboard/baseplate layouts) as machine-checkable JSON. A ray tracer and verifier will simulate
your design exactly as written, so geometry, branch names and orientation must follow the conventions below.

## Design IR (Python/Pydantic source — the schema you must output)
```python
{_ir_source()}
```

## Tracer conventions (authoritative — from optics/trace.py)
{_trace_doc()}

## Writing designs
{GUIDE}
## Parts catalog
{CATALOG}
## {HEURISTICS}
## Few-shot example Designs (these trace cleanly and pass verification)
{ex}
"""


def system_prompt(n_examples: int = 2) -> str:
    mt = TRACE_FILE.stat().st_mtime if TRACE_FILE.exists() else 0.0
    return _system_cached(mt, n_examples)


# ───────────────────────────── task prompts ─────────────────────────────

def plan_prompt(goal: str) -> str:
    return f"""Goal from the user:
\"\"\"{goal}\"\"\"

Plan the setup before any geometry. Produce: a title; concrete requirements (wavelength, powers, frequency
shifts, polarizations, outputs); the input power you will assume (default 20-50 mW for a diode/ECDL unless stated);
a baseplate size that fits; the ordered functional modules with their element types/parts; where EVERY beam
terminates; verifier Targets on the output elements (use the element ids you intend to use, e.g. FC1, PD1);
and 4 genuinely different layout approaches (one sentence each) for parallel candidate designs."""


def candidate_prompt(goal: str, plan, hint: str) -> str:
    plan_txt = plan.model_dump_json(indent=1) if plan is not None else "(no plan — work it out yourself)"
    return f"""Goal from the user:
\"\"\"{goal}\"\"\"

Plan:
{plan_txt}

Layout approach for THIS candidate: {hint}

Write the complete Design JSON. Check before answering: every branch ends in a fiber_coupler, photodiode or
beam_dump; every splitter output and AOM 0th order is handled; all positions are on the baseplate; mirror
out_direction_deg values make the beam go where the next element is; targets reference real element ids."""


def repair_prompt(goal: str, design: Design, report: str, trace: str, history: list[str]) -> str:
    hist = ("\nPrevious repair rounds:\n" + "\n".join(history)) if history else ""
    return f"""Goal:
\"\"\"{goal}\"\"\"

The design below was traced and verified and has problems. Fix ALL errors (and warnings where cheap) and return
the complete corrected Design JSON. Keep what works; change only what is needed. Typical fixes: add a beam_dump
on a stray branch, correct a mirror's out_direction_deg, move an element so the beam actually hits it, shrink the
beam or move away from apertures to avoid clipping, rename a branch reference (".t"/".r"/".0"/".+1"), resize the
baseplate, fix mode matching (waist vs fiber coupler focal length), relax unrealistic targets only if physically
impossible.

## Current design
{design.model_dump_json(exclude_none=True)}

## Verify report
{report}

## Trace summary
{trace}
{hist}"""


def extract_prompt(notes: str, i: int) -> str:
    focus = ["Be exhaustive: list every optic, including small ones (waveplates, irises, lenses).",
             "Focus on beam connectivity: follow each beam path from source to end carefully.",
             "Focus on labels, part numbers and parameter values printed in or near the figure."][i % 3]
    return f"""This image is an optics setup figure (schematic or CAD) from a paper or README.
Extract the optical setup as a strict JSON graph:
- components: every optical component, with id (short, unique, e.g. M1, PBS1), type (one of: laser, mirror,
  lens, half_wave_plate, quarter_wave_plate, pbs, beamsplitter, sampler, dichroic, aom, iris, fiber_coupler,
  photodiode, beam_dump, vapor_cell, isolator, other), label as written in the figure, approx_xy = [x, y]
  center position normalized 0-1 within the image with y measured UP from the bottom edge, and part_number if
  printed.
- beams: directed edges along which light travels from one component to the next (from, to, optional label /
  wavelength_nm). Include both passes of a double-passed element.
- parameters: numeric values visible or clearly implied (wavelength, focal lengths, AOM frequency, powers),
  with the text evidence.
{focus}
{('User notes: ' + notes) if notes else ''}"""


def merge_prompt(graphs: list[dict], notes: str) -> str:
    return f"""Three independent readers extracted the optics setup in this figure as graphs. Merge them into one
consensus graph: keep components that at least two readers found (or that are clearly visible in the image),
unify ids, average approx_xy, take the majority type, and keep beams that are consistent with the merged
components. Use the image to break ties.
{('User notes: ' + notes) if notes else ''}
Graphs:
{json.dumps(graphs, separators=(',', ':'))}"""


def synth_prompt(graph: dict, notes: str) -> str:
    return f"""Reproduce the optical setup in this figure as a Design that the tracer can simulate.

Extracted component graph (approx_xy normalized 0-1, y up):
{json.dumps(graph, separators=(',', ':'))}
{('User notes: ' + notes) if notes else ''}

Rules:
- Preserve the topology (which component feeds which, splitter outputs, double passes) and the relative layout:
  map approx_xy onto a baseplate of sensible physical size (typically 300-600 mm wide; keep the image aspect
  ratio), snapping beam paths to clean 0/90/180/270° directions where the figure shows straight lines.
- Map each component to the closest IR element type (lasers become sources). Drop purely mechanical parts.
- Use figure values (wavelength, focal lengths, AOM frequency) when given; otherwise realistic defaults.
- Every beam must terminate (add beam_dumps for beams that leave the figure or end without a component;
  fibers leaving the figure become fiber_couplers).
- Add sensible targets for the main outputs.
Return the complete Design JSON."""
