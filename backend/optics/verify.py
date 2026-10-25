"""verify(design, trace) -> VerifyReport.

Checks (Check.id):
  unplaced            error    element could not be placed (message from the tracer)
  clipping            warning  clip loss > 1 % at a hit; error if > 10 % (beam dumps exempt)
  stray_beam          error    escaped segment carrying > 0.5 mW ("laser safety: unterminated beam");
                      warning  0.05 - 0.5 mW
  off_table           error    element position outside the baseplate
  collision           warning  two element footprints overlap
  beam_through_mount  warning  a segment crosses another element's footprint without interacting
  target              error    a design Target is unmet (info when met)
  max_depth           warning  tracing hit the interaction/segment cap
  no_light            info     placed element receives no light
  nonlinear_convergence warning  soa/sfg/saturable-absorber fixed-point iteration did not converge

Footprints (along optical axis/normal x across, mm), centred on the element position:
  mirror 25x25, lens 15x25, waveplates 15x25, cubes (pbs/beamsplitter/sampler/dichroic) 20x20,
  aom 40x25, iris 10x25, fiber_coupler 30x30, photodiode 30x20, beam_dump 10x10 (compact razor/knife-edge block),
  vapor_cell 75x25, isolator 50x25, soa 30x20 (butterfly module), sfg_crystal 20x15,
  saturable_absorber 10x25.
For beam_through_mount the footprint is shrunk by 2 mm per side to tolerate near misses.

Score: 95 + 5 * delivered/input, -25 per error, -5 per warning, clamped to 0..100.
delivered_mw = power coupled into fibers + absorbed by photodiodes (beam dumps excluded, see dumped_mw).
"""
from __future__ import annotations

import math

from .ir import Check, Design, TraceResult, VerifyReport
from .trace import polarization_fidelity

FOOTPRINT = {
    "mirror": (25, 25), "lens": (15, 25), "half_wave_plate": (15, 25), "quarter_wave_plate": (15, 25),
    "pbs": (20, 20), "beamsplitter": (20, 20), "sampler": (20, 20), "dichroic": (20, 20),
    "aom": (40, 25), "iris": (10, 25), "fiber_coupler": (30, 30), "photodiode": (30, 20),
    "beam_dump": (10, 10), "vapor_cell": (75, 25), "isolator": (50, 25),
    "soa": (30, 20), "sfg_crystal": (20, 15), "saturable_absorber": (10, 25),
}


def _rect(pos, angle_deg, size, shrink=0.0):
    """Corners of an oriented rectangle."""
    a = math.radians(angle_deg or 0.0)
    ux, uy = math.cos(a), math.sin(a)
    vx, vy = -uy, ux
    hl, hw = max(size[0] / 2 - shrink, 0.1), max(size[1] / 2 - shrink, 0.1)
    cx, cy = pos
    return [(cx + sx * hl * ux + sy * hw * vx, cy + sx * hl * uy + sy * hw * vy)
            for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1))]


def _axes(poly):
    out = []
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        out.append((-(y1 - y0), x1 - x0))
    return out


def _sat(p1, p2) -> bool:
    """Separating-axis overlap test for convex polygons (a segment = 2-point polygon)."""
    for ax in _axes(p1) + _axes(p2):
        if ax == (0, 0):
            continue
        a = [ax[0] * x + ax[1] * y for x, y in p1]
        b = [ax[0] * x + ax[1] * y for x, y in p2]
        if max(a) < min(b) - 1e-9 or max(b) < min(a) - 1e-9:
            return False
    return True


def verify(design: Design, trace: TraceResult) -> VerifyReport:
    checks: list[Check] = []
    els = {e.id: e for e in trace.elements}
    bp = design.baseplate

    # unplaced
    for e in trace.elements:
        if e.error or not e.placed:
            checks.append(Check(id="unplaced", severity="error", element_id=e.id,
                                message=e.error or f"{e.id} could not be placed"))

    # clipping
    seg_by_id = {s.id: s for s in trace.segments}
    for e in trace.elements:
        if e.type == "beam_dump":
            continue
        for h in e.hits:
            if h.clip_loss > 0.01 and h.power_in_mw > 1e-4:
                sev = "error" if h.clip_loss > 0.10 else "warning"
                checks.append(Check(
                    id="clipping", severity=sev, element_id=e.id, segment_id=h.segment_id,
                    value=h.clip_loss, limit=0.10 if sev == "error" else 0.01,
                    message=(f"{e.id}: {100 * h.clip_loss:.1f}% clipped (beam radius {h.w_mm:.2f} mm, "
                             f"offset {h.offset_mm:.2f} mm)")))

    # stray beams / depth
    stray = 0.0
    for s in trace.segments:
        if s.end_reason == "escaped":
            stray += s.power_mw
            if s.power_mw > 0.5:
                checks.append(Check(id="stray_beam", severity="error", segment_id=s.id, value=s.power_mw,
                                    limit=0.5, message=(f"laser safety: unterminated beam on {s.branch} "
                                                        f"({s.power_mw:.2f} mW) leaves the table from "
                                                        f"({s.start[0]:.0f},{s.start[1]:.0f}) at "
                                                        f"{s.direction_deg:.0f}°; add a beam dump")))
            elif s.power_mw > 0.05:
                checks.append(Check(id="stray_beam", severity="warning", segment_id=s.id, value=s.power_mw,
                                    limit=0.05, message=f"weak unterminated beam on {s.branch} ({s.power_mw:.3f} mW)"))
        elif s.end_reason == "max_depth":
            checks.append(Check(id="max_depth", severity="warning", segment_id=s.id,
                                message=f"trace depth limit reached on {s.branch} (cavity or loop?)"))

    for eid in getattr(trace, "nonconverged", None) or []:
        checks.append(Check(id="nonlinear_convergence", severity="warning", element_id=eid,
                            message=(f"{eid}: power-dependent state did not converge in 12 iterations "
                                     f"(feedback loop / bistability?); powers downstream are approximate")))

    # off table
    for e in trace.elements:
        if e.position is None:
            continue
        x, y = e.position
        if not (0 <= x <= bp.width_mm and 0 <= y <= bp.height_mm):
            checks.append(Check(id="off_table", severity="error", element_id=e.id,
                                message=(f"{e.id} at ({x:.0f},{y:.0f}) is outside the "
                                         f"{bp.width_mm:.0f}x{bp.height_mm:.0f} mm baseplate")))

    # collisions + beams through mounts
    placed = [e for e in trace.elements if e.position is not None]
    elem_by_id = {e.id: e for e in design.elements}

    def footprint(e) -> tuple[float, float]:
        # A beam dump with an explicit aperture is a knife-edge/razor block sized by that aperture,
        # e.g. for picking off one AOM order ~1 mm from its neighbour.
        spec = elem_by_id.get(e.id)
        if e.type == "beam_dump" and spec is not None and spec.aperture_mm:
            return (4.0, spec.aperture_mm + 4.0)
        return FOOTPRINT.get(e.type, (20, 20))

    def bbox(pts):
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    def bb_overlap(a, b) -> bool:
        return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]

    rects = {e.id: _rect(e.position, e.angle_deg, footprint(e)) for e in placed}
    boxes = {k: bbox(v) for k, v in rects.items()}
    for i, a in enumerate(placed):
        ba = boxes[a.id]
        for b in placed[i + 1:]:
            if not bb_overlap(ba, boxes[b.id]):   # AABB pre-check before the exact SAT test
                continue
            if _sat(rects[a.id], rects[b.id]):
                checks.append(Check(id="collision", severity="warning", element_id=a.id,
                                    message=f"{a.id} and {b.id} footprints overlap "
                                            f"({math.dist(a.position, b.position):.1f} mm apart)"))
    small = {e.id: _rect(e.position, e.angle_deg, footprint(e), shrink=2.0) for e in placed}
    small_boxes = [(e, small[e.id], bbox(small[e.id])) for e in placed]
    flagged = set()
    for s in trace.segments:
        if s.power_mw < 1e-3:
            continue
        seg = [tuple(s.start), tuple(s.end)]
        sb = bbox(seg)
        for e, poly, eb in small_boxes:
            if not bb_overlap(sb, eb):
                continue
            if e.id in (s.start_element, s.end_element) or (s.id, e.id) in flagged:
                continue
            if _sat(seg, poly):
                flagged.add((s.id, e.id))
                checks.append(Check(id="beam_through_mount", severity="warning", element_id=e.id,
                                    segment_id=s.id,
                                    message=f"beam {s.branch} passes through {e.id}'s mount without interacting"))

    # no light
    for e in trace.elements:
        if e.placed and not e.hits:
            checks.append(Check(id="no_light", severity="info", element_id=e.id,
                                message=f"{e.id} receives no light"))

    # metrics
    input_mw = sum(s.power_mw for s in design.sources)
    delivered = sum(e.power_out_mw or 0.0 for e in trace.elements
                    if e.type in ("fiber_coupler", "photodiode"))
    dumped = sum(e.power_out_mw or 0.0 for e in trace.elements if e.type == "beam_dump")
    metrics = {"input_mw": input_mw, "delivered_mw": delivered, "dumped_mw": dumped, "stray_mw": stray,
               "n_elements": float(len(design.elements)), "n_segments": float(len(trace.segments))}

    # targets
    for t in design.targets:
        e = els.get(t.element_id)
        key = f"target.{t.element_id}.{t.kind}"
        if e is None:
            checks.append(Check(id="target", severity="error", element_id=t.element_id,
                                message=f"target references unknown element {t.element_id}"))
            continue
        power_in = sum(h.power_in_mw for h in e.hits)
        if t.kind == "min_power_mw":
            val = e.power_out_mw if e.power_out_mw is not None else power_in
            ok = val >= float(t.value) * (1 - 1e-6) - 1e-9  # tolerate float round-off
            msg = f"{e.id}: {val:.3f} mW (need ≥ {float(t.value):.3f})"
        elif t.kind == "min_coupling":
            val = e.coupling_efficiency or 0.0
            ok = val >= float(t.value) * (1 - 1e-6) - 1e-9  # tolerate float round-off
            msg = f"{e.id}: coupling {100 * val:.1f}% (need ≥ {100 * float(t.value):.1f}%)"
        else:
            val, label = 0.0, "no light"
            if e.hits:
                h = max(e.hits, key=lambda h: h.power_in_mw)
                s = seg_by_id.get(h.segment_id)
                if s is not None:
                    (exr, exi), (eyr, eyi) = s.jones
                    val = polarization_fidelity(complex(exr, exi), complex(eyr, eyi), t.value)
                    label = s.polarization_label
            ok = val >= 0.98
            msg = f"{e.id}: polarization {label} (need {t.value}, overlap {100 * val:.1f}%)"
        metrics[key] = float(val)
        checks.append(Check(id="target", severity="info" if ok else "error", element_id=e.id,
                            value=float(val), limit=float(t.value) if not isinstance(t.value, str) else None,
                            message=("met: " if ok else "unmet: ") + msg))

    n_err = sum(c.severity == "error" for c in checks)
    n_warn = sum(c.severity == "warning" for c in checks)
    frac = delivered / input_mw if input_mw > 0 else 0.0
    score = max(0.0, min(100.0, 95.0 + 5.0 * frac - 25.0 * n_err - 5.0 * n_warn))
    metrics["delivered_fraction"] = frac
    return VerifyReport(passed=n_err == 0, score=score, checks=checks, metrics=metrics)
