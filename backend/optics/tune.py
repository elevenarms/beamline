"""Deterministic alignment / tuning pass, emitted step by step for the UI animation.

    await tune(design, emit, objective="auto", pace_ms=0) -> Design
    detune(design, seed=0) -> Design          (a realistically misaligned copy, for demos)

Objective ("auto"; higher is better, evaluated with trace() + verify()):
  * with targets:  sum_t min(1, value_t / need_t) + 0.2 * delivered_fraction + 0.01 * score
    (polarization targets: value = overlap fidelity, need = 0.98)
  * without:       delivered_fraction + mean fiber coupling efficiency + 0.01 * score
  * minus 1.0 per structural verify error (off_table, unplaced); other errors count only
    through score (-25 each, i.e. -0.25), so the search never dims the light to silence
    stray-beam errors.  Trials that leave any element unplaced (that was placed
    before) are rejected outright and not emitted.
"delivered" = fibers + photodiodes (verify's delivered_mw).

Order: elements in the order the traced beams first reach them (segments in trace order,
sources in design order); each tunable element is tuned once, knob by knob.

Knobs (coarse grid, then a finer grid around the best coarse value; the current value is
the baseline and is never re-emitted):
  half/quarter_wave_plate  fast_axis_deg    0..90 in 12 steps of 7.5 deg, then +-3.75/+-1.9
  lens                     distance_mm      +-25 % in 10 steps, then 2 finer   (beam-placed only)
  fiber_coupler            distance_mm      +-10 mm in 8 steps, then 2 finer   (beam-placed only)
                           focal_length_mm  4.5, 6.2, 8, 11, 15.4 (+ current)
  mirror                   out_direction_deg +-1.5 deg in 8 steps, then 2 finer (or angle_deg +-0.75)
  beamsplitter             split_ratio      0.1 0.3 0.5 0.7 0.9;  sampler 0.01 0.02 0.05 0.1
  aom                      aom_frequency_mhz +-10 % in 8 steps, then 2 finer
                           (off by default: TUNE_AOM_FREQUENCY, since it changes the physics)
A step that does not strictly improve the objective is not kept (ties keep the original).

Events (see CONTRACT.md): tune_start, tune_step (every evaluated trial), tune_done (per knob),
final.
"""
from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable

from .ir import Design, Element, TraceResult, VerifyReport
from .trace import trace
from .verify import verify

Emit = Callable[[dict[str, Any]], Awaitable[None]]

WAVEPLATES = ("half_wave_plate", "quarter_wave_plate")
FIBER_FOCALS = (4.5, 6.2, 8.0, 11.0, 15.4)
STRUCTURAL = {"off_table", "unplaced"}
# The AOM drive frequency sets the experiment's frequency shift, so it is not a free alignment
# knob; enable explicitly (e.g. for single-pass deflection steering).
TUNE_AOM_FREQUENCY = False
SPLIT_RATIOS = {"beamsplitter": (0.1, 0.3, 0.5, 0.7, 0.9), "sampler": (0.01, 0.02, 0.05, 0.1)}


# ───────────────────────────── objective ──────────────────────────────────

class _Eval:
    __slots__ = ("objective", "trace", "report", "unplaced", "delivered", "coupling", "score")

    def __init__(self, design: Design):
        self.trace: TraceResult = trace(design)
        self.report: VerifyReport = verify(design, self.trace)
        m = self.report.metrics
        self.unplaced = {e.id for e in self.trace.elements if not e.placed}
        self.delivered = m.get("delivered_mw", 0.0)
        self.score = self.report.score
        fibers = [e.coupling_efficiency for e in self.trace.elements
                  if e.type == "fiber_coupler" and e.coupling_efficiency is not None]
        self.coupling = max(fibers) if fibers else None
        frac = m.get("delivered_fraction", 0.0)
        # Structural errors get a large penalty.  Optical errors (stray beam, clipping, unmet
        # target) are already felt through score (-25 each -> -0.25 here); a large penalty on
        # them makes the greedy search "fix" stray beams by throwing the light away.
        n_err = sum(c.severity == "error" and c.id in STRUCTURAL for c in self.report.checks)
        if design.targets:
            sat = 0.0
            for t in design.targets:
                val = m.get(f"target.{t.element_id}.{t.kind}", 0.0)
                need = 0.98 if t.kind == "polarization" else float(t.value)
                sat += min(1.0, val / need) if need > 0 else 1.0
            obj = sat + 0.2 * frac + 0.01 * self.score
        else:
            mean_c = sum(fibers) / len(fibers) if fibers else 0.0
            obj = frac + mean_c + 0.01 * self.score
        self.objective = obj - 1.0 * n_err

    def metrics(self) -> dict[str, Any]:
        return {"delivered_mw": self.delivered, "coupling": self.coupling, "score": self.score}


# ───────────────────────────── knobs ──────────────────────────────────────

def _grid(lo: float, hi: float, n: int) -> list[float]:
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def _knobs(el: Element) -> list[tuple[str, list[float], float | None]]:
    """[(field, coarse values, coarse step for refinement or None)]."""
    k: list[tuple[str, list[float], float | None]] = []
    t = el.type
    if t in WAVEPLATES:
        k.append(("fast_axis_deg", [7.5 * i for i in range(12)], 7.5))
    elif t == "lens" and el.distance_mm is not None:
        d = el.distance_mm
        k.append(("distance_mm", _grid(0.75 * d, 1.25 * d, 10), 0.5 * d / 9))
    elif t == "fiber_coupler":
        if el.distance_mm is not None:
            d = el.distance_mm
            k.append(("distance_mm", _grid(max(1.0, d - 10), d + 10, 8), 20 / 7))
        k.append(("focal_length_mm", list(FIBER_FOCALS), None))
    elif t == "mirror":
        if el.out_direction_deg is not None:
            a = el.out_direction_deg
            k.append(("out_direction_deg", _grid(a - 1.5, a + 1.5, 8), 3.0 / 7))
        elif el.angle_deg is not None:
            a = el.angle_deg
            k.append(("angle_deg", _grid(a - 0.75, a + 0.75, 8), 1.5 / 7))
    elif t in SPLIT_RATIOS:
        k.append(("split_ratio", list(SPLIT_RATIOS[t]), None))
    elif t == "aom" and TUNE_AOM_FREQUENCY:
        f = el.aom_frequency_mhz if el.aom_frequency_mhz is not None else 80.0
        k.append(("aom_frequency_mhz", _grid(0.9 * f, 1.1 * f, 8), 0.2 * f / 7))
    return k


def _order(design: Design, tr: TraceResult) -> list[str]:
    by_id = {e.id: e for e in design.elements}
    order: list[str] = []
    for s in tr.segments:
        eid = s.end_element
        if eid and eid in by_id and eid not in order and _knobs(by_id[eid]):
            order.append(eid)
    return order


# ───────────────────────────── tune ───────────────────────────────────────

async def tune(design: Design, emit: Emit, objective: str = "auto", pace_ms: float = 0.0,
               max_steps: int = 160) -> Design:
    d = design.model_copy(deep=True)
    by_id = {e.id: e for e in d.elements}
    cur = _Eval(d)
    base = cur
    baseline_unplaced = cur.unplaced
    order = _order(d, cur.trace)
    await emit({"type": "tune_start", "order": order, "objective": objective,
                "baseline": {"objective": base.objective, "delivered_mw": base.delivered, "score": base.score}})
    steps = 0

    async def try_value(el: Element, field: str, value: float) -> _Eval | None:
        nonlocal steps, cur
        old = getattr(el, field)
        setattr(el, field, value)
        ev = _Eval(d)
        if ev.unplaced - baseline_unplaced:
            setattr(el, field, old)   # would unplace something: reject silently
            return None
        steps += 1
        better = ev.objective > cur.objective + 1e-9
        await emit({"type": "tune_step", "element_id": el.id, "field": field, "value": value,
                    "objective": ev.objective, "metrics": ev.metrics(), "best_so_far": better,
                    "patch": {field: value}})
        if better:
            cur = ev
        else:
            setattr(el, field, old)
        await asyncio.sleep(pace_ms / 1000 if pace_ms else 0)
        return ev

    for eid in order:
        el = by_id[eid]
        for field, coarse, step in _knobs(el):
            if steps >= max_steps:
                break
            start = getattr(el, field)
            start_obj = cur.objective
            tried = {round(start, 6)} if start is not None else set()
            for v in coarse:
                if steps >= max_steps:
                    break
                if round(v, 6) not in tried:
                    tried.add(round(v, 6))
                    await try_value(el, field, v)
            if step is not None:
                best = getattr(el, field)
                for dv in (-step / 2, step / 2, -step / 4, step / 4):
                    if steps >= max_steps:
                        break
                    v = best + dv
                    if field == "fast_axis_deg":
                        v %= 180.0
                    if round(v, 6) not in tried:
                        tried.add(round(v, 6))
                        await try_value(el, field, v)
                    best = getattr(el, field)
            end = getattr(el, field)
            if end != start:
                await emit({"type": "tune_done", "element_id": eid, "field": field,
                            "from": start, "to": end, "gain": cur.objective - start_obj})
            else:
                await emit({"type": "tune_done", "element_id": eid, "field": field,
                            "from": start, "to": start, "gain": 0.0})

    await emit({"type": "final", "design": d, "trace": cur.trace, "report": cur.report,
                "summary": {"objective_before": base.objective, "objective_after": cur.objective,
                            "steps": steps}})
    return d


# ───────────────────────────── detune ─────────────────────────────────────

def detune(design: Design, seed: int = 0) -> Design:
    """Realistically misaligned copy: waveplates off by 8-25 deg, lens distances off by
    8-20 %, mirror angles off by 0.2-0.8 deg.  A perturbation that would unplace anything
    is retried smaller, then dropped."""
    rng = random.Random(seed)
    d = design.model_copy(deep=True)
    base_unplaced = {e.id for e in trace(d).elements if not e.placed}

    def sign() -> float:
        return rng.choice((-1.0, 1.0))

    for el in d.elements:
        if el.type in WAVEPLATES:
            field, delta = "fast_axis_deg", sign() * rng.uniform(8, 25)
        elif el.type == "lens" and el.distance_mm is not None:
            field, delta = "distance_mm", sign() * rng.uniform(0.08, 0.20) * el.distance_mm
        elif el.type == "mirror" and el.out_direction_deg is not None:
            field, delta = "out_direction_deg", sign() * rng.uniform(0.2, 0.8)
        elif el.type == "mirror" and el.angle_deg is not None:
            field, delta = "angle_deg", sign() * rng.uniform(0.1, 0.4)
        else:
            continue
        orig = getattr(el, field)
        old = orig if orig is not None else 0.0
        for scale in (1.0, 0.5, 0.25):
            setattr(el, field, old + scale * delta)
            if not ({e.id for e in trace(d).elements if not e.placed} - base_unplaced):
                break
        else:
            setattr(el, field, orig)
    return d


# ───────────────────────────── CLI ────────────────────────────────────────

def _main(argv: list[str]) -> int:
    import time

    if len(argv) < 2:
        print("usage: python -m optics.tune design.json [--detune SEED]")
        return 2
    design = Design.model_validate_json(open(argv[1]).read())
    if "--detune" in argv:
        design = detune(design, int(argv[argv.index("--detune") + 1]))
    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)
        if ev["type"] == "tune_done" and ev["from"] != ev["to"]:
            print(f"  {ev['element_id']:<10} {ev['field']:<18} {ev['from']:9.3f} -> {ev['to']:9.3f}"
                  f"  gain {ev['gain']:+.4f}")

    t0 = time.perf_counter()
    asyncio.run(tune(design, emit))
    dt = time.perf_counter() - t0
    start = events[0]["baseline"]
    fin = events[-1]
    print(f"{design.name}: objective {start['objective']:.4f} -> {fin['summary']['objective_after']:.4f}, "
          f"delivered {start['delivered_mw']:.3f} -> {fin['report'].metrics.get('delivered_mw', 0):.3f} mW, "
          f"{fin['summary']['steps']} steps, {dt * 1000:.0f} ms")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_main(sys.argv))
