"""Goal -> Design pipeline: plan, parallel candidates, trace+verify, repair loop."""
from __future__ import annotations

import asyncio
import logging
import time

from pydantic import BaseModel, Field

from optics.ir import Design, Target

from . import llm, prompts
from .common import (Emit, dump, evaluate_tracked, finalize_event, headline, noop_emit, rank_key,
                     repair_loop)
from .events import AgentTracker
from .common import autofix_step, design_blurb

log = logging.getLogger("beamline.agents.design")


class Module(BaseModel):
    name: str
    purpose: str
    elements: list[str] = Field(default_factory=list, description="ordered element types / parts")


class Plan(BaseModel):
    title: str
    requirements: list[str]
    wavelength_nm: float
    input_power_mw: float
    baseplate_width_mm: float
    baseplate_height_mm: float
    modules: list[Module]
    beam_terminations: list[str] = Field(description="where every beam ends (fiber, photodiode, dump)")
    targets: list[Target]
    approaches: list[str] = Field(description="distinct layout strategies, one per candidate")


# Settings tuned for a ~90 s demo budget (see report in the final summary).
PLAN_THINKING = "low"
PLAN_TIMEOUT_S = 35.0
CANDIDATE_THINKING = "low"
STRAGGLER_GRACE_S = 15.0   # after the first candidate lands, wait at most this long for the rest
CANDIDATE_HARD_S = 75.0    # absolute cap for the candidate stage
REPAIR_THINKING = "low"
TEMPERATURES = [1.0, 0.7, 1.0, 0.85, 1.0, 0.7]
DEFAULT_HINTS = [
    "Compact linear layout: keep the main beam along +x, fold with mirrors at 90° only where needed.",
    "U-shaped layout: fold the beam back with two mirrors so input and output are on the same side.",
    "Generous spacing: prioritise clearance and alignment access, use the full baseplate.",
    "Minimal part count: fewest optics that still meet every requirement.",
]


async def make_plan(goal: str, emit: Emit, tracker: AgentTracker) -> Plan | None:
    await emit({"type": "status", "stage": "plan", "message": "planning requirements and modules"})
    try:
        async with tracker.agent("planner", "planner", "Planner — requirements, modules, targets",
                                 thinking_level=PLAN_THINKING):
            plan = await asyncio.wait_for(
                llm.generate_model(Plan, [prompts.plan_prompt(goal)], system=prompts.system_prompt(),
                                   thinking=PLAN_THINKING, tag="plan"), timeout=PLAN_TIMEOUT_S)
            await tracker.thought("planner", f"Plan: {plan.title}. Modules: "
                                  + "; ".join(f"{m.name} ({m.purpose})" for m in plan.modules)[:330])
    except Exception as e:  # noqa: BLE001
        log.warning("plan failed: %s", e)
        await emit({"type": "status", "stage": "plan", "message": f"planning failed ({(str(e) or type(e).__name__)[:120]}); designing directly"})
        return None
    mods = ", ".join(m.name for m in plan.modules)
    await emit({"type": "status", "stage": "plan",
                "message": f"plan: {plan.title} — modules: {mods}; {len(plan.targets)} targets"})
    return plan


async def _candidate(i: int, goal: str, plan: Plan | None, hint: str, temp: float) -> Design:
    return await llm.generate_model(Design, [prompts.candidate_prompt(goal, plan, hint)],
                                    system=prompts.system_prompt(), thinking=CANDIDATE_THINKING,
                                    temperature=temp, tag=f"cand{i}")


async def design_from_goal(goal: str, emit: Emit = noop_emit, candidates: int = 4,
                           repair_rounds: int = 3, time_budget_s: float = 85.0) -> Design:
    t_start = time.monotonic()
    deadline = t_start + time_budget_s
    candidates = max(1, min(candidates, 6))
    tracker = AgentTracker(emit, model=llm.MODEL)
    plan = await make_plan(goal, emit, tracker)
    t_plan = time.monotonic()

    hints = list(plan.approaches if plan and plan.approaches else [])
    hints += DEFAULT_HINTS
    hints = hints[:candidates]
    while len(hints) < candidates:
        hints.append(DEFAULT_HINTS[len(hints) % len(DEFAULT_HINTS)])

    await emit({"type": "status", "stage": "design", "message": f"generating {candidates} candidate designs"})
    results: list[tuple] = []   # (index, design, trace, report, seq)
    parent = "planner" if plan else None

    async def run(i: int, hint: str, temp: float):
        aid = f"designer-{i + 1}"
        try:
            async with tracker.agent(aid, "designer", f"Designer {i + 1} — {hint[:70]}", parent=parent,
                                     thinking_level=CANDIDATE_THINKING, queued=False):
                d = await _candidate(i, goal, plan, hint, temp)
                await tracker.thought(aid, design_blurb(d))
                tr, rep = await evaluate_tracked(d, tracker, aid)
                seq = await tracker.iteration(aid, f"candidate {i + 1}", d, tr, rep)
                d, tr, rep, seq, _ = await autofix_step(d, tr, rep, tracker, aid, seq)
        except Exception as e:  # noqa: BLE001
            log.warning("candidate %d failed: %s", i, e)
            if not isinstance(e, asyncio.CancelledError):
                await emit({"type": "status", "stage": "design", "message": f"candidate {i} failed: {str(e)[:160]}"})
            return
        results.append((i, d, tr, rep, seq))
        await emit({"type": "candidate", "index": i, "stage": "design", "design": dump(d),
                    "report": dump(rep), "trace": dump(tr)})
        await emit({"type": "status", "stage": "verify",
                    "message": f"candidate {i}: {headline(rep)}"})

    for i in range(candidates):
        await tracker.queued(f"designer-{i + 1}", "designer", f"Designer {i + 1} — {hints[i][:70]}", parent=parent,
                             thinking_level=CANDIDATE_THINKING)
    tasks = [asyncio.create_task(run(i, hints[i], TEMPERATURES[i % len(TEMPERATURES)])) for i in range(candidates)]
    t_c0 = time.monotonic()
    t_first: float | None = None
    pending = set(tasks)
    while pending:
        if t_first is not None:
            left = STRAGGLER_GRACE_S - (time.monotonic() - t_first)
        else:
            left = CANDIDATE_HARD_S - (time.monotonic() - t_c0)
        if left <= 0:
            break
        done, pending = await asyncio.wait(pending, timeout=left, return_when=asyncio.FIRST_COMPLETED)
        if results and t_first is None:
            t_first = time.monotonic()
    if pending:
        await emit({"type": "status", "stage": "design",
                    "message": f"moving on with {len(results)} candidates ({len(pending)} still thinking, cancelled)"})
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)   # let them emit their "cancelled" state
    t_cand = time.monotonic()
    if not results:
        # last resort: one more attempt without temperature tricks
        await emit({"type": "status", "stage": "design", "message": "all candidates failed; retrying once"})
        async with tracker.agent("designer-retry", "designer", "Designer — retry", parent=parent,
                                 thinking_level=CANDIDATE_THINKING):
            d = await _candidate(0, goal, plan, DEFAULT_HINTS[0], 0.7)
            tr, rep = await evaluate_tracked(d, tracker, "designer-retry")
            seq = await tracker.iteration("designer-retry", "candidate (retry)", d, tr, rep)
        results.append((0, d, tr, rep, seq))
        await emit({"type": "candidate", "index": 0, "stage": "design", "design": dump(d),
                    "report": dump(rep), "trace": dump(tr)})

    results.sort(key=lambda r: rank_key(r[3]), reverse=True)
    i, d, tr, rep, seq = results[0]
    await emit({"type": "status", "stage": "verify",
                "message": f"picked candidate {i} as the best ({headline(rep)})"})

    d, tr, rep = await repair_loop(d, tr, rep, goal=goal, emit=emit, rounds=repair_rounds,
                                   thinking=REPAIR_THINKING, index_base=candidates, deadline=deadline,
                                   tracker=tracker, parent_seq=seq, parent_agent=f"designer-{i + 1}")
    t_end = time.monotonic()
    timings = {"plan_s": round(t_plan - t_start, 1), "candidates_s": round(t_cand - t_plan, 1),
               "repair_s": round(t_end - t_cand, 1), "total_s": round(t_end - t_start, 1)}
    log.info("design_from_goal timings %s", timings)
    await emit({"type": "status", "stage": "done",
                "message": f"done in {timings['total_s']}s — score {rep.score:.0f}, passed={rep.passed}",
                "timings": timings})
    await emit(finalize_event(d, tr, rep))
    return d
