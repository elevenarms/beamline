"""Hierarchical goal -> Design pipeline for big multi-laser apparatus (50-200 optics).

    async design_hierarchical(goal, emit, max_modules=8, time_budget_s=120) -> Design

1. Architect (Gemini, thinking "high", structured output): split the goal into fiber-in/fiber-out modules
   (title, purpose, wavelength, power, size, outputs, fiber links, suggested targets).  Regions are then packed
   deterministically onto a table (shelf packing, 25 mm snap) -- the model only proposes sizes.
   Emits status(stage=plan) and {"type":"modules","modules":[Module...],"table":Baseplate,"links":[...]}.
2. Every module is designed IN PARALLEL in its local frame (baseplate = region size) with the shared
   single-design machinery: prompts.system_prompt + prompts.candidate_prompt (module-scoped goal), 2 candidates,
   best one -> common.repair_loop.  A module whose candidates all fail gets one retry; else it is left out
   (status message + {"type":"module_failed"}).  Emits {"type":"module_done","module_id","design","report",
   "trace","local_design","timings"} where design/trace are in TABLE coordinates (ids prefixed
   "<module_id>.", group set) so the viewer can overlay them; report is the module-local verify report.
3. optics.merge.merge_modules -> trace + verify the whole -> {"type":"final",...}.

CLI:  uv run python -m agents.hierarchical "Full laser system for ..." [-o out.json] [-m 8]
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time

from pydantic import BaseModel, Field

from optics.ir import Baseplate, Design, Module, Target
from optics.merge import local_baseplate, merge_modules

from . import llm, prompts
from .common import (Emit, dump, evaluate, evaluate_tracked, finalize_event, headline, noop_emit, rank_key,
                     repair_loop)
from .design import DEFAULT_HINTS
from .events import AgentTracker

log = logging.getLogger("beamline.agents.hierarchical")

ARCH_THINKING = "high"
ARCH_TIMEOUT_S = 70.0
ARCH_HIGH_GRACE_S = 8.0
MIN_MODULE_STAGE_S = 65.0  # modules always get at least this long, even if the architect was slow
MODULE_THINKING = "low"
MODULE_CANDIDATES = 2
CAND_TIMEOUT_S = 70.0       # per module candidate call
STRAGGLER_GRACE_S = 12.0    # after a module's first candidate lands
REPAIR_ROUNDS = 2
SNAP = 25.0
MIN_W, MAX_W, MIN_H, MAX_H = 300.0, 650.0, 150.0, 450.0
TABLE_WIDTHS = (600.0, 900.0, 1200.0, 1500.0, 1800.0)
GAP = 25.0                  # clearance between module regions


# ───────────────────────────── architect schema ─────────────────────────────

class ModuleSpec(BaseModel):
    id: str = Field(description="short snake_case id, e.g. cooling_422")
    title: str
    purpose: str = Field(description="what this module does, which optics it needs, in 1-3 sentences")
    wavelength_nm: float
    input_power_mw: float = Field(description="optical power entering the module (laser head or fiber launch)")
    input: str = Field(description="where light enters: 'laser head <model>' or 'fiber from <module_id>'")
    outputs: list[str] = Field(description="each delivered output, e.g. 'fiber to trap: cooling beam'")
    width_mm: float = Field(description="region width needed, 300-600 mm")
    height_mm: float = Field(description="region height needed, 150-450 mm")
    targets: list[Target] = Field(default_factory=list,
                                  description="suggested verifier targets on this module's own element ids")


class FiberLink(BaseModel):
    from_module: str
    to_module: str
    purpose: str


class Architecture(BaseModel):
    title: str
    summary: str
    modules: list[ModuleSpec] = Field(min_length=3, description="3-8 modules covering the WHOLE apparatus")
    links: list[FiberLink] = Field(default_factory=list)


ARCH_SYSTEM = f"""You are the lead architect of large atomic-physics (AMO) laser systems: trapped ions, neutral-atom
arrays, cold-atom machines. You decompose an apparatus into breadboard modules that separate engineers lay out;
you do not draw geometry yourself. Reference parts and practices the module engineers use:
{prompts.CATALOG}
{prompts.HEURISTICS}"""


def architect_prompt(goal: str, max_modules: int) -> str:
    return f"""Goal from the user:
\"\"\"{goal}\"\"\"

You are the lead architect of a LARGE optical apparatus (tens to hundreds of optics, several lasers). Split it
into 3-{max_modules} independent MODULES (cover EVERY subsystem the goal implies, one module per laser at least), each a self-contained breadboard section that a separate engineer
will lay out. Modules exchange light ONLY through optical fibers: every module starts with exactly the light
sources it needs (a laser head, or a fiber launch from another module) and ends in fiber couplers,
photodiodes or beam dumps -- no free-space beams cross between modules.
Typical modules: one per laser/wavelength (isolation, AOM switching/shifting, power monitoring, fiber
coupling), spectroscopy/locking references, beam distribution into several fibers. Keep each module
moderately sized (8-25 optics). Give realistic wavelengths and powers, a region size per module
(width 300-600 mm, height 150-450 mm, multiples of 25 mm) that comfortably fits its optics with >= 40 mm
between optic centres, the fiber links between modules, and 1-4 suggested verifier targets per module
(min_power_mw / min_coupling on output elements; use ids like FC1, FC2, PD1)."""


def module_goal(goal: str, spec: ModuleSpec, region: tuple, links: list[FiberLink]) -> str:
    w, h = region[2], region[3]
    ins = [f"fiber from {l.from_module} ({l.purpose})" for l in links if l.to_module == spec.id]
    outs = [f"fiber to {l.to_module} ({l.purpose})" for l in links if l.from_module == spec.id]
    tg = json.dumps([t.model_dump() for t in spec.targets]) if spec.targets else "(choose sensible ones)"
    return f"""This is ONE MODULE ("{spec.id}": {spec.title}) of a larger apparatus. Overall goal: {goal}

Module purpose: {spec.purpose}
Wavelength: {spec.wavelength_nm:g} nm. Input: {spec.input} with {spec.input_power_mw:g} mW
{('(fiber launches: ' + '; '.join(ins) + ')') if ins else ''}
Delivered outputs: {'; '.join(spec.outputs + outs) or 'fiber couplers'}.
HARD CONSTRAINTS:
- The baseplate is exactly {w:g} x {h:g} mm (this module's region; local frame, origin lower-left). Set
  baseplate.width_mm={w:g}, height_mm={h:g}. Every optic must be >= 15 mm inside it.
- Sources: the module's own laser head or fiber-launch collimator (e.g. id L1), placed near the left edge.
- Every beam terminates inside the module (fiber_coupler / photodiode / beam_dump). No free-space beam leaves.
- Suggested targets (keep ids consistent with your elements): {tg}"""


# ───────────────────────────── region packing ─────────────────────────────

def _snap(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, math.ceil(v / SNAP) * SNAP))


def pack_regions(specs: list[ModuleSpec]) -> tuple[Baseplate, list[Module]]:
    """Shelf-pack module rectangles (tallest first) onto the standard table width giving the smallest table
    area (tables taller than 2x their width only as a last resort). Sizes snapped to 25 mm; regions separated by GAP."""
    sizes = [(_snap(s.width_mm, MIN_W, MAX_W), _snap(s.height_mm, MIN_H, MAX_H)) for s in specs]
    order = sorted(range(len(specs)), key=lambda i: (-sizes[i][1], -sizes[i][0]))
    best = None
    for tw in TABLE_WIDTHS:
        if max(w for w, _ in sizes) + 2 * GAP > tw:
            continue
        x = y = GAP
        row_h = 0.0
        pos = {}
        for i in order:
            w, h = sizes[i]
            if x + w + GAP > tw:
                x, y, row_h = GAP, y + row_h + GAP, 0.0
            pos[i] = (x, y)
            x += w + GAP
            row_h = max(row_h, h)
        th = math.ceil((y + row_h + GAP) / SNAP) * SNAP
        key = (th > 2 * tw, tw * th)   # prefer not-too-elongated, then smallest area
        if best is None or key < best[0]:
            best = (key, tw, th, pos)
    _, tw, th, pos = best
    table = Baseplate(width_mm=tw, height_mm=th, grid_mm=25.0)
    mods = [Module(id=s.id, title=s.title, description=s.purpose,
                   region=(pos[i][0], pos[i][1], sizes[i][0], sizes[i][1])) for i, s in enumerate(specs)]
    return table, mods


def _clean_id(s: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", s.lower()).strip("_") or "mod"
    out, k = base, 2
    while out in used:
        out, k = f"{base}_{k}", k + 1
    used.add(out)
    return out


# ───────────────────────────── pipeline ─────────────────────────────

async def _arch_call(goal: str, max_modules: int, thinking: str) -> Architecture:
    arch = await llm.generate_model(Architecture, [architect_prompt(goal, max_modules)], system=ARCH_SYSTEM,
                                    thinking=thinking, tag=f"architect-{thinking}")
    if len(arch.modules) < 2:
        raise ValueError(f"architect returned only {len(arch.modules)} module(s)")
    return arch


async def make_architecture(goal: str, emit: Emit, max_modules: int) -> Architecture:
    """Race a thinking="high" and a thinking="medium" architect call (high took >75 s in tests, medium ~30 s):
    prefer high, but once medium has landed wait at most ARCH_HIGH_GRACE_S more for it."""
    await emit({"type": "status", "stage": "plan", "message": "architect: splitting the apparatus into modules"})
    hi = asyncio.create_task(_arch_call(goal, max_modules, ARCH_THINKING))
    med = asyncio.create_task(_arch_call(goal, max_modules, "medium"))
    t0 = time.monotonic()
    try:
        done, _ = await asyncio.wait({hi, med}, timeout=ARCH_TIMEOUT_S, return_when=asyncio.FIRST_COMPLETED)
        if med in done and hi not in done and med.exception() is None:
            left = min(ARCH_HIGH_GRACE_S, ARCH_TIMEOUT_S - (time.monotonic() - t0))
            if left > 0:
                await asyncio.wait({hi}, timeout=left)
        elif hi in done and hi.exception() is not None and med not in done:
            await asyncio.wait({med}, timeout=max(1.0, ARCH_TIMEOUT_S - (time.monotonic() - t0)))
        for t, name in ((hi, ARCH_THINKING), (med, "medium")):
            if t.done() and not t.cancelled() and t.exception() is None:
                log.info("architect: using thinking=%s result after %.1fs", name, time.monotonic() - t0)
                return t.result()
        errs = [repr(t.exception()) for t in (hi, med) if t.done() and not t.cancelled() and t.exception()]
        raise llm.LLMError(f"architect failed: {'; '.join(errs) or 'timed out'}")
    finally:
        for t in (hi, med):
            t.cancel()


async def _design_module(goal: str, spec: ModuleSpec, mod: Module, table: Baseplate, links: list[FiberLink],
                         emit: Emit, deadline: float) -> tuple[Design, object, object, dict] | None:
    t0 = time.monotonic()
    region = mod.region
    bp = local_baseplate(table, region)
    mgoal = module_goal(goal, spec, region, links)

    agent_id = f"module:{mod.id}"

    async def memit(ev: dict) -> None:
        """Module-scoped event stream: statuses get a [module] prefix; module-LOCAL candidate/iteration designs
        are dropped (the pipeline emits table-frame iterations instead); console agent ids from the shared
        repair loop ("repair-1") are namespaced "module:<id>/repair-1" so they stay unique per run."""
        t = ev.get("type")
        if t == "status":
            await emit({**ev, "module_id": mod.id, "message": f"[{mod.id}] {ev['message']}"})
        elif t in ("candidate", "iteration"):
            return
        else:
            ev = dict(ev)
            aid = ev.get("agent_id")
            if aid and not aid.startswith("module:"):
                ev["agent_id"] = f"{agent_id}/{aid}"
            await emit(ev)

    mt = AgentTracker(memit, model=llm.MODEL)
    async with mt.agent(agent_id, "module", f"Module {mod.id} — {spec.title}"[:120], parent="architect",
                        thinking_level=MODULE_THINKING, queued=False):
        res = await _design_module_body(spec, mod, bp, mgoal, memit, mt, agent_id, deadline, t0)
        if res is None:
            raise llm.LLMError("all candidates failed")
        return res


async def _design_module_body(spec, mod, bp, mgoal, memit, mt, agent_id, deadline, t0):

    async def one(i: int) -> tuple:
        d = await asyncio.wait_for(
            llm.generate_model(Design, [prompts.candidate_prompt(mgoal, None, DEFAULT_HINTS[i % len(DEFAULT_HINTS)])],
                               system=prompts.system_prompt(), thinking=MODULE_THINKING,
                               temperature=(1.0, 0.7, 0.85)[i % 3], tag=f"{mod.id}.cand{i}"),
            timeout=min(CAND_TIMEOUT_S, max(10.0, deadline - time.monotonic())))
        d = d.model_copy(update={"baseplate": bp, "modules": []})
        tr, rep = await evaluate_tracked(d, mt, agent_id)
        return d, tr, rep

    results: list[tuple] = []
    for attempt in range(2):       # one retry if every candidate failed
        n = MODULE_CANDIDATES if attempt == 0 else 1
        tasks = [asyncio.create_task(one(i + attempt * MODULE_CANDIDATES)) for i in range(n)]
        pending, t_first = set(tasks), None
        while pending:
            timeout = None if t_first is None else max(0.0, STRAGGLER_GRACE_S - (time.monotonic() - t_first))
            done, pending = await asyncio.wait(pending, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                break
            for t in done:
                if t.exception() is None:
                    results.append(t.result())
                else:
                    log.warning("%s candidate failed: %r", mod.id, t.exception())
            if results and t_first is None:
                t_first = time.monotonic()
        for t in pending:
            t.cancel()
        if results:
            break
        await memit({"type": "status", "stage": "design", "message": "all candidates failed, retrying once"})
    if not results:
        return None
    t_cand = time.monotonic()
    results.sort(key=lambda r: rank_key(r[2]), reverse=True)
    d, tr, rep = results[0]
    await memit({"type": "status", "stage": "verify", "message": f"best of {len(results)} candidates: {headline(rep)}"})
    d, tr, rep = await repair_loop(d, tr, rep, goal=mgoal, emit=memit, rounds=REPAIR_ROUNDS,
                                   thinking=MODULE_THINKING, deadline=deadline, tracker=mt,
                                   parent_agent=agent_id)
    if d.baseplate != bp:          # repairs may try to resize; the region is fixed
        d = d.model_copy(update={"baseplate": bp})
        tr, rep = evaluate(d)
    t_end = time.monotonic()
    timings = {"candidates_s": round(t_cand - t0, 1), "repair_s": round(t_end - t_cand, 1),
               "total_s": round(t_end - t0, 1)}
    return d, tr, rep, timings


def _ordered(parts: list[tuple[Module, Design]], mods: list[Module]) -> list[tuple[Module, Design]]:
    order = {m.id: i for i, m in enumerate(mods)}
    return sorted(parts, key=lambda p: order[p[0].id])


async def design_hierarchical(goal: str, emit: Emit = noop_emit, max_modules: int = 8,
                              time_budget_s: float = 120.0) -> Design:
    t_start = time.monotonic()
    tracker = AgentTracker(emit, model=llm.MODEL)
    try:
        async with tracker.agent("architect", "architect", "Architect — split apparatus into fiber-linked modules",
                                 thinking_level=ARCH_THINKING):
            arch = await make_architecture(goal, emit, max_modules)
            await tracker.thought("architect", f"{arch.title}: " + "; ".join(
                f"{m.id} ({m.wavelength_nm:g} nm)" for m in arch.modules))
    except Exception as e:  # noqa: BLE001
        await emit({"type": "error", "message": f"architect failed: {str(e)[:300]}"})
        raise
    t_plan = time.monotonic()

    used: set[str] = set()
    remap = {}
    specs = []
    for s in arch.modules[:max_modules]:
        new = _clean_id(s.id, used)
        remap[s.id] = new
        specs.append(s.model_copy(update={"id": new}))
    links = [l.model_copy(update={"from_module": remap.get(l.from_module, l.from_module),
                                  "to_module": remap.get(l.to_module, l.to_module)}) for l in arch.links]
    table, mods = pack_regions(specs)
    await emit({"type": "status", "stage": "plan",
                "message": f"architecture: {arch.title} — {len(mods)} modules on a "
                           f"{table.width_mm:.0f}x{table.height_mm:.0f} mm table: "
                           + ", ".join(m.title or m.id for m in mods)})
    await emit({"type": "modules", "modules": [dump(m) for m in mods], "table": dump(table),
                "links": [dump(l) for l in links], "title": arch.title})
    for m in mods:
        await tracker.queued(f"module:{m.id}", "module", f"Module {m.id} — {m.title}"[:120], parent="architect",
                             thinking_level=MODULE_THINKING)

    # module design gets what is left of the budget, minus a few seconds for merge/verify
    deadline = max(t_start + time_budget_s - 3.0, time.monotonic() + MIN_MODULE_STAGE_S)
    await emit({"type": "status", "stage": "design",
                "message": f"designing {len(mods)} modules in parallel ({MODULE_CANDIDATES} candidates each)"})
    module_info: dict[str, dict] = {}
    parts: list[tuple[Module, Design]] = []
    acc_lock = asyncio.Lock()
    acc_seq: list[int | None] = [None]   # seq of the latest "modules merged so far" iteration

    async def run(spec: ModuleSpec, mod: Module):
        try:
            res = await _design_module(goal, spec, mod, table, links, emit, deadline)
        except Exception as e:  # noqa: BLE001
            log.exception("module %s crashed", mod.id)
            res, err = None, str(e) or type(e).__name__
        else:
            err = "all candidates failed"
        if res is None:
            module_info[mod.id] = {"ok": False, "error": err[:200]}
            await emit({"type": "module_failed", "module_id": mod.id, "message": err[:300]})
            await emit({"type": "status", "stage": "design", "module_id": mod.id,
                        "message": f"[{mod.id}] FAILED ({err[:120]}); leaving it out"})
            return
        d, tr, rep, timings = res
        placed = merge_modules(d.name, d.description, table, [(mod, d)])
        ptr, _ = evaluate(placed)
        async with acc_lock:   # one iteration per finished module: the table with every module done so far
            parts.append((mod, d))
            acc = merge_modules(arch.title, arch.summary, table, _ordered(parts, mods))
            atr, arep = evaluate(acc)
            acc_seq[0] = await tracker.iteration(
                f"module:{mod.id}", f"module {mod.id} done ({len(parts)}/{len(mods)})", acc, atr, arep,
                parent_seq=acc_seq[0], rationale=f"{mod.id}: {headline(rep)} ({len(d.elements)} optics)")
        module_info[mod.id] = {"ok": True, "score": round(rep.score, 1), "passed": rep.passed,
                               "elements": len(d.elements), **timings}
        await emit({"type": "module_done", "module_id": mod.id, "design": dump(placed), "trace": dump(ptr),
                    "report": dump(rep), "local_design": dump(d), "timings": timings})
        await emit({"type": "status", "stage": "verify", "module_id": mod.id,
                    "message": f"[{mod.id}] done in {timings['total_s']}s: {headline(rep)} ({len(d.elements)} optics)"})

    await asyncio.gather(*(run(s, m) for s, m in zip(specs, mods)))
    t_mod = time.monotonic()
    if not parts:
        await emit({"type": "error", "message": "every module failed"})
        raise llm.LLMError("hierarchical design: every module failed")

    async with tracker.agent("merge", "merge", f"Merge {len(parts)} modules onto the table", parent="architect"):
        t0 = time.perf_counter()
        merged = merge_modules(arch.title, arch.summary + "\nFiber links: " + "; ".join(
            f"{l.from_module} -> {l.to_module} ({l.purpose})" for l in links), table, _ordered(parts, mods))
        await tracker.tool("merge", "merge", f"merged {len(parts)} modules: {len(merged.sources)} sources, "
                           f"{len(merged.elements)} optics, {len(merged.targets)} targets",
                           (time.perf_counter() - t0) * 1e3)
        tr, rep = await evaluate_tracked(merged, tracker, "merge")
        await tracker.iteration("merge", f"merged apparatus ({len(parts)} modules)", merged, tr, rep,
                                parent_seq=acc_seq[0], rationale=headline(rep))
    t_end = time.monotonic()
    timings = {"plan_s": round(t_plan - t_start, 1), "modules_s": round(t_mod - t_plan, 1),
               "merge_verify_s": round(t_end - t_mod, 2), "total_s": round(t_end - t_start, 1)}
    log.info("design_hierarchical timings %s", timings)
    n_ok = sum(1 for v in module_info.values() if v.get("ok"))
    await emit({"type": "status", "stage": "done", "timings": timings, "modules": module_info,
                "message": f"done in {timings['total_s']}s — {n_ok}/{len(mods)} modules, {len(merged.elements)} "
                           f"optics, score {rep.score:.0f}, passed={rep.passed}"})
    await emit(finalize_event(merged, tr, rep))
    return merged


# ───────────────────────────── CLI ─────────────────────────────

async def _main() -> None:
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(prog="agents.hierarchical")
    ap.add_argument("goal")
    ap.add_argument("-m", "--max-modules", type=int, default=8)
    ap.add_argument("-t", "--time-budget", type=float, default=120.0)
    ap.add_argument("-o", "--out")
    ap.add_argument("--events", help="also write all events as JSONL here")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("beamline").setLevel(logging.INFO)

    t0 = time.monotonic()
    ev_f = open(args.events, "w") if args.events else None
    summary: dict = {}

    async def emit(ev: dict) -> None:
        dt = time.monotonic() - t0
        if ev_f:
            ev_f.write(json.dumps({"t": round(dt, 2), **ev}) + "\n")
        t = ev["type"]
        if t == "status":
            print(f"[{dt:6.1f}s] {ev['stage']:<7} {ev['message']}", flush=True)
            if ev["stage"] == "done":
                summary.update(ev)
        elif t == "modules":
            for m in ev["modules"]:
                print(f"            module {m['id']:<22} region={m['region']}")
        elif t == "final":
            rep = ev["report"]
            print(f"[{dt:6.1f}s] FINAL score={rep['score']:.1f} passed={rep['passed']} "
                  f"elements={len(ev['design']['elements'])} segments={len(ev['trace']['segments'])}")
            for c in [c for c in rep["checks"] if c["severity"] != "info"][:15]:
                print(f"            - [{c['severity']}] {c['id']}: {c['message'][:130]}")
        elif t == "error":
            print(f"[{dt:6.1f}s] ERROR {ev['message']}")

    design = await design_hierarchical(args.goal, emit, max_modules=args.max_modules,
                                       time_budget_s=args.time_budget)
    slug = re.sub(r"[^a-z0-9]+", "_", args.goal.lower()).strip("_")[:40]
    out = args.out or f"hierarchical_{slug}.json"
    Path(out).write_text(design.model_dump_json(indent=1, exclude_none=True))
    print(f"\nsaved {out}  ({time.monotonic() - t0:.1f}s total)")
    print("timings:", json.dumps(summary.get("timings")))
    for mid, info in (summary.get("modules") or {}).items():
        print(f"  {mid:<24} {json.dumps(info)}")
    print("LLM usage:", json.dumps(llm.usage_summary()))
    if ev_f:
        ev_f.close()


if __name__ == "__main__":
    asyncio.run(_main())
