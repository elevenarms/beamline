"""Build document (PDF) for a finished design, typeset with Typst.

    build_document(design, *, cover_png=None, tune_summary=None, citation=None, figure_png=None,
                   license=None) -> bytes   (PDF)

Sections: cover (image full-bleed or typographic), overview (description, plan-view SVG from the
trace, source figure, key specs), verification, bill of materials (optics.bom), assembly steps
(beam order, deterministic), alignment procedure (tune_summary), laser safety, credits.

All text reaches Typst through data.json (never spliced into markup), so arbitrary labels and
descriptions are safe.  Images are downscaled (cover <= 1600 px, figure <= 1000 px, JPEG) to keep
the PDF small; compile time is typically ~0.3 s.

tune_summary (optional) accepts the tune "final" summary plus the tune_done events the UI saw:
    {"objective_before": f, "objective_after": f, "steps": n,
     "changes": [{"element_id", "field", "from", "to", "gain"}, ...]}   ("done" is an alias)
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from .bom import short_tag
from .ir import Design, TraceResult

TYPST = shutil.which("typst") or "/opt/homebrew/bin/typst"


# ───────────────────────────── helpers ──────────────────────────────────────

def _downscale(data: bytes, max_px: int, quality: int = 85) -> bytes:
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im = im.convert("RGB")
    im.thumbnail((max_px, max_px))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()


def wavelength_color(nm: float) -> str:
    """Approximate visible colour for a wavelength; IR/UV get fixed muted tones."""
    if nm > 780:
        return "#8c2d5a"   # infrared
    if nm < 380:
        return "#5b3d99"   # ultraviolet
    if nm < 440:
        r, g, b = -(nm - 440) / 60, 0.0, 1.0
    elif nm < 490:
        r, g, b = 0.0, (nm - 440) / 50, 1.0
    elif nm < 510:
        r, g, b = 0.0, 1.0, -(nm - 510) / 20
    elif nm < 580:
        r, g, b = (nm - 510) / 70, 1.0, 0.0
    elif nm < 645:
        r, g, b = 1.0, -(nm - 645) / 65, 0.0
    else:
        r, g, b = 1.0, 0.0, 0.0
    k = 0.85   # slightly darker so lines read on white paper
    return "#%02x%02x%02x" % tuple(int(255 * k * c) for c in (r, g, b))


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def plan_svg(design: Design, trace: TraceResult, holes: list[tuple[float, float]] | None = None) -> str:
    """Top view: table outline, hole grid, beams (colour = wavelength, width ~ log power),
    element symbols + labels, sources, scale bar.  1 SVG unit = 1 mm, y flipped."""
    bp = design.baseplate
    W, H = bp.width_mm, bp.height_mm
    pad = 30.0
    vw, vh = W + 2 * pad, H + 2 * pad + 20

    def X(x):
        return x + pad

    def Y(y):
        return H - y + pad

    fs = max(5.0, min(9.0, W / 70))
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vw:.1f} {vh:.1f}" '
           f'width="{vw:.1f}mm" height="{vh:.1f}mm">',
           f'<rect x="{pad}" y="{pad}" width="{W}" height="{H}" fill="#f7f7f5" stroke="#444" stroke-width="0.8"/>']
    for x, y in holes or []:
        out.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="1.6" fill="#c9c9c4"/>')
    for s in sorted(trace.segments, key=lambda s: s.power_mw):
        if s.power_mw < 1e-4:
            continue
        w = 0.5 + 0.55 * math.log10(1 + s.power_mw)
        dash = ' stroke-dasharray="4 3"' if s.end_reason == "escaped" else ""
        out.append(f'<line x1="{X(s.start[0]):.2f}" y1="{Y(s.start[1]):.2f}" x2="{X(s.end[0]):.2f}" '
                   f'y2="{Y(s.end[1]):.2f}" stroke="{wavelength_color(s.wavelength_nm)}" '
                   f'stroke-width="{w:.2f}" stroke-linecap="round" opacity="0.9"{dash}/>')
    for src in design.sources:
        x, y = X(src.position[0]), Y(src.position[1])
        a = -src.direction_deg
        out.append(f'<g transform="translate({x:.1f},{y:.1f}) rotate({a:.1f})">'
                   f'<rect x="-34" y="-7" width="34" height="14" rx="2" fill="#333"/></g>')
        out.append(f'<text x="{x:.1f}" y="{y - 10:.1f}" font-size="{fs:.1f}" text-anchor="middle" '
                   f'fill="#222">{_esc(src.id)}</text>')
    for e in trace.elements:
        if not e.position:
            continue
        x, y = X(e.position[0]), Y(e.position[1])
        a = -(e.angle_deg or 0.0)
        t = e.type
        if t == "mirror":
            sym = '<rect x="-1.5" y="-9" width="3" height="18" fill="#555"/>'
        elif t in ("pbs", "beamsplitter", "sampler", "dichroic"):
            sym = ('<rect x="-6" y="-6" width="12" height="12" fill="#dfe7ee" stroke="#456" stroke-width="0.7"/>'
                   '<line x1="-6" y1="6" x2="6" y2="-6" stroke="#456" stroke-width="0.7"/>')
            a -= 0.0
        elif t == "lens":
            sym = '<ellipse cx="0" cy="0" rx="2.2" ry="9" fill="#e3eef7" stroke="#357" stroke-width="0.7"/>'
        elif t in ("half_wave_plate", "quarter_wave_plate"):
            sym = '<rect x="-1.2" y="-8" width="2.4" height="16" fill="#c7a6e0" stroke="#639" stroke-width="0.5"/>'
        elif t in ("photodiode", "fiber_coupler"):
            sym = '<rect x="0" y="-6" width="10" height="12" fill="#2f5d3a"/>'
        elif t == "beam_dump":
            sym = '<rect x="-1" y="-5" width="6" height="10" fill="#111"/>'
        elif t == "aom":
            sym = '<rect x="-10" y="-6" width="20" height="12" fill="#e8dcc5" stroke="#875" stroke-width="0.7"/>'
        else:
            sym = '<rect x="-7" y="-5" width="14" height="10" fill="#eee" stroke="#666" stroke-width="0.7"/>'
        out.append(f'<g transform="translate({x:.1f},{y:.1f}) rotate({a:.1f})">{sym}</g>')
        out.append(f'<text x="{x + 8:.1f}" y="{y + 11:.1f}" font-size="{fs * 0.85:.1f}" fill="#222">'
                   f'{_esc(e.id)}</text>')
    # scale bar
    bar = 50.0 if W < 600 else 100.0
    sy = H + 2 * pad + 4
    out.append(f'<line x1="{pad}" y1="{sy}" x2="{pad + bar}" y2="{sy}" stroke="#222" stroke-width="1.2"/>')
    out.append(f'<text x="{pad + bar + 4}" y="{sy + 3}" font-size="{fs:.1f}" fill="#222">{bar:.0f} mm</text>')
    out.append(f'<text x="{pad + W}" y="{sy + 3}" font-size="{fs:.1f}" text-anchor="end" fill="#555">'
               f'{W:.0f} × {H:.0f} mm, grid {bp.grid_mm:g} mm</text>')
    out.append("</svg>")
    return "\n".join(out)


_SPLITS = {"pbs", "beamsplitter", "sampler", "dichroic", "aom", "sfg_crystal"}
_ROLE = {"t": "transmitted", "r": "reflected", "0": "zero order", "+1": "+1 order", "-1": "−1 order", "sfg": "sum-frequency"}


def human_title(name: str) -> str:
    """'dual_beam_optical_tweezers' -> 'Dual Beam Optical Tweezers' (all-caps words kept: AOM, SFG)."""
    words = name.replace("_", " ").replace("-", " ").split()
    return " ".join(w if w.isupper() else w[:1].upper() + w[1:] for w in words)


def _title_size(title: str) -> int:
    """Cover title size: 26 pt up to ~28 characters, shrinking for longer names (min 13 pt)."""
    return max(13, min(26, int(26 * 28 / max(len(title), 1))))


def direction_text(deg: float) -> str:
    """0 -> '+x', 90 -> '+y', 180 -> '−x', 270 -> '−y' (within 0.5°), else e.g. '135.0°'."""
    a = deg % 360.0
    for card, name in ((0, "+x"), (90, "+y"), (180, "−x"), (270, "−y"), (360, "+x")):
        if abs(a - card) < 0.5:
            return name
    return f"{a:.1f}°"


def _short(label: str, n: int = 48) -> str:
    """Agent-written labels can be sentences: keep the part before the first bracket/colon."""
    s = (label or "").split(" (")[0].split(":")[0].strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _beam_order(design: Design, trace: TraceResult) -> list[str]:
    ids = {e.id for e in design.elements}
    order: list[str] = []
    for s in trace.segments:
        if s.end_element in ids and s.end_element not in order:
            order.append(s.end_element)
    order += [e.id for e in design.elements if e.id not in order]
    return order


def _eyewear(wls: list[float], pmax: float) -> list[list[str]]:
    od = max(2, math.ceil(math.log10(max(pmax, 1.0))) + 1)
    rows = []
    for wl in sorted(set(round(w) for w in wls)):
        band = ("UV" if wl < 400 else "visible" if wl <= 700 else "near-IR (invisible!)" if wl < 1400
                else "IR (eye-safe band, still hazardous to skin/optics)")
        rows.append([f"{wl} nm", band, f"OD ≥ {od} at {wl} nm (generic; confirm with your laser safety officer)"])
    return rows


# ───────────────────────────── content ──────────────────────────────────────

def _data(design: Design, trace: TraceResult, report, bom: dict, tune_summary: dict | None,
          citation: str | None, license: str | None, has_cover: bool, has_figure: bool) -> dict:
    by_id = {e.id: e for e in design.elements}
    pe = {e.id: e for e in trace.elements}
    order = _beam_order(design, trace)
    pns: dict[str, list[str]] = {}
    for r in bom["purchased"]:
        for eid in r["element_ids"]:
            pns.setdefault(eid, []).append(r["part_number"])
    outs: dict[str, list[str]] = {}
    for s in trace.segments:
        if s.start_element in by_id and s.power_mw > 1e-4:
            role = _ROLE.get(s.branch.rsplit(".", 1)[-1], "") if by_id[s.start_element].type in _SPLITS else ""
            outs.setdefault(s.start_element, []).append(
                f"{role + ' ' if role else ''}→ {direction_text(s.direction_deg)} ({s.power_mw:.3g} mW)")
    prev: dict[str, str] = {}
    for s in trace.segments:
        if s.end_element in by_id and s.end_element not in prev and s.start_element:
            prev[s.end_element] = s.start_element
    blocks: dict[str, list[str]] = {}
    names = {**{e.id: e.id for e in design.elements}, **{src.id: src.id for src in design.sources}}
    for s in trace.segments:
        if s.end_element in by_id and by_id[s.end_element].type == "beam_dump":
            frm = names.get(s.start_element or "", "the source")
            blocks.setdefault(s.end_element, []).append(
                f"beam from {frm}, travelling {direction_text(s.direction_deg)} "
                f"({s.power_mw:.3g} mW, {s.wavelength_nm:g} nm)")

    changes = []
    if tune_summary:
        changes = tune_summary.get("changes") or tune_summary.get("done") or []
    tuned = {(c["element_id"], c["field"]): c.get("to") for c in changes if c.get("to") is not None}

    def val(el, field):
        return tuned.get((el.id, field), getattr(el, field))

    # specs
    wls = sorted({s.wavelength_nm for s in design.sources})
    m = report.metrics
    fibers = [e for e in trace.elements if e.type == "fiber_coupler"]
    specs = [["Wavelengths", ", ".join(f"{w:g} nm" for w in wls)],
             ["Input power", f"{m.get('input_mw', 0):.3g} mW from {len(design.sources)} source(s)"],
             ["Delivered (fibers + detectors)", f"{m.get('delivered_mw', 0):.3g} mW"],
             ["Elements / beam segments", f"{len(design.elements)} / {len(trace.segments)}"],
             ["Baseplate", f"{design.baseplate.width_mm:g} × {design.baseplate.height_mm:g} × "
                           f"{design.baseplate.thickness_mm:g} mm, {bom['plate']['tiles']} printed tile(s)"]]
    for f in fibers:
        specs.append([f"Fiber {f.id}", f"{(f.power_out_mw or 0):.3g} mW, coupling {100 * (f.coupling_efficiency or 0):.0f} %"])

    # verification
    checks = [[c.severity.upper(), c.id, c.message] for c in report.checks if c.severity != "info"
              or c.id == "target"][:40]
    targets = [[c.message, "met" if c.severity == "info" else "UNMET"] for c in report.checks if c.id == "target"]

    # BOM tables
    def money(x):
        return "—" if x is None else f"${x:,.2f}"
    purchased = [[r["part_number"], r["description"], r["vendor"] or "", str(r["qty"]), money(r["unit_price_usd"]),
                  money(None if r["unit_price_usd"] is None else r["unit_price_usd"] * r["qty"])]
                 for r in bom["purchased"]]
    hardware = [[r["part_number"], r["description"], str(r["qty"]), money(r["unit_price_usd"])] for r in bom["hardware"]]
    printed = [[p["name"], p["file"], f"{p['volume_cm3']:g}", f"{p['est_print_h']:g}", f"{p['est_filament_g']:.0f}"]
               for p in bom["printed"]]

    # assembly
    plate = bom["plate"]
    steps = [["Print the baseplate",
              f"Print {len(bom['printed'])} file(s) from stl/ flat, top side up: PLA, 20 % infill, 3 walls "
              f"(≈ {bom['totals']['est_print_h']} h, ≈ {bom['totals']['est_filament_g']:.0f} g)."]]
    if plate["tiles"] > 1:
        steps.append(["Join the tiles", f"Lay the tiles out by their r/c names, overlap the 20 mm half-lap "
                                        f"joints and fasten with {plate['joint_bolts']} M3 × 25 bolts + nuts."])
    steps.append(["Press in the dowel pins", f"Press {plate['pin_holes']} Ø2 × 8 mm pins into the paired pin holes; "
                                              "they key each mount's orientation."])
    steps.append(["Bolt to the table", f"Fix the plate with {plate['table_holes']} 1/4-20 (or M6) cap screws through "
                                        "the counterbored holes (2-grid pitch, half a grid in from the edges)."])
    for k, eid in enumerate(order, 1):
        el, p = by_id[eid], pe.get(eid)
        if p is None or not p.position:
            continue
        pos = f"({p.position[0]:.1f}, {p.position[1]:.1f}) mm"
        head = (f"Mount {short_tag(el.label, el.id)} ({', '.join(pns.get(eid, [])) or el.type}) at site {k}, {pos}; "
                f"orientation {round(p.angle_deg or 0.0, 1) % 360:.1f}°; keyed by pins, one 8-32 screw from below.")
        t = el.type
        extra = ""
        if t in ("half_wave_plate", "quarter_wave_plate"):
            extra = f"Set the fast axis to {val(el, 'fast_axis_deg') or 0:.1f}° from horizontal (H)."
        elif t == "lens":
            extra = (f"f = {el.focal_length_mm or 100:g} mm, "
                     + (f"{val(el, 'distance_mm'):.1f} mm after {prev.get(eid, 'the previous element')}."
                        if el.beam else "at the absolute position above."))
        elif t in ("pbs", "beamsplitter", "sampler", "dichroic"):
            extra = "Outputs: " + "; ".join(outs.get(eid, ["(no light)"]))
            if t == "dichroic":
                extra += f". Reflects {el.reflect or 'below'} {el.cutoff_nm or 650:g} nm."
        elif t == "mirror":
            extra = "Steer the beam to: " + "; ".join(outs.get(eid, ["(no light)"]))
        elif t == "aom":
            extra = (f"Drive at {val(el, 'aom_frequency_mhz') or 80:g} MHz; use the {'+' if (el.aom_order or 1) > 0 else '-'}1 "
                     f"order (≈ {100 * (el.aom_efficiency or 0.8):.0f} % efficiency).")
        elif t == "sfg_crystal":
            extra = "Outputs: " + "; ".join(outs.get(eid, ["(no light)"]))
        elif t == "fiber_coupler":
            extra = (f"Collimation lens f = {val(el, 'focal_length_mm') or 11:g} mm, fiber MFD {el.fiber_mfd_um or 5:g} µm. "
                     f"Walk the two last mirrors and adjust the focus for maximum: expect ≈ {(p.power_out_mw or 0):.3g} mW "
                     f"({100 * (p.coupling_efficiency or 0):.0f} % coupling).")
        elif t == "photodiode":
            extra = f"Expect ≈ {(p.power_out_mw or 0):.3g} mW on the detector."
        elif t == "beam_dump":
            extra = "Blocks: " + "; ".join(blocks.get(eid, ["(nothing in this state)"]))
        steps.append([f"{el.id}", head + (" " + extra if extra else "")])

    # alignment
    align = []
    if changes:
        for c in changes:
            f, t = c.get("from"), c.get("to")
            align.append([c["element_id"], c["field"], "—" if f is None else f"{f:.3g}",
                          "—" if t is None else f"{t:.3g}", f"{c.get('gain', 0):+.3f}"])
    expect = []
    for e in trace.elements:
        if e.type == "fiber_coupler":
            expect.append(f"expect ≈ {(e.power_out_mw or 0):.3g} mW at {e.id}, coupling {100 * (e.coupling_efficiency or 0):.0f} %")
        elif e.type == "photodiode":
            expect.append(f"expect ≈ {(e.power_out_mw or 0):.3g} mW at {e.id}")
    knob_order = [eid for eid in order if by_id[eid].type in
                  ("half_wave_plate", "quarter_wave_plate", "lens", "mirror", "fiber_coupler", "beamsplitter",
                   "sampler", "aom")]

    # safety
    pmax = max([s.power_mw for s in design.sources] + [0.0])
    dumps = [[eid, "; ".join(blocks.get(eid, ["(nothing in the default state)"]))]
             for eid in order if by_id[eid].type == "beam_dump"]
    stray = [c.message for c in report.checks if c.id == "stray_beam"]

    date = _dt.date.today().strftime("%d %B %Y")
    return {
        "title": human_title(design.name), "title_size": _title_size(human_title(design.name)),
        "name": design.name, "date": date,
        "citation": citation or "", "license": license or "", "description": design.description or "",
        "notes": design.notes or "", "has_cover": has_cover, "has_figure": has_figure,
        "specs": specs,
        "passed": report.passed, "score": f"{report.score:.0f}", "checks": checks, "targets": targets,
        "purchased": purchased, "hardware": hardware, "printed": printed,
        "total": money(bom["totals"]["est_cost_usd"]), "price_note": bom["totals"]["price_note"],
        "steps": steps,
        "tuned": bool(changes), "align": align, "knob_order": knob_order, "expect": expect,
        "tune_line": (f"Tuner: objective {tune_summary.get('objective_before', 0):.3f} → "
                      f"{tune_summary.get('objective_after', 0):.3f} in {tune_summary.get('steps', 0)} steps."
                      if tune_summary else ""),
        "wavelengths": ", ".join(f"{w:g} nm" for w in wls), "pmax": f"{pmax:.3g} mW",
        "dumps": dumps, "eyewear": _eyewear([s.wavelength_nm for s in design.sources], pmax), "stray": stray,
    }


TEMPLATE = r'''
#let d = json("data.json")
#let sans = ("IBM Plex Sans", "Helvetica Neue", "Helvetica", "Arial", "Libertinus Sans")
#let mono = ("IBM Plex Mono", "Menlo", "DejaVu Sans Mono")
#let serif = ("Libertinus Serif", "PT Serif", "New Computer Modern")
#set document(title: d.title)
#set page(paper: "a4", margin: (x: 20mm, top: 22mm, bottom: 20mm))
#set text(font: sans, size: 9.5pt, lang: "en")
#set par(justify: false, leading: 0.6em)
#show heading.where(level: 1): it => block(above: 20pt, below: 10pt, breakable: false)[
  #text(font: serif, size: 20pt, weight: "regular", it.body)
  #v(-6pt) #line(length: 100%, stroke: 0.5pt + luma(120))]
#show heading.where(level: 2): it => block(above: 12pt, below: 6pt, text(size: 10.5pt, weight: "bold", it.body))
#let tbl(cols, header, rows, aligns: auto) = table(
  columns: cols, stroke: none, inset: (x: 4pt, y: 3pt), align: aligns,
  fill: (_, y) => if y == 0 { luma(235) } else if calc.even(y) { luma(248) } else { none },
  table.hline(stroke: 0.6pt),
  ..header.map(h => text(weight: "bold", size: 8.5pt, h)),
  table.hline(stroke: 0.4pt),
  ..rows.flatten().map(c => text(size: 8.5pt, c)),
  table.hline(stroke: 0.6pt),
)

// ── cover ──
#page(margin: 0pt, header: none, footer: none)[
  #if d.has_cover [
    #place(top + left, image("cover.jpg", width: 100%, height: 100%, fit: "cover"))
    #place(top + left, rect(width: 100%, height: 62mm, fill: gradient.linear(black.transparentize(35%), black.transparentize(100%), angle: 90deg)))
  ] else [
    #place(top + left, rect(width: 100%, height: 100%, fill: luma(250)))
    #place(center + horizon, dy: 20mm, block(width: 80%)[
      #set align(center)
      #text(font: serif, size: 13pt, fill: luma(90), style: "italic")[A build manual for a tabletop laser-optics setup]
    ])
  ]
  #let ink = if d.has_cover { white } else { black }
  #place(top + center, dy: 14mm, block(width: 86%)[
    #set align(center)
    #text(font: serif, size: 64pt, tracking: 6pt, fill: ink)[BEAMTEAM]
    #v(-30pt)
    #line(length: 100%, stroke: 0.8pt + ink)
    #v(-6pt)
    #grid(columns: (1fr, 1fr), align: (left, right),
      text(size: 8.5pt, fill: ink, tracking: 1pt)[BUILD DOCUMENT · #upper(d.date)],
      text(size: 8.5pt, fill: ink, tracking: 1pt)[#if d.citation != "" [GENERATED FROM #upper(d.citation)] else [DESIGNED IN BEAMTEAM]])
  ])
  #place(bottom + left, dx: 14mm, dy: -16mm, block(width: 80%, fill: if d.has_cover { black.transparentize(45%) } else { none }, inset: 8pt)[
    #text(font: serif, size: d.title_size * 1pt, fill: ink)[#d.title]
  ])
]

#set page(header: context { if counter(page).get().first() > 1 [
  #set text(size: 7.5pt, fill: luma(110))
  BEAMTEAM · #d.title #h(1fr) #d.date
] }, footer: context [#set text(size: 7.5pt, fill: luma(110)); #h(1fr) #counter(page).display() #h(1fr)])

= Overview
#d.description
#if d.notes != "" [ #par(text(size: 8.5pt, fill: luma(80))[#d.notes]) ]

#figure(box(width: 100%, height: 11.5cm, image("plan.svg", width: 100%, height: 100%, fit: "contain")), caption: [Plan view. Beams coloured by wavelength (infrared shown dark magenta), width ∝ log power; dashed = leaves the plate; grey dots = table holes.])

#grid(columns: (1fr, 1fr), gutter: 12pt,
  [
    == Key specifications
    #tbl((auto, 1fr), ("Quantity", "Value"), d.specs)
  ],
  [
    #if d.has_figure [
      == Source figure
      #image("figure.jpg", width: 100%)
      #text(size: 8pt)[#d.citation #if d.license != "" [ (#d.license)]]
    ]
  ])

#pagebreak(weak: true)
= Verification
#text(size: 14pt, weight: "bold", fill: if d.passed { rgb("#2f6b3a") } else { rgb("#9b2c2c") })[#if d.passed [PASS] else [FAIL]]
#h(8pt) score #d.score / 100 (BEAMTEAM tracer: 2D ray + Gaussian beam + Jones polarization)

#if d.targets.len() > 0 [
  == Targets
  #tbl((1fr, auto), ("Target", "Status"), d.targets)
]
== Checks
#if d.checks.len() == 0 [No warnings or errors.] else [
  #tbl((auto, auto, 1fr), ("Severity", "Check", "Message"), d.checks)
]

= Bill of materials
== Purchased parts
#tbl((auto, 1fr, auto, auto, auto, auto), ("Part", "Description", "Vendor", "Qty", "Unit", "Line"), d.purchased,
  aligns: (left, left, left, right, right, right))
#align(right)[*Estimated total: #d.total* \ #text(size: 7.5pt, fill: luma(90))[#d.price_note]]
== Hardware
#tbl((auto, 1fr, auto, auto), ("Part", "Description", "Qty", "Unit"), d.hardware, aligns: (left, left, right, right))
== 3D-printed parts
#tbl((auto, 1fr, auto, auto, auto), ("Part", "STL file", "cm³", "Print h", "PLA g"), d.printed,
  aligns: (left, left, right, right, right))

= Assembly
#for (i, s) in d.steps.enumerate() [
  #block(breakable: false, below: 6pt)[
    #grid(columns: (16mm, 1fr), gutter: 4pt,
      text(weight: "bold")[Step #(i + 1)],
      [*#s.at(0)* — #s.at(1)])
  ]
]

= Alignment procedure
Align in beam order with an iris and an IR card; adjust one knob at a time and keep the best reading.
#if d.tune_line != "" [ #d.tune_line ]

*Order:* #d.knob_order.join(" → ")

#if d.tuned [
  == Tuned values
  #tbl((auto, auto, auto, auto, auto), ("Element", "Knob", "From", "To", "Gain"), d.align,
    aligns: (left, left, right, right, right))
] else [ No tuner run attached: use the design values listed in the assembly steps. ]
== Expected readings
#for e in d.expect [- #e]

= Laser safety
*Wavelengths:* #d.wavelengths. *Maximum source power on the table:* #d.pmax.

#tbl((auto, auto, 1fr), ("Wavelength", "Band", "Eyewear (generic guidance)"), d.eyewear)

== Beam dumps
#if d.dumps.len() == 0 [No beam dumps in this design.] else [
  #tbl((auto, 1fr), ("Dump", "Blocks"), d.dumps)
]
#if d.stray.len() > 0 [
  == Unterminated beams (fix before operation)
  #for s in d.stray [- #s]
]
#block(fill: luma(240), inset: 8pt, width: 100%)[
  *Verify all beam dumps before full power.* Align at the lowest usable power, never look along the
  beam, remove watches and rings, keep the beam below eye level, and enclose invisible (IR) beams.
]

= Credits
- Layout concept and "paint by numbers" baseplates: PyOpticL (code-to-CAD optics).
#if d.citation != "" [- Source paper: #d.citation#if d.license != "" [ — license: #d.license]]
- Designed by Gemini `gemini-4-argon` agents, verified by the BEAMTEAM tracer.
- Prices are list-price estimates; part numbers should be checked against current vendor catalogs.
'''


def build_document(design: Design, *, cover_png: bytes | None = None, tune_summary: dict | None = None,
                   citation: str | None = None, figure_png: bytes | None = None,
                   license: str | None = None, trace: TraceResult | None = None,
                   work_dir: str | Path | None = None) -> bytes:
    """work_dir: keep the Typst sources there (debugging / page previews) instead of a temp dir."""
    from .bom import _plate_features, build_bom
    from .trace import trace as run_trace
    from .verify import verify

    tr = trace if trace is not None else run_trace(design)
    report = verify(design, tr)
    from .bom import KIT_ROOT, design_hash
    cached = KIT_ROOT / design_hash(design) / "bom.json"   # reuse a kit built via /api/bom
    bom = json.loads(cached.read_text()) if cached.exists() else build_bom(design, tr)
    table_holes, _, _ = _plate_features(design, tr)
    import contextlib
    ctx = contextlib.nullcontext(str(work_dir)) if work_dir else tempfile.TemporaryDirectory(prefix="beamline_doc_")
    with ctx as tmp:
        t = Path(tmp)
        t.mkdir(parents=True, exist_ok=True)
        has_cover = has_figure = False
        if cover_png:
            try:
                (t / "cover.jpg").write_bytes(_downscale(cover_png, 1600))
                has_cover = True
            except Exception:
                pass
        if figure_png:
            try:
                (t / "figure.jpg").write_bytes(_downscale(figure_png, 1000))
                has_figure = True
            except Exception:
                pass
        (t / "plan.svg").write_text(plan_svg(design, tr, table_holes))
        data = _data(design, tr, report, bom, tune_summary, citation, license, has_cover, has_figure)
        (t / "data.json").write_text(json.dumps(data))
        (t / "doc.typ").write_text(TEMPLATE)
        proc = subprocess.run([TYPST, "compile", "--root", str(t), str(t / "doc.typ"), str(t / "doc.pdf")],
                              capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            raise RuntimeError(f"typst failed: {proc.stderr[-2000:]}")
        return (t / "doc.pdf").read_bytes()
