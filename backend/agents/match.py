"""Deterministic figure-component <-> design-element matching for the `match` SSE event.

Pass 1: same id (synthesis is told to reuse the graph ids) with a compatible type.
Pass 2: per compatible type group, greedy nearest neighbour between the figure's scaled xy_mm and the
traced element positions (sources use their start position).
"""
from __future__ import annotations

import math

from optics.ir import Design, TraceResult

GROUP = {
    "laser": "source", "source": "source",
    "beamsplitter": "split", "sampler": "split",
    "half_wave_plate": "hwp", "quarter_wave_plate": "qwp",
}


def _group(t: str) -> str:
    return GROUP.get(t, t)


def match_rows(graph: dict, design: Design, tr: TraceResult | None) -> tuple[list[dict], dict]:
    pos: dict[str, tuple[float, float] | None] = {s.id: tuple(s.position) for s in design.sources}
    types: dict[str, str] = {s.id: "source" for s in design.sources}
    for e in design.elements:
        types[e.id] = e.type
        pos[e.id] = tuple(e.at) if e.at else None
    if tr is not None:
        for pe in tr.elements:
            if pe.position is not None:
                pos[pe.id] = tuple(pe.position)
    # a fiber collimator drawn as the input is usually the design's source
    figure = [c for c in graph.get("components", []) if c.get("type") != "other"]

    def compatible(fig_type: str, des_id: str) -> bool:
        ft, dt = _group(fig_type), _group(types[des_id])
        return ft == dt or (ft == "fiber_coupler" and dt == "source")

    assigned: dict[int, str] = {}
    free = set(types)
    lower = {d.lower(): d for d in types}
    for i, c in enumerate(figure):
        d = lower.get(str(c.get("id", "")).lower())
        if d in free and compatible(c["type"], d):
            assigned[i] = d
            free.discard(d)

    pairs = []
    for i, c in enumerate(figure):
        if i in assigned or "xy_mm" not in c:
            continue
        for d in free:
            if compatible(c["type"], d) and pos.get(d) is not None:
                p = pos[d]
                pairs.append((math.hypot(c["xy_mm"][0] - p[0], c["xy_mm"][1] - p[1]), i, d))
    for _, i, d in sorted(pairs):
        if i not in assigned and d in free:
            assigned[i] = d
            free.discard(d)

    rows = []
    for i, c in enumerate(figure):
        rows.append({"figure_label": c.get("label") or c.get("id", ""), "figure_type": c["type"],
                     "design_id": assigned.get(i), "status": "matched" if i in assigned else "missing"})
    for d in [s.id for s in design.sources] + [e.id for e in design.elements]:
        if d in free:
            rows.append({"figure_label": "", "figure_type": types[d], "design_id": d, "status": "extra"})
    summary = {"matched": len(assigned), "in_figure": len(figure)}
    return rows, summary


def match_event(graph: dict, design: Design, tr: TraceResult | None) -> dict:
    rows, summary = match_rows(graph, design, tr)
    return {"type": "match", "rows": rows, "summary": summary}
