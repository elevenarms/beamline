"""Figure -> Design pipeline: 3x parallel vision extraction, merge, synthesis, verify/repair."""
from __future__ import annotations

import asyncio
import logging
import time
from statistics import median

from pydantic import BaseModel, Field

from optics.ir import Design

from . import llm, prompts
from .common import Emit, headline, dump, evaluate, finalize_event, noop_emit, repair_loop

log = logging.getLogger("beamline.agents.reproduce")


class GComponent(BaseModel):
    id: str
    type: str = Field(description="one of the IR element types, or 'laser' for a source, or 'other'")
    label: str = ""
    approx_xy: list[float] = Field(description="[x, y] normalized 0-1 in the image, y measured UP from the bottom")
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


class Graph(BaseModel):
    title: str = ""
    components: list[GComponent]
    beams: list[GBeam]
    parameters: list[GParam] = Field(default_factory=list)
    notes: str = ""


EXTRACT_THINKING = "medium"
MERGE_THINKING = "low"
SYNTH_THINKING = "medium"
REPAIR_THINKING = "low"


def graph_dict(g: Graph) -> dict:
    return g.model_dump(mode="json", by_alias=True, exclude_none=True)


async def _extract(i: int, img, notes: str) -> Graph:
    return await llm.generate_model(Graph, [img, prompts.extract_prompt(notes, i)], thinking=EXTRACT_THINKING,
                                    temperature=[0.4, 0.8, 1.0][i % 3], tag=f"extract{i}")


async def _merge(graphs: list[Graph], img, notes: str) -> Graph:
    if len(graphs) == 1:
        return graphs[0]
    try:
        return await llm.generate_model(Graph, [img, prompts.merge_prompt([graph_dict(g) for g in graphs], notes)],
                                        thinking=MERGE_THINKING, tag="merge")
    except Exception as e:  # noqa: BLE001
        log.warning("LLM merge failed (%s); using median-size graph", e)
        m = median(len(g.components) for g in graphs)
        return min(graphs, key=lambda g: abs(len(g.components) - m))


async def reproduce_from_image(image_bytes: bytes, mime: str, notes: str = "", emit: Emit = noop_emit,
                               repair_rounds: int = 3, time_budget_s: float = 85.0) -> Design:
    t0 = time.monotonic()
    deadline = t0 + time_budget_s
    img = llm.image_part(image_bytes, mime)
    await emit({"type": "status", "stage": "extract", "message": "reading the figure (3 parallel passes)"})
    res = await asyncio.gather(*(_extract(i, img, notes) for i in range(3)), return_exceptions=True)
    graphs = [g for g in res if isinstance(g, Graph) and g.components]
    for r in res:
        if isinstance(r, Exception):
            log.warning("extraction failed: %s", r)
    if not graphs:
        raise llm.LLMError("all vision extraction passes failed: " + "; ".join(str(r)[:150] for r in res))
    await emit({"type": "status", "stage": "extract",
                "message": f"{len(graphs)} passes saw {[len(g.components) for g in graphs]} components; merging"})
    graph = await _merge(graphs, img, notes)
    t_ext = time.monotonic()
    await emit({"type": "extraction", "graph": graph_dict(graph)})

    await emit({"type": "status", "stage": "design", "message": "synthesizing a traceable design from the graph"})
    design = await llm.generate_model(Design, [img, prompts.synth_prompt(graph_dict(graph), notes)],
                                      system=prompts.system_prompt(), thinking=SYNTH_THINKING, tag="synth")
    tr, rep = evaluate(design)
    t_syn = time.monotonic()
    await emit({"type": "candidate", "index": 0, "stage": "design", "design": dump(design),
                "report": dump(rep), "trace": dump(tr)})
    await emit({"type": "status", "stage": "verify", "message": f"synthesized design: {headline(rep)}"})

    goal = ("Reproduce the optical setup in the figure, preserving its topology and relative layout. "
            f"Extracted graph: {llm.json.dumps(graph_dict(graph), separators=(',', ':'))}"
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
    return design
