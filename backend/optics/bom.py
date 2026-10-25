"""Build kit: bill of materials + printable "paint by numbers" baseplate (PyOpticL-style).

    build_bom(design, trace=None) -> dict          purchased / hardware / printed / totals
    build_kit(design, out_dir=None) -> (bom, dir)  also writes stl/*.stl, BOM.csv, bom.json, README.md,
                                                   pyopticl_design.py into a cache dir keyed by design hash
    kit_zip(design) -> bytes                       the whole kit as a zip

Purchased parts: an element's own ``part_number`` wins; otherwise a realistic default kit is
chosen per type (CATALOG / _default_parts).  Prices are list-price ESTIMATES (USD, 2024-ish) for
planning only.  Mounting: if the baseplate's optical height is >= 20 mm every mount gets a Ø1/2"
post stack (TR075 + PH075 + BA1S); below that (PyOpticL default 1/2") mounts bolt straight onto
the printed plate with one 8-32 screw from underneath and are keyed by two Ø2 mm dowel pins.

Printed plate (manifold3d booleans, trimesh STL export), plate frame = table frame (mm):
  * box width x height x thickness (design.baseplate)
  * table holes: 1/4-20 clearance Ø6.6 through, Ø11 counterbore from the top leaving a 6 mm floor,
    on a 2-grid (50.8 mm) pitch inset half a grid from the edges, skipped within 14 mm of a part
  * per placed element: Ø4.5 through hole (8-32 / M4) with Ø8.5 x 5 mm counterbore from the bottom,
    plus two Ø2.1 x 6 mm dowel-pin holes from the top at ±8 mm perpendicular to the element's
    optical axis (mirrors: along the mirror surface) -> mounts are keyed and pre-aligned
  * a 1 mm wide, 0.5 mm deep groove along every beam segment (the beam is visible on the print)
  * plates larger than 250 mm in x or y are tiled; neighbouring tiles meet in a 20 mm half-lap
    joint (left/lower tile keeps the bottom half of the lap) joined by M3 bolts every ~50 mm
Print estimate: extruded volume = shell (surface area x 3 walls x 0.4 mm) + 20 % of the interior;
time = extruded / 12 cm^3/h; filament = extruded x 1.24 g/cm^3 (PLA).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import tempfile
import zipfile
from pathlib import Path

from .ir import Design, TraceResult

# ───────────────────────────── catalog (ESTIMATES) ──────────────────────────

THORLABS = "https://www.thorlabs.com/thorproduct.cfm?partnumber={}"

# part_number -> (description, vendor, estimated unit price USD)
CATALOG: dict[str, tuple[str, str, float]] = {
    "BB1-E03": ("Ø1\" broadband dielectric mirror, 750-1100 nm", "Thorlabs", 80.0),
    "BB1-E02": ("Ø1\" broadband dielectric mirror, 400-750 nm", "Thorlabs", 80.0),
    "BB1-E04": ("Ø1\" broadband dielectric mirror, 1280-1600 nm", "Thorlabs", 80.0),
    "PF10-03-P01": ("Ø1\" protected silver mirror", "Thorlabs", 60.0),
    "KM100": ("kinematic mirror mount, Ø1\"", "Thorlabs", 48.0),
    "LMR1": ("lens mount, Ø1\" optics", "Thorlabs", 18.0),
    "LMR05": ("lens mount, Ø1/2\" optics", "Thorlabs", 17.0),
    "RSP05": ("rotation mount, Ø1/2\" optics", "Thorlabs", 95.0),
    "RSP1": ("rotation mount, Ø1\" optics", "Thorlabs", 105.0),
    "PBS052": ("10 mm polarizing beamsplitter cube, 620-1000 nm", "Thorlabs", 260.0),
    "PBS102": ("10 mm polarizing beamsplitter cube, 620-1000 nm", "Thorlabs", 260.0),
    "PBS104": ("10 mm polarizing beamsplitter cube, 1200-1600 nm", "Thorlabs", 260.0),
    "BS010": ("10 mm 50:50 non-polarizing beamsplitter cube, 400-700 nm", "Thorlabs", 215.0),
    "BS011": ("10 mm 50:50 non-polarizing beamsplitter cube, 700-1100 nm", "Thorlabs", 215.0),
    "BSF10-B": ("Ø1\" UVFS beam sampler (pickoff), 650-1050 nm", "Thorlabs", 70.0),
    "DMLP805": ("Ø1\" longpass dichroic, 805 nm cutoff", "Thorlabs", 190.0),
    "DMLP1180": ("Ø1\" longpass dichroic, 1180 nm cutoff", "Thorlabs", 190.0),
    "DMSP1500": ("Ø1\" shortpass dichroic, 1500 nm cutoff", "Thorlabs", 190.0),
    "KM100CP": ("kinematic mount for 10 mm cubes", "Thorlabs", 70.0),
    "1205C-2": ("acousto-optic modulator, 80 MHz, 400-850 nm", "Isomet", 1500.0),
    "532C-2": ("AOM RF driver, 80 MHz", "Isomet", 1400.0),
    "PAF2-A4A": ("FiberPort collimator/coupler, f = 4.6 mm, FC/APC", "Thorlabs", 420.0),
    "P1-780A-FC-2": ("single-mode patch cable 780 nm, FC/APC, 2 m", "Thorlabs", 110.0),
    "PDA36A2": ("Si amplified switchable-gain photodetector", "Thorlabs", 360.0),
    "PDA20CS2": ("InGaAs amplified photodetector, 800-1700 nm", "Thorlabs", 480.0),
    "LB1": ("beam block / dump, black anodized", "Thorlabs", 95.0),
    "ID12": ("Ø12 mm mounted iris diaphragm", "Thorlabs", 75.0),
    "GC19075-RB": ("Rb reference vapor cell, Ø19 x 75 mm", "Thorlabs", 750.0),
    "IO-3D-780-VLP": ("free-space optical isolator, 780 nm", "Thorlabs", 1300.0),
    "BOA1004P": ("semiconductor optical amplifier (booster), 1550 nm, fiber-pigtailed [specialist]",
                 "Thorlabs", 3200.0),
    "MSFG1-0.5": ("PPLN crystal for SFG/SHG + oven [specialist; QPM period per process]", "Covesion", 1900.0),
    "SAM-1550-1": ("semiconductor saturable absorber mirror, 1550 nm [specialist]", "BATOP", 900.0),
    "TR075": ("Ø1/2\" post, 3/4\" long", "Thorlabs", 6.0),
    "PH075": ("Ø1/2\" post holder, 3/4\"", "Thorlabs", 10.0),
    "BA1S": ("mounting base 1\" x 2.3\"", "Thorlabs", 8.0),
    "SH25S050": ("1/4-20 x 1/2\" cap screw (25 pack -> per piece)", "Thorlabs", 0.4),
    "SH8S100": ("8-32 x 1\" cap screw (per piece)", "Thorlabs", 0.3),
    "DOWEL-2x8": ("Ø2 x 8 mm steel dowel pin (per piece)", "McMaster-Carr", 0.15),
    "M3x25+NUT": ("M3 x 25 mm cap screw + nut (tile lap joints)", "McMaster-Carr", 0.2),
}

# Estimated prices by part-number prefix, for real part numbers not in CATALOG (longest prefix wins)
PREFIX_PRICES: dict[str, tuple[str, float]] = {
    "AC127": ("Thorlabs", 90.0), "AC254": ("Thorlabs", 110.0), "LA1": ("Thorlabs", 35.0),
    "LB1": ("Thorlabs", 35.0), "BB05": ("Thorlabs", 65.0), "BB1": ("Thorlabs", 80.0),
    "PF05": ("Thorlabs", 45.0), "PF10": ("Thorlabs", 60.0), "BSF05": ("Thorlabs", 55.0),
    "BSF10": ("Thorlabs", 70.0), "WPH05M": ("Thorlabs", 310.0), "WPQ05M": ("Thorlabs", 290.0),
    "WPH10M": ("Thorlabs", 420.0), "WPQ10M": ("Thorlabs", 400.0), "PBS1": ("Thorlabs", 260.0),
    "PBS2": ("Thorlabs", 290.0), "PBS05": ("Thorlabs", 260.0), "BS0": ("Thorlabs", 215.0),
    "DMLP": ("Thorlabs", 190.0), "DMSP": ("Thorlabs", 190.0), "GC": ("Thorlabs", 750.0),
    "PAF2": ("Thorlabs", 420.0), "P1-": ("Thorlabs", 110.0), "P3-": ("Thorlabs", 130.0),
    "PDA": ("Thorlabs", 360.0), "ID": ("Thorlabs", 75.0), "IO-": ("Thorlabs", 1300.0),
    "KM": ("Thorlabs", 50.0), "Isomet": ("Isomet", 1500.0), "1205C": ("Isomet", 1500.0),
    "MT200": ("AA Opto-Electronic", 1500.0), "MT80": ("AA Opto-Electronic", 1300.0),
}
LASER_HINTS = ("laser", "toptica", "dl pro", "lp785", "dpss", "dfb", "sfl", "fpl", "hnl", "ecdl")


def _price(pn: str) -> tuple[str, float] | None:
    best = None
    for pre, v in PREFIX_PRICES.items():
        if pn.startswith(pre) and (best is None or len(pre) > len(best[0])):
            best = (pre, v)
    return best[1] if best else None


# Ø1" N-BK7 plano-convex lenses by focal length (mm); coating suffix chosen by wavelength
LENSES = {25.4: "LA1951", 30: "LA1805", 35: "LA1027", 40: "LA1422", 50: "LA1131", 60: "LA1134",
          75: "LA1608", 100: "LA1509", 125: "LA1986", 150: "LA1433", 175: "LA1229", 200: "LA1708",
          250: "LA1461", 300: "LA1484", 400: "LA1172", 500: "LA1908", 1000: "LA1464"}
FIBERPORTS = {4.5: "PAF2-A4A", 4.6: "PAF2-A4A", 6.2: "PAF2-5A", 8.0: "PAF2-7A", 11.0: "PAF2-11A",
              15.4: "PAF2-15A"}


def _coating(wl: float) -> str:
    return "-A" if wl < 650 else ("-B" if wl < 1050 else "-C")


def _wl_tag(wl: float) -> str:
    return str(int(round(wl)))


# ───────────────────────────── purchased parts ──────────────────────────────

def _default_parts(el, wl: float) -> list[tuple[str, str | None]]:
    """[(part_number, description override)] for an element without a part number (optic + mount)."""
    t = el.type
    if t == "mirror":
        pn = "BB1-E02" if wl < 700 else ("BB1-E03" if wl < 1100 else "BB1-E04")
        return [(pn, None), ("KM100", None)]
    if t == "lens":
        f = el.focal_length_mm or 100.0
        near = min(LENSES, key=lambda x: abs(x - f))
        return [(LENSES[near] + _coating(wl), f"Ø1\" plano-convex lens f = {near:g} mm (nearest stock to {f:g})"),
                ("LMR1", None)]
    if t in ("half_wave_plate", "quarter_wave_plate"):
        kind = "WPH05M" if t == "half_wave_plate" else "WPQ05M"
        name = "half" if t == "half_wave_plate" else "quarter"
        return [(f"{kind}-{_wl_tag(wl)}", f"Ø1/2\" zero-order {name}-wave plate, {wl:.0f} nm"), ("RSP05", None)]
    if t == "pbs":
        return [("PBS052" if wl < 1100 else "PBS104", None), ("KM100CP", None)]
    if t == "beamsplitter":
        return [("BS011" if wl >= 700 else "BS010", None), ("KM100CP", None)]
    if t == "sampler":
        return [("BSF10-B", None), ("KM100", None)]
    if t == "dichroic":
        return [(f"DMLP{int(el.cutoff_nm or 650)}", f"Ø1\" dichroic, {el.cutoff_nm or 650:.0f} nm cutoff"),
                ("KM100", None)]
    if t == "aom":
        return [("1205C-2", None), ("532C-2", None)]
    if t == "fiber_coupler":
        pn = FIBERPORTS.get(min(FIBERPORTS, key=lambda x: abs(x - (el.focal_length_mm or 11.0))), "PAF2-11A")
        return [(pn, None), (f"P1-{_wl_tag(wl)}A-FC-2", f"single-mode patch cable {wl:.0f} nm, FC/APC, 2 m")]
    if t == "photodiode":
        return [("PDA36A2" if wl < 1000 else "PDA20CS2", None)]
    if t == "beam_dump":
        return [("LB1", None)]
    if t == "iris":
        return [("ID12", None)]
    if t == "vapor_cell":
        return [("GC19075-RB", None)]
    if t == "isolator":
        return [(f"IO-3D-{_wl_tag(wl)}-VLP", f"free-space optical isolator, {wl:.0f} nm")]
    if t == "soa":
        return [("BOA1004P", None)]
    if t == "sfg_crystal":
        return [("MSFG1-0.5", None)]
    if t == "saturable_absorber":
        return [("SAM-1550-1", None)]
    return []


_DESC = {"mirror": "mirror", "lens": "lens", "half_wave_plate": "half-wave plate",
         "quarter_wave_plate": "quarter-wave plate", "pbs": "polarizing beamsplitter",
         "beamsplitter": "beamsplitter", "sampler": "beam sampler", "dichroic": "dichroic mirror",
         "aom": "acousto-optic modulator", "fiber_coupler": "fiber coupler", "photodiode": "photodiode",
         "beam_dump": "beam dump", "iris": "iris", "vapor_cell": "vapor cell", "isolator": "optical isolator",
         "soa": "semiconductor optical amplifier [specialist]", "sfg_crystal": "nonlinear crystal [specialist]",
         "saturable_absorber": "saturable absorber [specialist]"}
_NEEDS_MOUNT = {"mirror": "KM100", "lens": "LMR1", "half_wave_plate": "RSP05", "quarter_wave_plate": "RSP05",
                "pbs": "KM100CP", "beamsplitter": "KM100CP", "sampler": "KM100", "dichroic": "KM100"}


def _row_for(pn: str, desc: str | None, laser: bool = False) -> dict:
    cat = CATALOG.get(pn)
    pre = None if cat or laser else _price(pn)
    vendor = cat[1] if cat else (pre[0] if pre else "")
    price = cat[2] if cat else (pre[1] if pre else None)
    return {"part_number": pn, "description": desc or (cat[0] if cat else pn), "vendor": vendor,
            "qty": 0, "unit_price_usd": price,
            "url": THORLABS.format(pn) if vendor == "Thorlabs" else None, "element_ids": [],
            "price_note": ("light source: quote separately, not in total" if laser else
                           "estimate" if price is not None else "price unknown")}


def _element_wavelengths(design: Design, trace: TraceResult | None) -> dict[str, float]:
    wl: dict[str, float] = {}
    if trace is not None:
        seg_wl = {s.id: s.wavelength_nm for s in trace.segments}
        for e in trace.elements:
            if e.hits:
                wl[e.id] = seg_wl.get(e.hits[0].segment_id, 0.0)
    return wl


def short_tag(label: str | None, fallback: str, n: int = 32) -> str:
    """A short role tag from an element label: the part before any bracket/colon, cut to <= n
    chars at a word boundary.  Never the element's notes/description."""
    s = (label or "").split(" (")[0].split("(")[0].split(":")[0].split(";")[0].strip(" -,.")
    if not s:
        return fallback
    if len(s) > n:
        cut = s[: n + 1].rsplit(" ", 1)[0].rstrip(" -,.")
        s = (cut if cut else s[:n]) + "…"
    return s


def _type_desc(el) -> str:
    """Generic description for an element whose part number is not in the catalog."""
    t = el.type
    if t == "dichroic":
        kind = "longpass" if (el.reflect or "below") == "below" else "shortpass"
        return f"dichroic mirror, {kind} {el.cutoff_nm or 650:g} nm"
    if t == "lens":
        return f"lens, f = {el.focal_length_mm or 100:g} mm"
    if t == "sampler":
        return f"beam sampler, {100 * (el.split_ratio or 0.05):g} % pickoff"
    if t == "beamsplitter":
        r = el.split_ratio if el.split_ratio is not None else 0.5
        return f"beamsplitter, {100 * (1 - r):g}:{100 * r:g} (T:R)"
    if t == "aom":
        return f"acousto-optic modulator, {el.aom_frequency_mhz or 80:g} MHz"
    return _DESC.get(t, t)


def _finish_descriptions(rows: list[dict], tags: dict[str, str]) -> None:
    """description = catalog/type text + role: '— TAG' for one element, '× n: id1, id2' for several."""
    for r in rows:
        ids = r["element_ids"]
        if len(ids) == 1:
            r["description"] = f"{r['description']} — {tags.get(ids[0], ids[0])}"
        elif ids:
            shown = ", ".join(ids[:8]) + (f", … +{len(ids) - 8}" if len(ids) > 8 else "")
            r["description"] = f"{r['description']} × {len(ids)}: {shown}"


def _purchased(design: Design, trace: TraceResult | None) -> list[dict]:
    rows: dict[str, dict] = {}
    default_wl = design.sources[0].wavelength_nm if design.sources else 780.0
    wls = _element_wavelengths(design, trace)
    posts = design.baseplate.optical_height_mm >= 20.0

    def add(pn: str, desc: str | None, eid: str, qty: int = 1, laser: bool = False):
        r = rows.setdefault(pn, _row_for(pn, desc, laser))
        r["qty"] += qty
        if eid not in r["element_ids"]:
            r["element_ids"].append(eid)

    tags: dict[str, str] = {}
    for s in design.sources:
        pn = s.part_number or f"LASER-{_wl_tag(s.wavelength_nm)}"
        tags[s.id] = short_tag(s.label, s.id)
        add(pn, f"laser, {s.wavelength_nm:g} nm, {s.power_mw:g} mW", s.id, laser=True)
    for el in design.elements:
        wl = wls.get(el.id) or default_wl
        tags[el.id] = short_tag(el.label, el.id)
        if el.part_number:
            add(el.part_number, CATALOG[el.part_number][0] if el.part_number in CATALOG else _type_desc(el), el.id)
            if el.type in _NEEDS_MOUNT and el.part_number not in _NEEDS_MOUNT.values():
                add(_NEEDS_MOUNT[el.type], None, el.id)
        else:
            for pn, desc in _default_parts(el, wl):
                add(pn, desc, el.id)
        if posts and el.type not in ("aom", "soa"):
            for pn in ("TR075", "PH075", "BA1S"):
                add(pn, None, el.id)
    out = sorted(rows.values(), key=lambda r: (r["vendor"] != "Thorlabs", r["part_number"]))
    _finish_descriptions(out, tags)
    return out


# ───────────────────────────── plate geometry ───────────────────────────────

TILE_MAX = 250.0
LAP = 20.0
PIN_OFFSET = 8.0


def _plate_features(design: Design, trace: TraceResult | None):
    """Positions of table holes, element sites (x, y, axis_deg), and beam segments on the plate."""
    bp = design.baseplate
    W, H, g = bp.width_mm, bp.height_mm, bp.grid_mm
    sites = []
    if trace is not None:
        for e in trace.elements:
            if e.placed and e.position and 0 <= e.position[0] <= W and 0 <= e.position[1] <= H:
                sites.append((e.id, e.position[0], e.position[1], e.angle_deg or 0.0))
    table = []
    pitch = 2 * g
    x = g / 2
    while x <= W - g / 2 + 1e-6:
        y = g / 2
        while y <= H - g / 2 + 1e-6:
            if all(math.hypot(x - sx, y - sy) > 14.0 for _, sx, sy, _ in sites):
                table.append((x, y))
            y += pitch
        x += pitch
    segs = []
    if trace is not None:
        for s in trace.segments:
            if s.length_mm > 0.5:
                segs.append((s.start, s.end))
    return table, sites, segs


def _circle(x, y, d, n=24):
    import manifold3d as m3
    return m3.CrossSection.circle(d / 2, n).translate([x, y])


def _pin_positions(sites, table, bolts) -> list[tuple[float, float]]:
    """Two dowel pins per site at ±8 mm perpendicular to the optical axis; a pin that would come
    within 0.5 mm of another hole (bolt, table counterbore) is dropped (that mount would collide
    there anyway, and touching holes make a non-manifold pinch)."""
    holes = [(x, y, 11.0 / 2) for x, y in table] + [(x, y, 4.5 / 2) for _, x, y, _ in sites] \
        + [(x, y, 3.4 / 2) for x, y in bolts]
    out = []
    for _, x, y, ang in sites:
        px, py = -math.sin(math.radians(ang)), math.cos(math.radians(ang))
        for k in (-1, 1):
            qx, qy = x + k * PIN_OFFSET * px, y + k * PIN_OFFSET * py
            if all(math.hypot(qx - hx, qy - hy) > r + 1.05 + 0.5 for hx, hy, r in holes):
                out.append((qx, qy))
    return out


def _layers(design: Design, table, sites, segs, bolts):
    """2.5D plate: [(z0, z1, CrossSection)] -- each z-band's 2D section with its holes cut.
    Built from robust 2D booleans (Clipper2); slivers from nearly coincident features are removed
    by CrossSection.simplify, so the final mesh is always a clean closed manifold."""
    import manifold3d as m3
    bp = design.baseplate
    W, H, T = bp.width_mm, bp.height_mm, bp.thickness_mm
    floor = min(6.0, T / 2)          # table-bolt counterbore floor (from the bottom)
    cb = min(5.0, T / 3)             # element-bolt counterbore depth (from the bottom)
    pin_z = max(T - 6.0, T / 2)      # dowel-pin holes start (6 mm deep from the top)
    groove_z = T - 0.5
    zs = sorted({0.0, cb, floor, T / 2, pin_z, groove_z, T})
    pin_xy = _pin_positions(sites, table, bolts)
    pins = [_circle(x, y, 2.1, 12) for x, y in pin_xy]
    grooves = []
    for (x0, y0), (x1, y1) in segs:
        L = math.hypot(x1 - x0, y1 - y0)
        ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
        grooves.append(m3.CrossSection.square([L, 1.0]).translate([0, -0.5]).rotate(ang).translate([x0, y0]))
    if grooves:
        # Keep a 0.5 mm wall between grooves and every hole: a groove edge ending exactly on a
        # hole boundary creates a pinch vertex (valid manifold, but not representable in STL).
        keep_out = ([_circle(x, y, 12.0) for x, y in table] + [_circle(x, y, 9.5) for _, x, y, _ in sites]
                    + [_circle(x, y, 4.4, 16) for x, y in bolts])
        keep_out += [_circle(x, y, 3.1, 12) for x, y in pin_xy]
        grooves = [(m3.CrossSection.batch_boolean(grooves, m3.OpType.Add)
                    - m3.CrossSection.batch_boolean(keep_out, m3.OpType.Add)).simplify(1e-3)]
    base = m3.CrossSection.square([W, H])
    out = []
    for z0, z1 in zip(zs, zs[1:]):
        zm = (z0 + z1) / 2
        cut = [_circle(x, y, 11.0 if zm > floor else 6.6) for x, y in table]
        cut += [_circle(x, y, 8.5 if zm < cb else 4.5) for _, x, y, _ in sites]
        cut += [_circle(x, y, 3.4, 16) for x, y in bolts]
        if zm > pin_z:
            cut += pins
        if zm > groove_z:
            cut += grooves
        sec = base - m3.CrossSection.batch_boolean(cut, m3.OpType.Add) if cut else base
        out.append((z0, z1, sec.simplify(1e-3)))
    return out


def _extrude(layers, rect=None):
    """Stack the layer sections (optionally clipped to a per-layer rectangle) into one manifold."""
    import manifold3d as m3
    parts = []
    for z0, z1, sec in layers:
        if rect is not None:
            x0, y0, x1, y1 = rect((z0 + z1) / 2)
            sec = sec ^ m3.CrossSection.square([x1 - x0, y1 - y0]).translate([x0, y0])
        if not sec.is_empty():
            parts.append(m3.Manifold.extrude(sec.simplify(1e-3), z1 - z0).translate([0, 0, z0]))
    return m3.Manifold.batch_boolean(parts, m3.OpType.Add) if parts else m3.Manifold()


def _seams(length: float, n: int, centers: list[float]) -> list[float]:
    """n+1 cut coordinates; inner seams moved (<= 30 mm) to keep the seam and the lap edge away
    from hole centres, plus an irrational nudge so cut planes never coincide with feature faces."""
    cuts = [0.0]
    for i in range(1, n):
        nominal = length * i / n
        best, best_d = nominal, -1.0
        for k in range(121):
            off = (k // 2) * 0.5 * (1 if k % 2 else -1)
            c = nominal + off
            d = min((min(abs(c - x), abs(c + LAP - x)) for x in centers), default=1e9)
            if d > best_d + 1e-9:
                best, best_d = c, d
            if d >= 10.0:
                break
        cuts.append(best + 0.0137)
    cuts.append(length)
    return cuts


def _plate_parts(design: Design, table, sites, segs):
    """[(name, manifold)], n_joint_bolts.  Plates over TILE_MAX are tiled with 20 mm half-lap
    joints: at each seam the left/lower tile keeps the bottom half of the lap, the right/upper
    tile the top half; M3 bolts pass through the middle of the lap every ~50 mm."""
    bp = design.baseplate
    W, H, T = bp.width_mm, bp.height_mm, bp.thickness_mm
    if W <= TILE_MAX and H <= TILE_MAX:
        return [("baseplate", _extrude(_layers(design, table, sites, segs, [])))], 0, \
            len(_pin_positions(sites, table, []))
    holes = list(table) + [(x, y) for _, x, y, _ in sites]
    # 30 mm reserve for seam shifting keeps every tile (incl. its lap) within TILE_MAX
    nx = max(1, math.ceil((W - LAP) / (TILE_MAX - LAP - 30)))
    ny = max(1, math.ceil((H - LAP) / (TILE_MAX - LAP - 30)))
    xs = _seams(W, nx, [h[0] for h in holes])
    ys = _seams(H, ny, [h[1] for h in holes])
    bolts = []
    for x in xs[1:-1]:
        n = max(2, int(H // 50))
        bolts += [(x + LAP / 2, H * (k + 0.5) / n) for k in range(n)]
    for y in ys[1:-1]:
        n = max(2, int(W // 50))
        bolts += [(W * (k + 0.5) / n, y + LAP / 2) for k in range(n)]
    layers = _layers(design, table, sites, segs, bolts)

    def span(cuts, i, bottom):
        lo, hi = cuts[i], cuts[i + 1]
        last = i == len(cuts) - 2
        if bottom:
            return (lo + LAP if i > 0 else -1.0), (hi + LAP if not last else hi + 1.0)
        return (lo if i > 0 else -1.0), (hi if not last else hi + 1.0)

    out = []
    for i in range(nx):
        for j in range(ny):
            def rect(zm, i=i, j=j):
                b = zm < T / 2
                x0, x1 = span(xs, i, b)
                y0, y1 = span(ys, j, b)
                return x0, y0, x1, y1
            piece = _extrude(layers, rect)
            if not piece.is_empty():
                out.append((f"baseplate_r{j + 1}c{i + 1}", piece))
    return out, len(bolts), len(_pin_positions(sites, table, bolts))


def plate_genus(design: Design, trace: TraceResult | None = None) -> tuple[int, int]:
    """(genus of the untiled plate, expected through holes = table holes + element sites)."""
    if trace is None:
        from .trace import trace as run_trace
        trace = run_trace(design)
    table, sites, segs = _plate_features(design, trace)
    return _extrude(_layers(design, table, sites, segs, [])).genus(), len(table) + len(sites)


def _print_estimate(man) -> dict:
    vol = man.volume() / 1000.0                      # cm^3
    shell = man.surface_area() * 3 * 0.4 / 1000.0    # 3 walls x 0.4 mm
    shell = min(shell, vol)
    extruded = shell + 0.2 * (vol - shell)
    return {"volume_cm3": round(vol, 1), "est_print_h": round(extruded / 12.0, 1),
            "est_filament_g": round(extruded * 1.24, 0)}


def _to_stl(man, path: Path) -> None:
    import trimesh
    mesh = man.to_mesh()
    # process=True merges coincident vertices so trimesh sees the closed 2-manifold manifold3d produced
    tm = trimesh.Trimesh(vertices=mesh.vert_properties[:, :3], faces=mesh.tri_verts, process=True)
    tm.export(path)


# ───────────────────────────── public API ───────────────────────────────────

def design_hash(design: Design) -> str:
    return hashlib.sha256(design.model_dump_json().encode()).hexdigest()[:16]


def _build(design: Design, trace: TraceResult | None, stl_dir: Path | None) -> dict:
    if trace is None:
        from .trace import trace as run_trace
        trace = run_trace(design)
    purchased = _purchased(design, trace)
    table, sites, segs = _plate_features(design, trace)
    tiles, n_joint, n_pins = _plate_parts(design, table, sites, segs)
    printed = []
    for name, man in tiles:
        est = _print_estimate(man)
        fname = f"{name}.stl"
        if stl_dir is not None:
            _to_stl(man, stl_dir / fname)
        printed.append({"name": name, "file": f"stl/{fname}", **est,
                        "notes": (f"PLA, 20 % infill, 3 walls, print flat (top up). "
                                  f"{len(sites)} keyed element sites, {len(table)} table holes"
                                  + (f"; half-lap tile, {n_joint} M3 joint bolts in total" if len(tiles) > 1 else ""))})
    n_sites = len(sites)
    hw_rows = [("SH25S050", len(table)), ("SH8S100", n_sites), ("DOWEL-2x8", n_pins)]
    if n_joint:
        hw_rows.append(("M3x25+NUT", n_joint))
    hardware = []
    for pn, q in hw_rows:
        if q:
            r = _row_for(pn, None)
            r["qty"] = q
            hardware.append(r)

    def cost(rows):
        return sum((r["unit_price_usd"] or 0.0) * r["qty"] for r in rows)

    unknown = [r["part_number"] for r in purchased
               if r["unit_price_usd"] is None and not r["price_note"].startswith("light source")]
    return {
        "design": design.name,
        "purchased": purchased,
        "hardware": hardware,
        "printed": printed,
        "plate": {"width_mm": design.baseplate.width_mm, "height_mm": design.baseplate.height_mm,
                  "thickness_mm": design.baseplate.thickness_mm, "table_holes": len(table),
                  "element_sites": n_sites, "pin_holes": n_pins, "tiles": len(printed),
                  "joint_bolts": n_joint, "element_ids": [s[0] for s in sites]},
        "totals": {
            "purchased_parts": sum(r["qty"] for r in purchased),
            "hardware_parts": sum(r["qty"] for r in hardware),
            "printed_parts": len(printed),
            "est_cost_usd": round(cost(purchased) + cost(hardware), 2),
            "est_print_h": round(sum(p["est_print_h"] for p in printed), 1),
            "est_filament_g": sum(p["est_filament_g"] for p in printed),
            "price_note": "list-price estimates, USD, excluding lasers; verify with vendors"
                          + (f"; no price for {', '.join(unknown)}" if unknown else ""),
        },
    }


def build_bom(design: Design, trace: TraceResult | None = None) -> dict:
    """BOM without writing files (printed volumes/times are still computed from the plate mesh)."""
    return _build(design, trace, None)


KIT_ROOT = Path(tempfile.gettempdir()) / "beamline_kits"


def build_kit(design: Design, out_dir: Path | None = None) -> tuple[dict, Path]:
    """Write the full kit into out_dir (default: a cache dir keyed by the design hash)."""
    out = Path(out_dir) if out_dir else KIT_ROOT / design_hash(design)
    if out_dir is None and (out / "bom.json").exists():
        return json.loads((out / "bom.json").read_text()), out
    (out / "stl").mkdir(parents=True, exist_ok=True)
    bom = _build(design, None, out / "stl")
    (out / "bom.json").write_text(json.dumps(bom, indent=2))
    (out / "BOM.csv").write_text(_csv(bom))
    (out / "README.md").write_text(_readme(design, bom))
    try:
        from .pyopticl_export import to_pyopticl
        (out / "pyopticl_design.py").write_text(to_pyopticl(design))
    except Exception as e:  # exporter problems must not block the kit
        (out / "pyopticl_design.py").write_text(f"# PyOpticL export failed: {e}\n")
    return bom, out


def kit_zip(design: Design) -> bytes:
    _, out = build_kit(design)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.rglob("*")):
            if p.is_file():
                z.write(p, f"{design.name}_kit/{p.relative_to(out)}")
    return buf.getvalue()


def _csv(bom: dict) -> str:
    f = io.StringIO()
    w = csv.writer(f)
    w.writerow(["section", "part_number", "description", "vendor", "qty", "unit_price_usd_estimate",
                "line_total_usd", "element_ids", "url"])
    for sec in ("purchased", "hardware"):
        for r in bom[sec]:
            p = r["unit_price_usd"]
            w.writerow([sec, r["part_number"], r["description"], r["vendor"], r["qty"],
                        "" if p is None else f"{p:.2f}", "" if p is None else f"{p * r['qty']:.2f}",
                        " ".join(r["element_ids"]), r["url"] or ""])
    for p in bom["printed"]:
        w.writerow(["printed", p["name"], f"{p['volume_cm3']} cm3, ~{p['est_print_h']} h, "
                    f"~{p['est_filament_g']:.0f} g PLA", "3D print", 1, "", "", "", p["file"]])
    t = bom["totals"]
    w.writerow(["total", "", t["price_note"], "", t["purchased_parts"] + t["hardware_parts"], "",
                f"{t['est_cost_usd']:.2f}", "", ""])
    return f.getvalue()


def _readme(design: Design, bom: dict) -> str:
    order = bom["plate"]["element_ids"]
    t = bom["totals"]
    lines = [
        f"# Build kit: {design.name}", "",
        design.description, "",
        f"Estimated parts cost: ${t['est_cost_usd']:,.0f} ({t['price_note']}).",
        f"Printing: {len(bom['printed'])} part(s), ~{t['est_print_h']} h, ~{t['est_filament_g']:.0f} g PLA.", "",
        "## Assembly", "",
        "1. Print every file in `stl/` flat, top side up (PLA, 20 % infill, 3 walls).",
        "2. Tiled plates: lay the tiles out by row/column name, overlap the half-lap joints and bolt "
        "them with the M3 screws and nuts." if bom["plate"]["tiles"] > 1 else
        "2. Clean the holes; a Ø4.5 drill and a Ø2 reamer by hand help.",
        "3. Press two Ø2 x 8 mm dowel pins into each pair of pin holes (they key every mount's orientation).",
        "4. Bolt the plate to the optical table with 1/4-20 (or M6) screws through the counterbored holes.",
        "5. Place mounts on their keyed sites in this order (beam order) and fix each with one 8-32 screw "
        "from underneath (or post + post holder + base if the optical height is >= 20 mm):", "",
    ]
    by_id = {e.id: e for e in design.elements}
    for i, eid in enumerate(order, 1):
        e = by_id.get(eid)
        if e:
            lines.append(f"   {i:2d}. {eid} — {e.type}{' (' + e.label + ')' if e.label else ''}")
    lines += ["",
              "6. Align: walk the beam in order with irises/cards; the BEAMTEAM tuner (`/api/tune`) gives "
              "suggested waveplate angles, lens positions and mirror tweaks for each element.",
              "7. Terminate every beam before turning up the power (the verifier flags stray beams).", "",
              "`pyopticl_design.py` regenerates the layout in PyOpticL / FreeCAD for CAD-quality mounts.", ""]
    return "\n".join(lines)
