"""Figure -> Design pipeline: 3x parallel vision extraction (0-1000 boxes), majority vote / merge,
pixel -> mm scaling from known part sizes, synthesis, verify/repair, then a figure<->design match event."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import struct
import time
from statistics import median

from pydantic import BaseModel, Field

from optics.ir import Design

from . import llm, prompts
from .common import Emit, dump, evaluate, finalize_event, headline, noop_emit, repair_loop
from .match import match_event

log = logging.getLogger("beamline.agents.reproduce")


# ───────────────────────────── extraction schemas ─────────────────────────────

class RawComponent(BaseModel):
    id: str
    type: str = Field(description="one of the IR element types, 'laser' for a source, or 'other'")
    label: str = ""
    box_2d: list[int] = Field(description="[ymin, xmin, ymax, xmax] normalized 0-1000, origin top-left")
    part_number: str | None = None


class GBeam(BaseModel):
    from_: str = Field(alias="from")
    to: str
    label: str | None = None
    wavelength_nm: float | None = None

    model_config = {"populate_by_name": True}


class GParam(BaseModel):
    name: str
    value: str
    unit: str = ""
    evidence: str = ""


class RawGraph(BaseModel):
    title: str = ""
    baseplate_box_2d: list[int] | None = Field(
        default=None, description="[ymin, xmin, ymax, xmax] 0-1000 of the baseplate/breadboard if drawn")
    components: list[RawComponent]
    beams: list[GBeam]
    parameters: list[GParam] = Field(default_factory=list)
    notes: str = ""


EXTRACT_THINKING = "medium"
MERGE_THINKING = "low"
SYNTH_THINKING = "low"
REPAIR_THINKING = "low"
EXTRACT_GRACE_S = 10.0   # after the first vision pass lands, wait at most this long for the others
EXTRACT_HARD_S = 60.0
SYNTH_TIMEOUT_S = 70.0
MIN_SPACING_MM = 40.0
# Approximate largest drawn extent (mm) of a mounted part, used as a scale anchor.
ANCHOR_MM = {"mirror": 38.0, "half_wave_plate": 38.0, "quarter_wave_plate": 38.0}


def _signature(g: RawGraph) -> tuple:
    """Order-independent parts list, used for majority voting between vision passes."""
    return tuple(sorted(c.type for c in g.components))


# ───────────────────────────── geometry ─────────────────────────────

def image_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) for PNG / JPEG / GIF / WebP, without PIL."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", data[16:24])
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", data[6:10])
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            if data[12:16] == b"VP8X":
                return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
            if data[12:16] == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30])
                return w & 0x3FFF, h & 0x3FFF
        if data[:2] == b"\xff\xd8":
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    except Exception:  # noqa: BLE001
        pass
    return None


def _box(b: list[int] | None) -> tuple[float, float, float, float] | None:
    if not b or len(b) != 4:
        return None
    y0, x0, y1, x1 = (max(0.0, min(1000.0, float(v))) for v in b)
    return min(y0, y1), min(x0, x1), max(y0, y1), max(x0, x1)


def scale_graph(raw: RawGraph, img_wh: tuple[int, int] | None, notes: str = "") -> dict:
    """Graph dict for the event/synthesis: approx_xy (0-1, y up), box_2d, and xy_mm on a baseplate.

    Scale anchor: drawn mirror / waveplate mounts ≈ 38 mm (1") or 28 mm (1/2"), then stretched so optic
    centres are >= 40 mm apart (drawings tend to be compressed; figures read 1.5-3x short)."""
    W, H = img_wh or (1000, 1000)
    half_inch = any(k in (notes + raw.title).lower() for k in ('1/2"', "half-inch", "half inch", "1/2 in"))
    comps = []
    for c in raw.components:
        b = _box(c.box_2d) or (500, 500, 500, 500)
        y0, x0, y1, x1 = b
        cx, cy = (x0 + x1) / 2000 * W, (y0 + y1) / 2000 * H          # px, y down
        bw, bh = (x1 - x0) / 1000 * W, (y1 - y0) / 1000 * H
        comps.append((c, cx, cy, bw, bh))

    sizes = [max(bw, bh) / (ANCHOR_MM[c.type] * (28 / 38 if half_inch else 1.0))
             for c, _, _, bw, bh in comps if c.type in ANCHOR_MM and max(bw, bh) > 5]
    px_per_mm = median(sizes) if sizes else None
    pts = [(cx, cy) for c, cx, cy, _, _ in comps if c.type != "other"]
    if px_per_mm is None:
        xs = [p[0] for p in pts] or [0, W]
        px_per_mm = max(max(xs) - min(xs), 1.0) / 350.0          # spread the parts over ~350 mm
    mm_per_px = 1.0 / px_per_mm
    # enforce mount spacing: 20th-percentile nearest-neighbour distance >= MIN_SPACING_MM
    nn = []
    for i, (xa, ya) in enumerate(pts):
        d = [math.hypot(xa - xb, ya - yb) for j, (xb, yb) in enumerate(pts) if j != i]
        d = [x for x in d if x > 2]
        if d:
            nn.append(min(d))
    if nn:
        nn.sort()
        p20 = nn[max(0, int(0.2 * len(nn)) - 1)] * mm_per_px
        if p20 < MIN_SPACING_MM:
            mm_per_px *= MIN_SPACING_MM / max(p20, 1.0)

    pb = _box(raw.baseplate_box_2d)
    if pb:
        px0, py_top, px1, py_bot = pb[1] / 1000 * W, pb[0] / 1000 * H, pb[3] / 1000 * W, pb[2] / 1000 * H
    else:
        px0, px1 = min(p[0] for p in pts or [(0, 0)]), max(p[0] for p in pts or [(W, H)])
        py_top, py_bot = min(p[1] for p in pts or [(0, 0)]), max(p[1] for p in pts or [(W, H)])
    margin_px = 30.0 / mm_per_px
    px0 = min([px0] + [p[0] - margin_px for p in pts])
    px1 = max([px1] + [p[0] + margin_px for p in pts])
    py_top = min([py_top] + [p[1] - margin_px for p in pts])
    py_bot = max([py_bot] + [p[1] + margin_px for p in pts])
    plate_w = (px1 - px0) * mm_per_px
    plate_h = (py_bot - py_top) * mm_per_px
    if plate_w > 900:  # keep it a tabletop module
        f = 900 / plate_w
        mm_per_px *= f
        plate_w, plate_h = plate_w * f, plate_h * f

    out_comps = []
    for c, cx, cy, _, _ in comps:
        d = {"id": c.id, "type": c.type, "label": c.label,
             "approx_xy": [round(cx / W, 3), round(1 - cy / H, 3)],
             "box_2d": c.box_2d,
             "xy_mm": [round((cx - px0) * mm_per_px), round((py_bot - cy) * mm_per_px)]}
        if c.part_number:
            d["part_number"] = c.part_number
        out_comps.append(d)
    return {
        "title": raw.title,
        "components": out_comps,
        "beams": [b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in raw.beams],
        "parameters": [p.model_dump(mode="json") for p in raw.parameters],
        "notes": raw.notes,
        "scale_mm_per_px": round(mm_per_px, 4),
        "baseplate_mm": [round(plate_w / 5) * 5, round(plate_h / 5) * 5],
    }


# ───────────────────────────── LLM steps ─────────────────────────────

async def _extract(i: int, img, notes: str) -> RawGraph:
    return await llm.generate_model(RawGraph, [img, prompts.extract_prompt(notes, i)], thinking=EXTRACT_THINKING,
                                    temperature=[0.4, 0.8, 1.0][i % 3], tag=f"extract{i}")


async def _merge(graphs: list[RawGraph], img, notes: str) -> RawGraph:
    if len(graphs) == 1:
        return graphs[0]
    try:
        return await asyncio.wait_for(llm.generate_model(
            RawGraph, [img, prompts.merge_prompt([g.model_dump(mode="json", by_alias=True, exclude_none=True)
                                                 for g in graphs], notes)],
            thinking=MERGE_THINKING, tag="merge"), timeout=30)
    except Exception as e:  # noqa: BLE001
        log.warning("LLM merge failed (%s); using median-size graph", e)
        m = median(len(g.components) for g in graphs)
        return min(graphs, key=lambda g: abs(len(g.components) - m))


async def _extract_all(img, notes: str, emit: Emit, t0: float) -> RawGraph:
    tasks = [asyncio.create_task(_extract(i, img, notes)) for i in range(3)]
    graphs: list[RawGraph] = []
    errors: list[str] = []
    t_first: float | None = None
    pending = set(tasks)
    while pending:
        left = (EXTRACT_GRACE_S - (time.monotonic() - t_first)) if t_first is not None \
            else (EXTRACT_HARD_S - (time.monotonic() - t0))
        if left <= 0:
            break
        done, pending = await asyncio.wait(pending, timeout=left, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            try:
                g = t.result()
            except Exception as e:  # noqa: BLE001
                log.warning("extraction failed: %s", e)
                errors.append(str(e)[:150])
                continue
            if g.components:
                graphs.append(g)
                await emit({"type": "status", "stage": "extract",
                            "message": f"vision pass {len(graphs)}: {len(g.components)} components, "
                                       f"{len(g.beams)} beam links"})
                if t_first is None:
                    t_first = time.monotonic()
    for t in pending:
        t.cancel()
    if not graphs:
        raise llm.LLMError("all vision extraction passes failed: " + "; ".join(errors))
    sigs = [_signature(g) for g in graphs]
    if len(graphs) >= 2 and max(sigs.count(x) for x in sigs) >= 2:
        best_sig = max(sigs, key=sigs.count)
        await emit({"type": "status", "stage": "extract",
                    "message": f"{sigs.count(best_sig)}/{len(graphs)} vision passes agree on the parts list"})
        return next(g for g, sg in zip(graphs, sigs) if sg == best_sig)
    await emit({"type": "status", "stage": "extract",
                "message": f"vision passes disagree ({[len(g.components) for g in graphs]} components); merging"})
    return await _merge(graphs, img, notes)


async def reproduce_from_image(image_bytes: bytes, mime: str, notes: str = "", emit: Emit = noop_emit,
                               repair_rounds: int = 3, time_budget_s: float = 75.0) -> Design:
    t0 = time.monotonic()
    deadline = t0 + time_budget_s
    img = llm.image_part(image_bytes, mime)
    await emit({"type": "status", "stage": "extract", "message": "reading the figure (3 parallel passes)"})
    raw = await _extract_all(img, notes, emit, t0)
    graph = scale_graph(raw, image_size(image_bytes), notes)
    t_ext = time.monotonic()
    await emit({"type": "extraction", "graph": graph})
    w, h = graph["baseplate_mm"]
    await emit({"type": "status", "stage": "extract",
                "message": f"scaled the drawing to a {w:.0f} x {h:.0f} mm baseplate "
                           f"({graph['scale_mm_per_px']:.2f} mm/px, mounts >= {MIN_SPACING_MM:.0f} mm apart)"})

    await emit({"type": "status", "stage": "design", "message": "synthesizing a traceable design from the graph"})
    synth_msg = prompts.synth_prompt(graph, notes)
    try:
        design = await asyncio.wait_for(llm.generate_model(
            Design, [img, synth_msg], system=prompts.system_prompt(), thinking=SYNTH_THINKING, tag="synth"),
            timeout=SYNTH_TIMEOUT_S)
    except (asyncio.TimeoutError, TimeoutError):
        await emit({"type": "status", "stage": "design", "message": "synthesis slow; retrying with low thinking"})
        design = await llm.generate_model(Design, [img, synth_msg], system=prompts.system_prompt(),
                                          thinking="low", tag="synth-retry")
    tr, rep = evaluate(design)
    t_syn = time.monotonic()
    await emit({"type": "candidate", "index": 0, "stage": "design", "design": dump(design),
                "report": dump(rep), "trace": dump(tr)})
    await emit({"type": "status", "stage": "verify", "message": f"synthesized design: {headline(rep)}"})

    compact = {"components": [{k: c[k] for k in ("id", "type", "label", "xy_mm")} for c in graph["components"]],
               "beams": graph["beams"]}
    goal = ("Reproduce the optical setup in the figure, preserving its topology and relative layout. "
            f"Extracted graph (xy_mm = suggested table position): {json.dumps(compact, separators=(',', ':'))}"
            + (f"\nUser notes: {notes}" if notes else ""))
    design, tr, rep = await repair_loop(design, tr, rep, goal=goal, emit=emit, rounds=repair_rounds,
                                        thinking=REPAIR_THINKING, index_base=1, deadline=deadline)
    t_end = time.monotonic()
    timings = {"extract_s": round(t_ext - t0, 1), "synth_s": round(t_syn - t_ext, 1),
               "repair_s": round(t_end - t_syn, 1), "total_s": round(t_end - t0, 1)}
    log.info("reproduce timings %s", timings)
    await emit({"type": "status", "stage": "done",
                "message": f"done in {timings['total_s']}s — score {rep.score:.0f}, passed={rep.passed}",
                "timings": timings})
    await emit(finalize_event(design, tr, rep))
    try:
        await emit(match_event(graph, design, tr))
    except Exception as e:  # noqa: BLE001
        log.warning("match failed: %s", e)
    return design
