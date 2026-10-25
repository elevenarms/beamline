"""2D planar ray + Gaussian-beam + Jones tracer for Beamline designs.

    trace(design: Design) -> TraceResult

Two passes:

1. **Placement pass** (PyOpticL-style).  Elements with ``at`` are positioned up
   front.  Every source is traced depth-first.  For the current segment on
   branch B, the *first not-yet-placed element in list order* with
   ``beam == B`` is placed ``distance_mm`` from the segment start -- unless an
   already-positioned element (any branch, or ``at``-placed) is physically
   intersected earlier, in which case the beam interacts with that one first.
   In this pass beams are never dropped for low power (geometry does not depend
   on polarization), so elements on a dark branch still get placed.
2. **Physics pass**.  All positions/orientations are frozen; beams are traced
   purely by ray/segment intersection.  This pass produces the segments, hits,
   powers and coupling numbers.  Branches below 1e-6 mW are dropped.

Geometry / orientation conventions (angles in degrees, CCW from +x)
-------------------------------------------------------------------
* Every element is a line segment through its position.  For transmissive
  parts and mirrors the segment is perpendicular to ``angle_deg`` and its length
  is the aperture.  Splitter cubes use their reflecting *diagonal* instead
  (length aperture*sqrt(2)) so they can be hit from all four faces.
* Transmissive parts (lens, waveplates, aom, iris, vapor_cell, isolator,
  fiber_coupler, photodiode, beam_dump): ``angle_deg`` = optical axis; default =
  incoming beam direction.  Isolator forward = along angle_deg; fiber coupler
  accepts light travelling along angle_deg.
* **Mirror**: ``angle_deg`` = surface normal, pointing toward the reflecting
  side.  If ``out_direction_deg`` is given, normal = direction of
  (u_out - u_in), i.e. the bisector that reflects the incoming beam into
  out_direction_deg (any angle except out == in; 180 deg = retro-reflection).
  Else if ``angle_deg`` is given it is used as the normal (flipped to face the
  incoming beam at placement time).  Otherwise: error.  A beam hitting the back
  of a mirror is absorbed.
* **Splitter cubes** (pbs, beamsplitter, sampler, dichroic): canonical rule --
  *a beam travelling along angle_deg is transmitted along angle_deg and
  reflected to angle_deg + 90* (diagonal normal points at angle_deg + 135).
  Default angle_deg = incoming direction, so the default reflection is +90
  (CCW, i.e. to the beam's left).  ``out_direction_deg`` picks the reflected
  direction and must be incoming +-90: out = in + 90 -> angle = in;
  out = in - 90 -> angle = in + 90 (reported angle_deg is always canonical).
  Beams from other faces reflect geometrically off the same diagonal (e.g. a
  beam travelling along angle_deg + 180 reflects to angle_deg + 270).
* **AOM**: order +1 is deflected CCW by theta = lambda*f/v, order -1 CW.  Zero
  order keeps direction with (1 - eff) power.
* **Lens** off-axis: ray rotated by -h/f rad, h = signed offset of the hit
  from the lens centre measured to the beam's left.

Physics conventions
-------------------
* Jones vector in the beam frame (x = H in-plane, y = V).  R = (1, -i)/sqrt2,
  L = (1, +i)/sqrt2.  Every reflection flips the sign of Ex.  A waveplate seen
  by a beam travelling against its axis has its fast axis mirrored (-phi).
* PBS: transmits Ex (H), reflects Ey (V).  Non-polarizing splitters by
  split_ratio (= reflected fraction).  Dichroic: reflects lambda < cutoff when
  reflect == "below" (default), defaults cutoff 650 nm.
* Clipping: transmitted fraction for a circular aperture radius r with beam
  radius w and in-plane offset h is (1 - exp(-2r^2/w^2)) * Tx(h)/Tx(0),
  Tx(h) = [erf(sqrt2 (r-h)/w) + erf(sqrt2 (r+h)/w)]/2 -- exact when centred,
  approximate offset correction.  A beam whose centre misses the aperture
  entirely does not interact.  Beam dumps do not clip.
* Fiber coupler: beam focused by the coupler lens (default f = 11 mm), fiber
  face fixed at the back focal plane, fiber mode w_f = MFD/2 (default 5 um).
  eta = Gaussian overlap (size + curvature) * exp(-(f*alpha/w_f)^2) (beam tilt
  alpha vs. coupler axis) * exp(-(pi w_f h/(lambda f))^2) (offset h at the
  lens) * clip.  Backside hits couple nothing.
* end_reason: "element" (passes on), "absorbed" (terminating element, mirror
  backside, isolator reverse, placement-error blocker), "escaped" (no hit
  within the baseplate + 50 mm margin or 2000 mm), "max_depth" (64
  interactions per path or 2000 segments in total).

CLI:  uv run python -m optics.trace path/to/design.json
"""
from __future__ import annotations

import cmath
import json
import math
import sys
from dataclasses import dataclass, field

from .ir import (
    SPLITTING,
    TERMINATING,
    Design,
    Element,
    ElementHit,
    PlacedElement,
    Segment,
    TraceResult,
)

# ───────────────────────────── constants / defaults ─────────────────────────

MAX_DEPTH = 64           # interactions along one path
MAX_SEGMENTS = 2000      # total segments per pass
ESCAPE_LEN = 2000.0      # mm
MARGIN = 50.0            # mm around the baseplate
MIN_POWER = 1e-6         # mW; dimmer branches are dropped in the physics pass
EPS = 1e-6

TRANSMISSIVE = {
    "lens", "half_wave_plate", "quarter_wave_plate", "aom", "iris", "vapor_cell",
    "isolator", "fiber_coupler", "photodiode", "beam_dump",
}


def default_aperture(t: str) -> float:
    return {"fiber_coupler": 6.0, "iris": 2.0}.get(t, 12.7)


# ───────────────────────────── small vector helpers ─────────────────────────

def _u(deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return (math.cos(a), math.sin(a))


def _ang(v: tuple[float, float]) -> float:
    return math.degrees(math.atan2(v[1], v[0]))


def _wrap(deg: float) -> float:
    """Wrap to (-180, 180]."""
    d = math.fmod(deg, 360.0)
    if d <= -180.0:
        d += 360.0
    elif d > 180.0:
        d -= 360.0
    return d


def _cross(a, b) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _rot(v, rad: float):
    c, s = math.cos(rad), math.sin(rad)
    return (c * v[0] - s * v[1], s * v[0] + c * v[1])


# ───────────────────────────── Gaussian helpers ─────────────────────────────

def _w_of_q(q: complex, lam_mm: float) -> float:
    inv = 1.0 / q
    return math.sqrt(-lam_mm / (math.pi * inv.imag)) if inv.imag < 0 else float("nan")


def _thin_lens(q: complex, f: float) -> complex:
    return 1.0 / (1.0 / q - 1.0 / f)


def clip_transmission(r: float, w: float, h: float = 0.0) -> float:
    """Fraction of a Gaussian (1/e^2 radius w) passing a circular aperture of
    radius r, with approximate correction for an in-plane centre offset h."""
    if w <= 0 or not math.isfinite(w):
        return 1.0
    t0 = 1.0 - math.exp(-2.0 * r * r / (w * w))
    if h == 0.0:
        return t0
    s2 = math.sqrt(2.0) / w
    tx0 = math.erf(s2 * r)
    txh = 0.5 * (math.erf(s2 * (r - h)) + math.erf(s2 * (r + h)))
    return max(0.0, t0 * txh / tx0) if tx0 > 0 else 0.0


def mode_overlap(q1: complex, q2: complex, lam_mm: float) -> float:
    """Power coupling between two circular Gaussian modes at the same plane.
    Field ~ exp(-a r^2), a = i k / (2 q).  eta = 4 / (w1^2 w2^2 |a1* + a2|^2)."""
    k = 2 * math.pi / lam_mm
    a1, a2 = 1j * k / (2 * q1), 1j * k / (2 * q2)
    w1sq, w2sq = 1.0 / a1.real, 1.0 / a2.real
    return min(1.0, 4.0 / (w1sq * w2sq * abs(a1.conjugate() + a2) ** 2))


# ───────────────────────────── polarization helpers ─────────────────────────

_S2 = 1 / math.sqrt(2)
_POL = {
    "H": (1 + 0j, 0j), "V": (0j, 1 + 0j),
    "D": (_S2 + 0j, _S2 + 0j), "A": (_S2 + 0j, -_S2 + 0j),
    "R": (_S2 + 0j, -1j * _S2), "L": (_S2 + 0j, 1j * _S2),
}


def jones_from_spec(spec) -> tuple[complex, complex]:
    if isinstance(spec, str):
        if spec in _POL:
            return _POL[spec]
        try:
            spec = float(spec)
        except ValueError:
            return _POL["H"]
    a = math.radians(float(spec))
    return (complex(math.cos(a)), complex(math.sin(a)))


def _normalize(ex: complex, ey: complex) -> tuple[complex, complex]:
    n = math.sqrt(abs(ex) ** 2 + abs(ey) ** 2)
    if n < 1e-15:
        return (1 + 0j, 0j)
    ex, ey = ex / n, ey / n
    # remove global phase so the larger-ish component is real positive
    ref = ex if abs(ex) > 1e-9 else ey
    ph = cmath.exp(-1j * cmath.phase(ref))
    return (ex * ph, ey * ph)


def polarization_label(ex: complex, ey: complex, tol: float = 0.02) -> str:
    ex, ey = _normalize(ex, ey)
    s1 = abs(ex) ** 2 - abs(ey) ** 2
    s2 = 2 * (ex.conjugate() * ey).real
    s3 = 2 * (ex.conjugate() * ey).imag
    if s3 > 1 - tol:
        return "L"
    if s3 < -(1 - tol):
        return "R"
    if abs(s3) < tol:
        psi = (0.5 * math.degrees(math.atan2(s2, s1))) % 180.0
        for name, ang in (("H", 0.0), ("D", 45.0), ("V", 90.0), ("A", 135.0), ("H", 180.0)):
            if abs(psi - ang) < 1.0:
                return name
        return f"linear {round(psi) % 180}°"
    return "elliptical"


def polarization_fidelity(ex: complex, ey: complex, spec) -> float:
    """|<target|E>|^2 for a target PolarizationSpec."""
    tx, ty = jones_from_spec(spec)
    ex, ey = _normalize(ex, ey)
    return abs(tx.conjugate() * ex + ty.conjugate() * ey) ** 2


def _waveplate(ex, ey, phi_deg: float, retard: float):
    """J = R(phi) diag(1, e^{i retard}) R(-phi)."""
    p = math.radians(phi_deg)
    c, s = math.cos(p), math.sin(p)
    e = cmath.exp(1j * retard)
    # R(-phi) E
    a = c * ex + s * ey
    b = -s * ex + c * ey
    b *= e
    return (c * a - s * b, s * a + c * b)


# ───────────────────────────── runtime state ────────────────────────────────

@dataclass
class _El:
    spec: Element
    idx: int
    type: str
    aperture: float
    pos: tuple[float, float] | None = None
    angle: float | None = None       # axis / mirror normal / canonical cube angle
    placed: bool = False             # has a position (and is usable)
    error: str | None = None
    blocker: bool = False            # positioned but broken: absorbs whatever hits it
    hits: list = field(default_factory=list)
    power_in: float = 0.0
    power_out: float = 0.0

    @property
    def positioned(self) -> bool:
        return self.pos is not None and (self.placed or self.blocker)


@dataclass
class _Beam:
    branch: str
    source_id: str
    pos: tuple[float, float]
    d: tuple[float, float]
    wl: float
    fshift: float
    power: float
    ex: complex
    ey: complex
    q: complex
    depth: int
    start_el: str | None


# ───────────────────────────── orientation ──────────────────────────────────

def _resolve_orientation(el: _El, d: tuple[float, float]) -> None:
    """Fix el.angle from the first beam (direction d) that reaches it."""
    if el.angle is not None or el.error:
        return
    sp, th = el.spec, _ang(d)
    if el.type == "mirror":
        if sp.out_direction_deg is not None:
            uo = _u(sp.out_direction_deg)
            n = (uo[0] - d[0], uo[1] - d[1])
            if math.hypot(*n) < 1e-6:
                el.error = (f"mirror {sp.id}: out_direction_deg {sp.out_direction_deg} equals the "
                            f"incoming direction {th:.1f}; a mirror cannot do that")
                return
            el.angle = _ang(n)
        elif sp.angle_deg is not None:
            a = sp.angle_deg
            if _dot(_u(a), d) > 0:   # make the normal face the incoming beam
                a += 180.0
            el.angle = _wrap(a)
        else:
            el.error = (f"mirror {sp.id}: needs out_direction_deg (desired outgoing direction) "
                        f"or angle_deg (surface normal); incoming beam direction is {th:.1f}°")
    elif el.type in SPLITTING:
        if sp.out_direction_deg is not None:
            diff = _wrap(sp.out_direction_deg - th)
            if abs(diff - 90) < 1.0:
                el.angle = _wrap(th)
            elif abs(diff + 90) < 1.0:
                el.angle = _wrap(th + 90)
            else:
                el.error = (f"{el.type} {sp.id}: out_direction_deg must be incoming ±90° "
                            f"(incoming {th:.1f}°, so {_wrap(th + 90):.1f} or {_wrap(th - 90):.1f})")
        elif sp.angle_deg is not None:
            el.angle = _wrap(sp.angle_deg)
        else:
            el.angle = _wrap(th)
    else:
        el.angle = _wrap(sp.angle_deg) if sp.angle_deg is not None else _wrap(th)


def _initial_angle(el: _El) -> None:
    """Orientation known without a beam (for `at` elements)."""
    sp = el.spec
    if el.type == "mirror":
        if sp.angle_deg is not None and sp.out_direction_deg is None:
            el.angle = _wrap(sp.angle_deg)
    elif sp.angle_deg is not None and not (el.type in SPLITTING and sp.out_direction_deg is not None):
        el.angle = _wrap(sp.angle_deg)


# ───────────────────────────── intersection ─────────────────────────────────

def _intersect(el: _El, p, d) -> float | None:
    """Distance along the ray to el, or None."""
    c = el.pos
    cp = (c[0] - p[0], c[1] - p[1])
    if el.angle is None or el.blocker:
        # orientation unknown: treat as a disk of diameter aperture, hit at closest approach
        s = _dot(cp, d)
        if s > EPS and abs(_cross(d, cp)) <= el.aperture / 2:
            return s
        return None
    if el.type in SPLITTING:
        tdeg, half = el.angle + 135.0 + 90.0, el.aperture / math.sqrt(2)
    else:
        tdeg, half = el.angle + 90.0, el.aperture / 2
    t = _u(tdeg)
    den = _cross(d, t)
    if abs(den) < 1e-12:
        return None
    s = _cross(cp, t) / den
    u = _cross(cp, d) / den
    if s > EPS and abs(u) <= half + 1e-9:
        # beam centre must also be inside the clear aperture as seen by the beam
        if abs(_cross(d, cp)) <= el.aperture / 2 + 1e-9:
            return s
    return None


def _nearest(els: list[_El], beam: _Beam) -> tuple[_El | None, float]:
    best, bs = None, math.inf
    for el in els:
        if not el.positioned or el.spec.id == beam.start_el:
            continue
        s = _intersect(el, beam.pos, beam.d)
        if s is not None and s < bs:
            best, bs = el, s
    return best, bs


def _escape_len(p, d, box) -> float:
    x0, y0, x1, y1 = box
    t = ESCAPE_LEN
    for pi, di, lo, hi in ((p[0], d[0], x0, x1), (p[1], d[1], y0, y1)):
        if abs(di) > 1e-12:
            t = min(t, max((lo - pi) / di, (hi - pi) / di))
    return max(t, 0.0)


# ───────────────────────────── interactions ─────────────────────────────────

def _interact(el: _El, beam: _Beam, s: float, hit, seg_id: str | None, physics: bool):
    """Return (outputs: list[_Beam], absorbed: bool)."""
    sp, typ = el.spec, el.type
    lam = beam.wl * 1e-6
    q = beam.q + s
    w = _w_of_q(q, lam)
    d = beam.d
    c = el.pos
    h = _cross(d, (hit[0] - c[0], hit[1] - c[1]))   # signed offset, + = beam's left

    T = 1.0 if typ == "beam_dump" else clip_transmission(el.aperture / 2, w, abs(h))
    if physics:
        el.hits.append(ElementHit(segment_id=seg_id, power_in_mw=beam.power, w_mm=w,
                                  clip_loss=1.0 - T, offset_mm=abs(h)))
        el.power_in += beam.power
    P = beam.power * T
    depth = beam.depth + 1

    def out(branch, dvec, power, ex, ey, qq=q, fshift=beam.fshift):
        ex, ey = _normalize(ex, ey)
        return _Beam(branch, beam.source_id, hit, dvec, beam.wl, fshift, power, ex, ey, qq, depth, sp.id)

    if el.blocker:
        return [], True

    axis = _u(el.angle) if el.angle is not None else d
    forward = _dot(d, axis) >= 0

    if typ == "mirror":
        n = axis
        dn = _dot(d, n)
        if dn > 0:   # back of the mirror
            return [], True
        r = (d[0] - 2 * dn * n[0], d[1] - 2 * dn * n[1])
        return [out(beam.branch, r, P, -beam.ex, beam.ey)], False

    if typ in SPLITTING:
        n = _u(el.angle + 135.0)
        dn = _dot(d, n)
        r = (d[0] - 2 * dn * n[0], d[1] - 2 * dn * n[1])
        ex, ey = beam.ex, beam.ey
        if typ == "pbs":
            pt, pr = P * abs(ex) ** 2, P * abs(ey) ** 2
            jt, jr = (ex, 0j), (0j, ey)
        else:
            if typ == "dichroic":
                cutoff = sp.cutoff_nm if sp.cutoff_nm is not None else 650.0
                below = beam.wl < cutoff
                R = 1.0 if (below == ((sp.reflect or "below") == "below")) else 0.0
            else:
                R = sp.split_ratio if sp.split_ratio is not None else (0.05 if typ == "sampler" else 0.5)
            pt, pr = P * (1 - R), P * R
            jt, jr = (ex, ey), (ex, ey)
        return [out(beam.branch + ".t", d, pt, *jt),
                out(beam.branch + ".r", r, pr, -jr[0], jr[1])], False

    if typ == "lens":
        f = sp.focal_length_mm if sp.focal_length_mm else 100.0
        nd = _rot(d, -h / f)
        return [out(beam.branch, nd, P, beam.ex, beam.ey, qq=_thin_lens(q, f))], False

    if typ in ("half_wave_plate", "quarter_wave_plate"):
        phi = sp.fast_axis_deg or 0.0
        if not forward:
            phi = -phi
        ret = math.pi if typ == "half_wave_plate" else math.pi / 2
        ex, ey = _waveplate(beam.ex, beam.ey, phi, ret)
        return [out(beam.branch, d, P, ex, ey)], False

    if typ == "aom":
        f_mhz = sp.aom_frequency_mhz if sp.aom_frequency_mhz is not None else 80.0
        eff = sp.aom_efficiency if sp.aom_efficiency is not None else 0.8
        order = sp.aom_order if sp.aom_order is not None else 1
        v = sp.acoustic_velocity_m_s if sp.acoustic_velocity_m_s else 4200.0
        theta = beam.wl * 1e-9 * f_mhz * 1e6 / v
        tag = ".+1" if order == 1 else ".-1"
        return [out(beam.branch + ".0", d, P * (1 - eff), beam.ex, beam.ey),
                out(beam.branch + tag, _rot(d, order * theta), P * eff, beam.ex, beam.ey,
                    fshift=beam.fshift + order * f_mhz)], False

    if typ == "iris":
        return [out(beam.branch, d, P, beam.ex, beam.ey)], False

    if typ == "vapor_cell":
        tr = sp.transmission if sp.transmission is not None else 1.0
        return [out(beam.branch, d, P * tr, beam.ex, beam.ey)], False

    if typ == "isolator":
        if not forward:
            return [], True
        tr = sp.transmission if sp.transmission is not None else 0.9
        return [out(beam.branch, d, P * tr, beam.ex, beam.ey)], False

    if typ == "fiber_coupler":
        if physics and forward:
            f = sp.focal_length_mm if sp.focal_length_mm else 11.0
            wf = (sp.fiber_mfd_um if sp.fiber_mfd_um else 5.0) * 1e-3 / 2
            q_face = _thin_lens(q, f) + f
            q_fib = 1j * math.pi * wf * wf / lam
            eta = mode_overlap(q_face, q_fib, lam)
            alpha = math.acos(max(-1.0, min(1.0, _dot(d, axis))))
            eta *= math.exp(-((f * alpha / wf) ** 2))
            eta *= math.exp(-((math.pi * wf * h / (lam * f)) ** 2))
            el.power_out += P * eta
        return [], True

    if typ == "photodiode":
        if physics:
            el.power_out += P
        return [], True

    if typ == "beam_dump":
        if physics:
            el.power_out += P
        return [], True

    return [out(beam.branch, d, P, beam.ex, beam.ey)], False


# ───────────────────────────── main loop ────────────────────────────────────

def _run(design: Design, els: list[_El], physics: bool):
    bp = design.baseplate
    box = (-MARGIN, -MARGIN, bp.width_mm + MARGIN, bp.height_mm + MARGIN)
    segments: list[Segment] = []
    branches: list[str] = []
    seen: set[str] = set()
    branch_end: dict[str, str] = {}
    by_branch: dict[str, list[_El]] = {}
    for el in els:
        if el.spec.beam is not None:
            by_branch.setdefault(el.spec.beam, []).append(el)

    def next_child(branch: str) -> _El | None:
        for el in by_branch.get(branch, ()):
            if not el.placed and not el.error:
                return el
        return None

    for src in design.sources:
        lam = src.wavelength_nm * 1e-6
        zr = math.pi * src.waist_mm ** 2 / lam
        ex, ey = _normalize(*jones_from_spec(src.polarization))
        stack = [_Beam(src.id, src.id, tuple(src.position), _u(src.direction_deg), src.wavelength_nm,
                       0.0, src.power_mw, ex, ey, complex(-src.waist_offset_mm, zr), 0, src.id)]
        while stack:
            beam = stack.pop()
            if physics and beam.power < MIN_POWER:
                continue
            if beam.branch not in seen:
                seen.add(beam.branch)
                branches.append(beam.branch)

            target, s = _nearest(els, beam)
            if not physics:
                child = next_child(beam.branch)
                if child is not None:
                    dist = child.spec.distance_mm
                    if dist is None or dist <= 0:
                        child.error = f"{child.spec.id}: distance_mm must be > 0 (got {dist})"
                    elif dist <= s:
                        child.pos = (beam.pos[0] + dist * beam.d[0], beam.pos[1] + dist * beam.d[1])
                        _resolve_orientation(child, beam.d)
                        if child.error:
                            child.blocker = True
                        else:
                            child.placed = True
                        target, s = child, dist
                    # re-run this beam if the child errored before being positioned
                    if child.error and not child.blocker:
                        stack.append(beam)
                        continue

            over = beam.depth >= MAX_DEPTH or len(segments) >= MAX_SEGMENTS
            if target is None:
                s = _escape_len(beam.pos, beam.d, box)
            end = (beam.pos[0] + s * beam.d[0], beam.pos[1] + s * beam.d[1])
            seg_id = f"s{len(segments)}"
            reason = "max_depth" if over else ("escaped" if target is None else "element")

            outputs, absorbed = [], False
            if target is not None and not over:
                if target.angle is None and not target.blocker:
                    _resolve_orientation(target, beam.d)
                    if target.error:
                        target.blocker = True
                outputs, absorbed = _interact(target, beam, s, end, seg_id, physics)
                if absorbed:
                    reason = "absorbed"
            if reason != "element":
                branch_end[beam.branch] = (
                    f"absorbed at {target.spec.id}" if reason == "absorbed" else
                    "escaped without hitting anything" if reason == "escaped" else
                    "hit the interaction depth limit")

            if physics or len(segments) < MAX_SEGMENTS:
                lam = beam.wl * 1e-6
                q0 = beam.q
                zr = max(q0.imag, 1e-12)
                segments.append(Segment(
                    id=seg_id, branch=beam.branch, source_id=beam.source_id,
                    start=beam.pos, end=end, direction_deg=_ang(beam.d), length_mm=s,
                    wavelength_nm=beam.wl, freq_shift_mhz=beam.fshift, power_mw=beam.power,
                    jones=((beam.ex.real, beam.ex.imag), (beam.ey.real, beam.ey.imag)),
                    polarization_label=polarization_label(beam.ex, beam.ey),
                    waist_z_mm=-q0.real, rayleigh_mm=zr, w0_mm=math.sqrt(lam * zr / math.pi),
                    w_start_mm=_w_of_q(q0, lam), w_end_mm=_w_of_q(q0 + s, lam),
                    start_element=beam.start_el,
                    end_element=target.spec.id if target is not None else None,
                    end_reason=reason,
                ))
            # depth-first, first output first
            for ob in reversed(outputs):
                stack.append(ob)
    return segments, branches, branch_end


def trace(design: Design) -> TraceResult:
    els = [_El(spec=e, idx=i, type=e.type,
               aperture=e.aperture_mm if e.aperture_mm else default_aperture(e.type))
           for i, e in enumerate(design.elements)]
    ids = {}
    for el in els:
        if el.spec.id in ids:
            el.error = f"duplicate element id {el.spec.id!r}"
        ids[el.spec.id] = el
        if el.spec.at is not None and not el.error:
            el.pos = tuple(el.spec.at)
            el.placed = True
            _initial_angle(el)

    # pass 1: placement
    _, place_branches, branch_end = _run(design, els, physics=False)

    for el in els:
        if el.placed or el.error:
            continue
        b = el.spec.beam
        if b not in place_branches:
            el.error = (f"{el.spec.id}: branch {b!r} never existed; existing branches: "
                        f"{', '.join(place_branches) or '(none)'}")
        else:
            earlier = [o.spec.id for o in els if o.spec.beam == b and o.idx < el.idx and not o.placed]
            why = branch_end.get(b, "ended")
            el.error = (f"{el.spec.id}: branch {b!r} {why} before this element was reached "
                        f"(elements on a branch are placed in list order"
                        + (f"; earlier unplaced on this branch: {', '.join(earlier)}" if earlier else "")
                        + ")")

    # pass 2: physics
    for el in els:
        el.hits, el.power_in, el.power_out = [], 0.0, 0.0
    segments, branches, _ = _run(design, els, physics=True)

    out = []
    for el in els:
        pe = PlacedElement(id=el.spec.id, type=el.type, placed=el.placed and not el.error,
                           position=el.pos, angle_deg=el.angle, hits=el.hits, error=el.error)
        if el.type in TERMINATING:
            pe.power_out_mw = el.power_out
            if el.type == "fiber_coupler":
                pe.coupling_efficiency = el.power_out / el.power_in if el.power_in > 0 else 0.0
        out.append(pe)
    return TraceResult(segments=segments, elements=out, branches=branches)


# ───────────────────────────── CLI ──────────────────────────────────────────

def _main(argv: list[str]) -> int:
    import time

    from .verify import verify

    if len(argv) < 2:
        print("usage: python -m optics.trace design.json")
        return 2
    with open(argv[1]) as f:
        design = Design.model_validate(json.load(f))
    t0 = time.perf_counter()
    tr = trace(design)
    t1 = time.perf_counter()
    rep = verify(design, tr)
    t2 = time.perf_counter()
    print(f"{design.name}: {len(tr.segments)} segments, branches {tr.branches}")
    print(f"{'id':>5} {'branch':<14} {'start':>16} {'end':>16} {'dir':>7} {'len':>7} "
          f"{'P mW':>8} {'pol':<11} {'w0':>6} {'z0':>7} {'end':<10} reason")
    for s in tr.segments:
        print(f"{s.id:>5} {s.branch:<14} ({s.start[0]:6.1f},{s.start[1]:6.1f}) "
              f"({s.end[0]:6.1f},{s.end[1]:6.1f}) {s.direction_deg:7.1f} {s.length_mm:7.1f} "
              f"{s.power_mw:8.3f} {s.polarization_label:<11} {s.w0_mm:6.3f} {s.waist_z_mm:7.1f} "
              f"{(s.end_element or '-'):<10} {s.end_reason}")
    print("\nelements:")
    for e in tr.elements:
        pos = f"({e.position[0]:.1f},{e.position[1]:.1f})" if e.position else "-"
        ang = f"{e.angle_deg:.1f}" if e.angle_deg is not None else "-"
        extra = ""
        if e.power_out_mw is not None:
            extra += f" out={e.power_out_mw:.3f}mW"
        if e.coupling_efficiency is not None:
            extra += f" eta={e.coupling_efficiency:.3f}"
        if e.hits:
            extra += f" hits={len(e.hits)} maxclip={max(h.clip_loss for h in e.hits):.3f}"
        print(f"  {e.id:<10} {e.type:<18} placed={e.placed!s:<5} {pos:<16} {ang:>7}{extra}"
              + (f"  ERROR: {e.error}" if e.error else ""))
    print(f"\nreport: passed={rep.passed} score={rep.score:.1f}")
    for c in rep.checks:
        print(f"  [{c.severity}] {c.id}: {c.message}")
    print("  metrics: " + ", ".join(f"{k}={v:.3g}" for k, v in rep.metrics.items()))
    print(f"\ntrace {1e3 * (t1 - t0):.2f} ms, verify {1e3 * (t2 - t1):.2f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
