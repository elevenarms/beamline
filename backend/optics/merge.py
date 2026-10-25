"""Merge per-module Designs into one large multi-module Design.

    merge_modules(name, description, table, parts: [(Module, Design), ...]) -> Design
    place_design(design, prefix, offset, group) -> (sources, elements, targets)

Semantics
- Each module Design is authored in the LOCAL frame of its own region: origin at the
  region's lower-left corner, baseplate = region size (w, h).  merge_modules translates
  every Source.position and every absolute Element.at by the region origin (x, y);
  beam-relative placements (beam + distance_mm) need no change.
- Ids are namespaced "<module_id>.<id>" for sources, elements and target element_ids.
  Branch names start with their source id, so every Element.beam is prefixed the same
  way ("L1.t.+1" -> "cooling.L1.t.+1").  The tracer never parses branch names, so the
  extra dot is harmless.
- Every source/element gets group = module_id (outer merge wins when nesting).
- Targets are concatenated; module notes are folded into the merged notes.
- Design.modules of the result lists the Modules (regions in table coordinates).  Any
  modules of a nested part Design are flattened away (their contents keep the outer group).
- Modules exchange light only via fibers: each module starts with its own fiber-launch
  source(s) and ends in fiber couplers / dumps, so the modules trace independently and the
  merged design traces identically to its parts, offset by the region origins -- PROVIDED
  every beam terminates inside its module (a stray beam escapes at region+50 mm in the
  part but at table+50 mm in the merge, and could hit another module on the way).
"""
from __future__ import annotations

from .ir import Baseplate, Design, Element, Module, Source, Target


def _pref(prefix: str, s: str) -> str:
    return f"{prefix}.{s}" if prefix else s


def place_design(design: Design, prefix: str, offset: tuple[float, float], group: str | None
                 ) -> tuple[list[Source], list[Element], list[Target]]:
    """Return translated + namespaced copies of a design's sources, elements and targets."""
    ox, oy = offset
    sources = [s.model_copy(update={
        "id": _pref(prefix, s.id),
        "position": (s.position[0] + ox, s.position[1] + oy),
        "group": group if group is not None else s.group,
    }) for s in design.sources]
    elements = []
    for e in design.elements:
        upd = {"id": _pref(prefix, e.id), "group": group if group is not None else e.group}
        if e.at is not None:
            upd["at"] = (e.at[0] + ox, e.at[1] + oy)
        if e.beam is not None:
            upd["beam"] = _pref(prefix, e.beam)
        elements.append(e.model_copy(update=upd))
    targets = [t.model_copy(update={"element_id": _pref(prefix, t.element_id)}) for t in design.targets]
    return sources, elements, targets


def merge_modules(name: str, description: str, table: Baseplate,
                  parts: list[tuple[Module, Design]]) -> Design:
    ids = [m.id for m, _ in parts]
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate module ids: {ids}")
    sources: list[Source] = []
    elements: list[Element] = []
    targets: list[Target] = []
    notes: list[str] = []
    for mod, d in parts:
        s, e, t = place_design(d, mod.id, (mod.region[0], mod.region[1]), mod.id)
        sources += s
        elements += e
        targets += t
        if d.notes:
            notes.append(f"[{mod.id}] {d.notes}")
    return Design(name=name, description=description, modules=[m for m, _ in parts],
                  baseplate=table, sources=sources, elements=elements, targets=targets,
                  notes="\n".join(notes))


def local_baseplate(table: Baseplate, region: tuple[float, float, float, float]) -> Baseplate:
    """Baseplate for authoring a module in its region's local frame."""
    return table.model_copy(update={"width_mm": region[2], "height_mm": region[3]})


def region_violations(design: Design) -> list[str]:
    """Placed-by-`at`/source positions that fall outside their group's module region (cheap sanity check)."""
    regions = {m.id: m.region for m in design.modules}
    out = []
    for item in list(design.sources) + [e for e in design.elements if e.at is not None]:
        pos = item.position if isinstance(item, Source) else item.at
        r = regions.get(item.group or "")
        if r and not (r[0] <= pos[0] <= r[0] + r[2] and r[1] <= pos[1] <= r[1] + r[3]):
            out.append(f"{item.id} at {pos} outside module {item.group} region {r}")
    return out
