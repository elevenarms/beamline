"""Export a Beamline `Design` as a runnable PyOpticL (FreeCAD) script.

PyOpticL (https://github.com/UMassIonTrappers/PyOpticL, UMass Ion Trappers) is a
code-to-CAD optics library: optics are placed along a BeamPath by beam index and
distance, and the baseplate / mounts / drill holes are generated in FreeCAD.
The generated script follows the style of PyOpticL's Designs/modules/doublepass.py.

Conversions
- Units: our mm map 1:1 to `dim(x, "mm")`; power mW -> W.
- Frame: the PyOpticL Baseplate is created with grid_offset=(0, 0) so its lower-left
  corner is the origin, exactly like our table frame.
- Beam index: the source is 0b1; at a splitter transmitted = i<<1, reflected = (i<<1)+1
  (our ".t"/".r"); an AOM with N orders appends ceil(log2 N) bits (PyOpticL's AOM has
  orders [0, +1], so ".0" -> i<<1 and ".+1"/".-1" -> (i<<1)+1).
- Rotation: reflectors (mirror, sampler, dichroic) take the absolute surface-normal
  angle = bisector of (-incoming, outgoing); transmissive parts take the beam axis;
  stops (fiberport, photodetector, iris) face the beam (axis + 180).
  Cubes use rotate_cube to choose which side the reflected port is on; the AOM is
  flipped 180 deg when the diffracted order leaves on the clockwise side.
Element orientations are taken from the Beamline tracer when available, otherwise
from a light-weight built-in walk of the design.
"""
from __future__ import annotations

import math
import re

from optics.ir import Design, Element, TraceResult

_STOPS = {"fiber_coupler", "photodiode", "iris"}
_REFLECTORS = {"mirror", "sampler", "dichroic"}
_CUBES = {"pbs", "beamsplitter"}
_UNSUPPORTED = {"vapor_cell", "isolator", "beam_dump"}


# ───────────────────────────── helpers ─────────────────────────────

def _norm(a: float) -> float:
    a = math.fmod(a, 360.0)
    if a > 180.0:
        a -= 360.0
    if a <= -180.0:
        a += 360.0
    return 0.0 if abs(a) < 1e-9 else a


def _fmt(x: float) -> str:
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _ident(s: str) -> str:
    s = re.sub(r"\W", "_", s)
    return s if s and not s[0].isdigit() else f"_{s}"


def _cross(a_deg: float, b_deg: float) -> float:
    a, b = math.radians(a_deg), math.radians(b_deg)
    return math.cos(a) * math.sin(b) - math.sin(a) * math.cos(b)


def _bisector(d_in: float, d_out: float) -> float:
    """Surface-normal angle for a reflector turning d_in into d_out."""
    back = math.radians(d_in + 180.0)
    out = math.radians(d_out)
    x, y = math.cos(back) + math.cos(out), math.sin(back) + math.sin(out)
    if math.hypot(x, y) < 1e-9:  # grazing (no turn) — normal perpendicular
        return _norm(d_in + 90.0)
    return _norm(math.degrees(math.atan2(y, x)))


def _reflect(d: float, normal: float) -> float:
    return _norm(2.0 * normal - d + 180.0)


def branch_to_index(branch: str, source_ids: list[str]) -> tuple[str, int]:
    """'L1.r.+1' -> ('L1', 0b111). Source id is the longest matching prefix."""
    src = max((s for s in source_ids if branch == s or branch.startswith(s + ".")),
              key=len, default=None)
    if src is None:
        src = branch.split(".")[0]
    rest = branch[len(src):].lstrip(".")
    idx = 1
    for tok in [t for t in rest.split(".") if t] if rest else []:
        if tok in ("t", "0"):
            idx = idx << 1
        elif tok in ("r", "+1", "-1", "1"):
            idx = (idx << 1) + 1
        else:
            raise ValueError(f"unknown branch suffix {tok!r} in {branch!r}")
    return src, idx


# ───────────────────────────── geometry ─────────────────────────────

class _Geo:
    """Per element: position, incoming direction, reflected/diffracted direction."""

    def __init__(self) -> None:
        self.pos: dict[str, tuple[float, float]] = {}
        self.d_in: dict[str, float] = {}
        self.d_side: dict[str, float] = {}  # mirror out / splitter reflected / AOM diffracted


def _geo_from_trace(design: Design, tr: TraceResult) -> _Geo:
    g = _Geo()
    for pe in tr.elements:
        if pe.placed and pe.position is not None:
            g.pos[pe.id] = pe.position
    first_in: dict[str, object] = {}
    for s in tr.segments:
        if s.end_element and s.end_reason == "element" and s.end_element not in first_in:
            first_in[s.end_element] = s
    for el in design.elements:
        s_in = first_in.get(el.id)
        if s_in is None:
            continue
        g.d_in[el.id] = s_in.direction_deg
        outs = [s for s in tr.segments if s.start_element == el.id]
        want: list[str] = []
        if el.type == "mirror":
            want = [s_in.branch]
        elif el.type in _CUBES or el.type in ("sampler", "dichroic"):
            want = [s_in.branch + ".r"]
        elif el.type == "aom":
            want = [s_in.branch + ".+1", s_in.branch + ".-1"]
        for s in outs:
            if s.branch in want:
                g.d_side[el.id] = s.direction_deg
                break
    return g


def _geo_fallback(design: Design) -> _Geo:
    """Simple sequential walk (used only when the tracer is unavailable)."""
    g = _Geo()
    st: dict[str, tuple[float, float, float]] = {
        s.id: (s.position[0], s.position[1], s.direction_deg) for s in design.sources}
    for el in design.elements:
        if el.at is not None:
            g.pos[el.id] = el.at
            if el.angle_deg is not None:
                g.d_in[el.id] = el.angle_deg + (180.0 if el.type in _STOPS else 0.0)
            continue
        if el.beam not in st:
            continue
        x, y, d = st[el.beam]
        r = math.radians(d)
        x, y = x + el.distance_mm * math.cos(r), y + el.distance_mm * math.sin(r)
        g.pos[el.id], g.d_in[el.id] = (x, y), d
        b = el.beam
        if el.type == "mirror":
            if el.out_direction_deg is not None:
                out = el.out_direction_deg
            elif el.angle_deg is not None:
                out = _reflect(d, el.angle_deg)
            else:
                out = d
            g.d_side[el.id] = out
            st[b] = (x, y, out)
        elif el.type in _CUBES or el.type in ("sampler", "dichroic"):
            if el.out_direction_deg is not None:
                rd = el.out_direction_deg
            elif el.angle_deg is not None and el.type not in _CUBES:
                rd = _reflect(d, el.angle_deg)
            else:
                rd = _norm(d + 90.0)
            g.d_side[el.id] = rd
            st[b + ".t"] = (x, y, d)
            st[b + ".r"] = (x, y, rd)
        elif el.type == "aom":
            order = el.aom_order or 1
            theta = math.degrees((780e-9 * (el.aom_frequency_mhz or 80) * 1e6)
                                 / (el.acoustic_velocity_m_s or 4200))
            g.d_side[el.id] = _norm(d + order * theta)
            st[b + ".0"] = (x, y, d)
            st[b + (".+1" if order > 0 else ".-1")] = (x, y, g.d_side[el.id])
        elif el.type in ("fiber_coupler", "photodiode", "beam_dump"):
            st.pop(b, None)
        else:
            st[b] = (x, y, d)
    return g


def _geometry(design: Design, tr: TraceResult | None) -> _Geo:
    if tr is None:
        try:
            from optics.trace import trace  # type: ignore

            tr = trace(design)
        except Exception:  # noqa: BLE001 — tracer missing or crashed
            tr = None
    fb = _geo_fallback(design)
    if tr is None:
        return fb
    g = _geo_from_trace(design, tr)
    for k, v in fb.pos.items():  # fill gaps from the fallback walk
        g.pos.setdefault(k, v)
    for k, v in fb.d_in.items():
        g.d_in.setdefault(k, v)
    for k, v in fb.d_side.items():
        g.d_side.setdefault(k, v)
    return g


# ───────────────────────────── code generation ─────────────────────────────

def _pn(el: Element) -> str:
    return f", part_number={el.part_number!r}" if el.part_number else ""


def _definition(el: Element, g: _Geo) -> tuple[str | None, float]:
    """Return (definition expression or None if unsupported, rotation_deg)."""
    d_in = g.d_in.get(el.id, el.angle_deg if el.angle_deg is not None else 0.0)
    side = g.d_side.get(el.id)
    t = el.type
    if t in _REFLECTORS:
        if side is not None:
            rot = _bisector(d_in, side)
        elif el.angle_deg is not None:
            rot = el.angle_deg
        else:
            rot = d_in + 180.0
        if t == "mirror":
            expr = f"optics.Circular_Mirror(mount_definition=thorlabs.Mirror_Mount_K05S1(){_pn(el)})"
        elif t == "sampler":
            r = el.split_ratio if el.split_ratio is not None else 0.05
            expr = (f"optics.Circular_Sampler(ref_ratio={_fmt(r)}, "
                    f"mount_definition=thorlabs.Beamsplitter_Mount_B05G(){_pn(el)})")
        else:
            c = el.cutoff_nm if el.cutoff_nm is not None else 600.0
            rng = f"[(None, {_fmt(c)})]" if (el.reflect or "below") == "below" else f"[({_fmt(c)}, None)]"
            expr = (f"optics.Circular_Dichroic_Mirror(ref_wavelengths={rng}, "
                    f"mount_definition=thorlabs.Mirror_Mount_K05S1(){_pn(el)})")
        return expr, rot
    if t == "lens":
        f = el.focal_length_mm if el.focal_length_mm is not None else 100.0
        return (f"optics.Spherical_Lens(focal_length=dim({_fmt(f)}, \"mm\"), "
                f"mount_definition=thorlabs.Lens_Mount_L05G(){_pn(el)})"), d_in
    if t in ("half_wave_plate", "quarter_wave_plate"):
        ret = 0.5 if t == "half_wave_plate" else 0.25
        fa = el.fast_axis_deg or 0.0
        return (f"optics.Circular_Waveplate(retardance={ret}, fast_axis_angle={_fmt(fa)}, "
                f"mount_definition=thorlabs.Rotation_Mount_RSP05(){_pn(el)})"), d_in
    if t in _CUBES:
        rotate_cube = side is not None and _cross(d_in, side) < 0
        if t == "pbs":
            kind = "ref_polarization=90"  # PBS reflects V (s) light
        else:
            kind = f"ref_ratio={_fmt(el.split_ratio if el.split_ratio is not None else 0.5)}"
        return (f"optics.Beamsplitter_Cube_on_Surface_Adapter({kind}, "
                f"rotate_cube={rotate_cube}{_pn(el)})"), d_in
    if t == "aom":
        rot = d_in
        if side is not None and _cross(d_in, side) < 0:
            rot = d_in + 180.0  # PyOpticL's +1 order deflects toward local +y
        return "isomet.AOM_1205C_on_KM100PM()", rot
    if t == "fiber_coupler":
        return "thorlabs.Fiberport_PAF2A4A()", d_in + 180.0
    if t == "photodiode":
        return "thorlabs.Photodetector_PDA10A2()", d_in + 180.0
    if t == "iris":
        return "thorlabs.Iris_IDA12()", d_in + 180.0
    return None, d_in


def _polarization(p) -> str:
    if isinstance(p, (int, float)):
        return f"linear_polarization({_fmt(float(p))})"
    return {
        "H": "linear_polarization(0)",
        "V": "linear_polarization(90)",
        "D": "linear_polarization(45)",
        "A": "linear_polarization(-45)",
        "R": 'circular_polarization("right")',
        "L": 'circular_polarization("left")',
    }.get(p, "linear_polarization(0)")


def to_pyopticl(design: Design, trace_result: TraceResult | None = None) -> str:
    """Render `design` as PyOpticL Python source (run inside FreeCAD with PyOpticL installed)."""
    g = _geometry(design, trace_result)
    bp = design.baseplate
    src_ids = [s.id for s in design.sources]
    fn = _ident(design.name.lower()) or "design"
    L: list[str] = []
    w = L.append

    w(f"# PyOpticL layout generated by Beamline from design {design.name!r}.")
    w("# Built on PyOpticL (https://github.com/UMassIonTrappers/PyOpticL) by the UMass Ion")
    w("# Trappers group — code-to-CAD optical baseplates for FreeCAD. Style follows")
    w("# PyOpticL/Designs/modules/doublepass.py. Run inside FreeCAD with PyOpticL installed.")
    w("# Note: PyOpticL's AOM model (Isomet 1205C) uses its own RF/sound-velocity values, so")
    w("# diffraction angles may differ slightly from the Beamline trace.")
    if design.description:
        for line in design.description.splitlines():
            w(f"#   {line}")
    w("")
    w("from PyOpticL.beam_path import BeamPath, circular_polarization, linear_polarization")
    w("from PyOpticL.layout import Component")
    w("from PyOpticL.library import Baseplate, isomet, optics, thorlabs")
    w("from PyOpticL.utils import Dimension as dim")
    w("")
    w(f'base_dx = dim({_fmt(bp.width_mm)}, "mm")')
    w(f'base_dy = dim({_fmt(bp.height_mm)}, "mm")')
    w(f'base_dz = dim({_fmt(bp.thickness_mm)}, "mm")')
    w("")
    w("")
    w(f"def {fn}():")
    w("    baseplate = Component(")
    w(f"        label={design.name!r},")
    w("        definition=Baseplate(")
    w("            dimensions=(base_dx, base_dy, base_dz),")
    w(f'            optical_height=dim({_fmt(bp.optical_height_mm)}, "mm"),')
    w('            grid_offset=(dim(0, "mm"), dim(0, "mm")),')
    w("        ),")
    w("    )")
    w("")

    beam_var: dict[str, str] = {}
    for s in design.sources:
        v = f"beam_{_ident(s.id)}"
        beam_var[s.id] = v
        lbl = s.label or s.id
        w(f"    # source {s.id}: {lbl}" + (f" ({s.part_number})" if s.part_number else ""))
        if "fiber" in (lbl + (s.part_number or "")).lower() or "PAF" in (s.part_number or ""):
            w("    baseplate.add(")
            w(f"        Component(label={(lbl + ' collimator')!r}, definition=thorlabs.Fiberport_PAF2A4A()),")
            w(f"        position=({_fmt(s.position[0])}, {_fmt(s.position[1])}, 0),")
            w(f"        rotation={_fmt(_norm(s.direction_deg))},")
            w("    )")
        w(f"    {v} = baseplate.add(")
        w("        BeamPath(")
        w(f"            label={lbl!r},")
        w(f"            wavelength={_fmt(s.wavelength_nm)},")
        w(f"            polarization={_polarization(s.polarization)},")
        w(f"            power={_fmt(s.power_mw / 1000.0)},  # W")
        w(f'            waist=dim({_fmt(s.waist_mm)}, "mm"),')
        w(f'            waist_position=dim({_fmt(s.waist_offset_mm)}, "mm"),')
        w("        ),")
        w(f"        position=({_fmt(s.position[0])}, {_fmt(s.position[1])}, 0),")
        w(f"        rotation={_fmt(_norm(s.direction_deg))},")
        w("    )")
        w("")

    for el in design.elements:
        expr, rot = _definition(el, g)
        lbl = el.label or el.id
        tag = f"{el.id} ({el.type}{', ' + el.part_number if el.part_number else ''})"
        if expr is None:
            where = (f"on {el.beam} at {_fmt(el.distance_mm)} mm" if el.at is None
                     else f"at ({_fmt(el.at[0])}, {_fmt(el.at[1])})")
            pos = g.pos.get(el.id)
            pos_s = f", table position ({_fmt(pos[0])}, {_fmt(pos[1])})" if pos else ""
            w(f"    # TODO: {tag} {lbl!r} has no PyOpticL library part; place manually {where}{pos_s},")
            w(f"    #       axis {_fmt(_norm(rot))} deg.")
            w("")
            continue
        comp = f"Component(label={lbl!r}, definition={expr})"
        w(f"    # {tag}")
        if el.at is not None:
            w("    baseplate.add(")
            w(f"        {comp},")
            w(f"        position=({_fmt(el.at[0])}, {_fmt(el.at[1])}, 0),")
            w(f"        rotation={_fmt(_norm(rot))},")
            w("    )")
        else:
            src, idx = branch_to_index(el.beam, src_ids)
            v = beam_var.get(src)
            if v is None:
                w(f"    # TODO: branch {el.beam!r} does not start at a known source; skipped.")
                w("")
                continue
            w(f"    {v}.add(")
            w(f"        {comp},")
            w(f"        beam_index={bin(idx)},  # branch {el.beam}")
            w(f'        distance=dim({_fmt(el.distance_mm)}, "mm"),')
            w(f"        rotation={_fmt(_norm(rot))},")
            w("    )")
        w("")

    w("    return baseplate")
    w("")
    w("")
    w('if __name__ == "__main__":')
    w(f"    {fn}().recompute()")
    w("")
    return "\n".join(L)
