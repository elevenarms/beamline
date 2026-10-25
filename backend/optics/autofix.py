"""Deterministic design fixes applied before (or instead of) an LLM repair round.

terminate_strays: every beam that escapes the table with non-trivial power gets a beam dump placed on
its branch, just inside the table edge. Instant, safe, and frees the repair agent for real problems.
"""
from __future__ import annotations

import math
from typing import Any

from optics.diff import diff_designs
from optics.ir import Design, Element, TraceResult
from optics.trace import trace

STRAY_MW = 0.05      # matches verify's warning threshold for unterminated beams
EDGE_MARGIN = 15.0   # keep dumps this far inside the plate edge
MAX_DIST = 40.0      # place dumps close to the last optic, but not further than this


def _distance_to_edge(start: tuple[float, float], direction_deg: float, w: float, h: float) -> float:
    """Distance from start along direction to the baseplate boundary (inf if pointing inward forever)."""
    dx, dy = math.cos(math.radians(direction_deg)), math.sin(math.radians(direction_deg))
    best = math.inf
    for coord, d, lo, hi in ((start[0], dx, 0.0, w), (start[1], dy, 0.0, h)):
        if abs(d) > 1e-12:
            for bound in (lo, hi):
                t = (bound - coord) / d
                if t > 1e-9:
                    best = min(best, t)
    return best


def _errors(design: Design) -> tuple[int, set[str]]:
    from optics.verify import verify  # local import: verify imports trace
    t = trace(design)
    rep = verify(design, t)
    strays = {sg.branch for sg in t.segments if sg.end_reason == "escaped" and sg.power_mw > STRAY_MW}
    return sum(c.severity == "error" for c in rep.checks), strays


def terminate_strays(design: Design, tr: TraceResult | None = None) -> tuple[Design, list[dict[str, Any]]]:
    """Return (fixed design, changes). For each escaped branch carrying > STRAY_MW, try dump placements
    (near/far, full block or knife edge) and keep the first that terminates it without adding errors —
    a stray running 1 mm from a wanted beam must not take the wanted beam out with it."""
    tr = tr or trace(design)
    bp = design.baseplate
    taken = {e.id for e in design.elements}
    current = design
    base_errors, _ = _errors(current)

    escaped = []
    seen: set[str] = set()
    for sg in tr.segments:
        if sg.end_reason == "escaped" and sg.power_mw > STRAY_MW and sg.branch not in seen:
            seen.add(sg.branch)
            escaped.append(sg)

    for sg in escaped:
        edge = _distance_to_edge(sg.start, sg.direction_deg, bp.width_mm, bp.height_mm)
        room = edge - EDGE_MARGIN if math.isfinite(edge) else 2 * MAX_DIST
        distances = sorted({max(3.0, min(d, room)) for d in (MAX_DIST, room, 2 * MAX_DIST, 20.0)}, reverse=False)
        n = 1
        while f"BD_auto{n}" in taken:
            n += 1
        eid = f"BD_auto{n}"
        accepted = False
        for aperture in (None, 2.0, 1.0):          # full block, then knife edges
            for dist in distances:
                el = Element(id=eid, type="beam_dump", beam=sg.branch, distance_mm=round(dist, 1),
                             aperture_mm=aperture, group=_group_of(design, sg.source_id),
                             label=f"auto dump ({sg.power_mw:.2f} mW)" + (" knife edge" if aperture else ""))
                trial = current.model_copy(update={"elements": [*current.elements, el]})
                errs, strays = _errors(trial)
                if sg.branch not in strays and errs <= base_errors:
                    current, base_errors, accepted = trial, errs, True
                    break
            if accepted:
                break
        if accepted:
            taken.add(eid)

    if current is design:
        return design, []
    return current, diff_designs(design, current)


def _group_of(design: Design, source_id: str) -> str | None:
    return next((s.group for s in design.sources if s.id == source_id), None)
