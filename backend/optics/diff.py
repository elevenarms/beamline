"""Deterministic design diff: what changed between two Designs (used to replay agent tuning)."""
from __future__ import annotations

from typing import Any

from optics.ir import Design, Element

_MOVE = {"distance_mm", "at"}
_ROTATE = {"angle_deg", "out_direction_deg"}
_RETARGET = {"beam"}
_SKIP = {"id", "label"}


def _change(op: str, element_id: str, field: str | None = None, frm: Any = None, to: Any = None,
            note: str | None = None) -> dict[str, Any]:
    return {"op": op, "element_id": element_id, "field": field, "from": frm, "to": to, "note": note}


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, (list, tuple)):
        return "(" + ", ".join(_fmt(x) for x in v) + ")"
    return str(v)


def diff_designs(a: Design | None, b: Design) -> list[dict[str, Any]]:
    """Changes turning design a into design b (a=None means everything in b was added)."""
    old: dict[str, Element] = {e.id: e for e in (a.elements if a else [])}
    new: dict[str, Element] = {e.id: e for e in b.elements}
    changes: list[dict[str, Any]] = []

    for eid, e in new.items():
        if eid not in old:
            where = f"on {e.beam} at {_fmt(e.distance_mm)} mm" if e.beam else f"at {_fmt(e.at)}"
            changes.append(_change("add", eid, note=f"added {e.type} {where}"))
            continue
        before, after = old[eid].model_dump(), e.model_dump()
        for field, to in after.items():
            frm = before.get(field)
            if field in _SKIP or frm == to:
                continue
            if isinstance(frm, (int, float)) and isinstance(to, (int, float)) and abs(frm - to) < 1e-9:
                continue
            op = ("move" if field in _MOVE else "rotate" if field in _ROTATE
                  else "retarget" if field in _RETARGET else "param")
            changes.append(_change(op, eid, field, frm, to, note=f"{field}: {_fmt(frm)} → {_fmt(to)}"))

    for eid, e in old.items():
        if eid not in new:
            changes.append(_change("remove", eid, note=f"removed {e.type}"))
    return changes
