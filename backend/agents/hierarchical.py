"""Hierarchical goal -> Design pipeline for big multi-laser apparatus (50-200 optics).

    async design_hierarchical(goal, emit, max_modules=8, time_budget_s=120) -> Design

1. Architect (Gemini, thinking "high", structured output): split the goal into fiber-in/fiber-out modules
   (title, purpose, wavelength, power, size, outputs, fiber links, suggested targets).  Regions are then packed
   deterministically onto a table (shelf packing, 25 mm snap) -- the model only proposes sizes.
   Power budget: the architect lists every physical laser once and the feed links (fiber / free_space, power);
   compute_budget() derives each module's input deterministically (laser heads -> root modules; feeds capped at
   90 % of the sender's input; fiber feeds x0.7), enforce_budget() rescales each module design's sources to it
   (labels "fed from <module>"), budget_report() adds total_laser_mw / sum_of_module_inputs_mw metrics and
   "power_budget" warnings to the final report.
   Emits status(stage=plan) and {"type":"modules","modules":[Module...],"table":Baseplate,"links":[...],
   "lasers":[...],"budget":{module_id: {input_mw, laser_ids, fed_from, feeds_out, unbudgeted, label}}}.
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

from typing import Literal

from pydantic import BaseModel, Field

from optics.ir import Baseplate, Check, Design, Module, Target, TraceResult, VerifyReport
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
    laser_ids: list[str] = Field(default_factory=list,
                                 description="ids of the lasers (from Architecture.lasers) whose HEAD sits in this "
                                             "module; empty if the module is fed from other modules")
    input_power_mw: float = Field(description="planned optical power entering the module (recomputed from the "
                                              "laser powers and feed links by the pipeline)")
    input: str = Field(description="where light enters: 'laser head <model>' or 'fiber from <module_id>'")
    outputs: list[str] = Field(description="each delivered output, e.g. 'fiber to trap: cooling beam'")
    width_mm: float = Field(description="region width needed, 300-600 mm")
    height_mm: float = Field(description="region height needed, 150-450 mm")
    targets: list[Target] = Field(default_factory=list,
                                  description="suggested verifier targets on this module's own element ids")


class Laser(BaseModel):
    id: str = Field(description="short id, e.g. laser_1064")
    model: str = Field(description="real laser, e.g. 'Toptica DL pro 422' or 'Azurlight 1064 nm fiber amplifier'")
    wavelength_nm: float
    power_mw: float = Field(description="realistic output power of this ONE physical laser")


class FiberLink(BaseModel):
    """A light feed from one module to another (name kept for compatibility; kind may be free_space)."""
    from_module: str
    to_module: str
    purpose: str
    kind: Literal["fiber", "free_space"] = "fiber"
    power_mw: float = Field(0.0, description="power the upstream module sends into this feed (before fiber loss)")


class Architecture(BaseModel):
    title: str
    summary: str
    lasers: list[Laser] = Field(default_factory=list,
                                description="EVERY physical laser in the apparatus, each listed once")
    modules: list[ModuleSpec] = Field(min_length=3, description="3-8 modules covering the WHOLE apparatus")
    links: list[FiberLink] = Field(default_factory=list,
                                   description="every light feed between modules, with its power")


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
(min_power_mw / min_coupling on output elements; use ids like FC1, FC2, PD1).
POWER BUDGET (strict): list every physical laser ONCE in `lasers` with its real output power. Each laser head
sits in exactly one module (its laser_ids). A laser shared by several subsystems (e.g. one 3 W 1064 nm laser
for several tweezer/lattice paths, or one 422 nm laser for cooling + detection) goes into ONE module that
splits it and FEEDS the others through `links` (kind "fiber", or "free_space" only if unavoidable) with the
power sent into each feed. A module's feeds can never add up to more than the light it receives. Fiber feeds
lose ~30 % in fiber coupling. Never give two modules their own copy of the same laser."""


def module_goal(goal: str, spec: ModuleSpec, region: tuple, links: list[FiberLink],
                budget: dict | None = None) -> str:
    w, h = region[2], region[3]
    b = budget or {}
    ins = [f"{l.kind.replace('_', '-')} feed from {l.from_module} ({l.purpose}): "
           f"{_feed_in(l):.0f} mW arrives" for l in links if l.to_module == spec.id]
    outs = [f"{l.kind.replace('_', '-')} feed to {l.to_module} ({l.purpose}): send {l.power_mw:.0f} mW into "
            + ("a fiber_coupler" if l.kind == "fiber" else "a beam_dump labelled 'free-space port to "
               f"{l.to_module}' at the region edge") for l in links if l.from_module == spec.id]
    if b.get("label"):
        src_rule = (f"- POWER: the module's input sources must total EXACTLY {b['input_mw']:.0f} mW "
                    f"({b['label']}); set each source label to start with \"{b['label']}\". Do not add light.")
    else:
        src_rule = f"- POWER: input sources total {spec.input_power_mw:g} mW."
    tg = json.dumps([t.model_dump() for t in spec.targets]) if spec.targets else "(choose sensible ones)"
    return f"""This is ONE MODULE ("{spec.id}": {spec.title}) of a larger apparatus. Overall goal: {goal}

Module purpose: {spec.purpose}
Wavelength: {spec.wavelength_nm:g} nm. Input: {b.get('label') or spec.input}, {b.get('input_mw', spec.input_power_mw):.0f} mW
{('(incoming feeds: ' + '; '.join(ins) + ')') if ins else ''}
Delivered outputs: {'; '.join(spec.outputs + outs) or 'fiber couplers'}.
HARD CONSTRAINTS:
- The baseplate is exactly {w:g} x {h:g} mm (this module's region; local frame, origin lower-left). Set
  baseplate.width_mm={w:g}, height_mm={h:g}. Every optic must be >= 15 mm inside it.
- Sources: the module's own laser head or fiber-launch collimator (e.g. id L1), placed near the left edge.
{src_rule}
- Every beam terminates inside the module (fiber_coupler / photodiode / beam_dump). No free-space beam leaves.
- Suggested targets (keep ids consistent with your elements): {tg}"""


# ───────────────────────────── power budget ─────────────────────────────

FIBER_EFF = 0.7          # fiber-coupling efficiency assumed for a fiber feed between modules
MODULE_PASS = 0.9        # a module can send at most this fraction of its input into outgoing feeds


def _feed_in(l: FiberLink) -> float:
    return l.power_mw * (FIBER_EFF if l.kind == "fiber" else 1.0)


def compute_budget(specs: list[ModuleSpec], lasers: list[Laser], links: list[FiberLink]
                   ) -> tuple[dict[str, dict], list[FiberLink]]:
    """Deterministic power accounting (the architect's arithmetic is not trusted).
    Root modules get the full power of the lasers whose heads they host (a laser claimed by several modules
    is split equally). Modules are then processed in feed order: outgoing feeds are scaled down so they total
    <= MODULE_PASS x the module's input; a fed module's input = sum of its incoming feeds x FIBER_EFF (fiber)
    or x1 (free space). Modules with neither a laser nor a feed keep the architect's input and are flagged
    'unbudgeted' (light from nowhere -> power_budget warning). Returns (budget per module, adjusted links)."""
    ids = {s.id for s in specs}
    laser_by_id = {l.id: l for l in lasers}
    claims: dict[str, list[str]] = {}
    for s in specs:
        for lid in s.laser_ids:
            if lid in laser_by_id:
                claims.setdefault(lid, []).append(s.id)
    links = [l.model_copy() for l in links if l.from_module in ids and l.to_module in ids
             and l.from_module != l.to_module]
    budget: dict[str, dict] = {}
    for s in specs:
        own = [(lid, laser_by_id[lid].power_mw / len(claims[lid])) for lid in s.laser_ids if lid in laser_by_id]
        budget[s.id] = {"input_mw": sum(p for _, p in own), "laser_ids": [lid for lid, _ in own],
                        "fed_from": [], "feeds_out": [], "unbudgeted": False, "label": ""}
    incoming = {s.id: [l for l in links if l.to_module == s.id] for s in specs}
    done: set[str] = set()
    order: list[str] = []
    while len(done) < len(specs):
        ready = [s.id for s in specs if s.id not in done
                 and all(l.from_module in done for l in incoming[s.id])]
        if not ready:      # feed cycle: break it at the first remaining module
            ready = [next(s.id for s in specs if s.id not in done)]
        for mid in ready:
            b = budget[mid]
            fed = [l for l in incoming[mid] if l.from_module in done]
            b["input_mw"] += sum(_feed_in(l) for l in fed)
            b["fed_from"] = [{"module": l.from_module, "kind": l.kind, "power_mw": round(_feed_in(l), 1)}
                             for l in fed]
            spec = next(s for s in specs if s.id == mid)
            if not b["laser_ids"] and not fed:
                b["unbudgeted"] = True
                b["input_mw"] = spec.input_power_mw
            outs = [l for l in links if l.from_module == mid]
            want = sum(l.power_mw for l in outs)
            cap = MODULE_PASS * b["input_mw"]
            if outs and (want > cap or want <= 0):
                for l in outs:   # scale to the cap (or split it equally if powers were missing)
                    l.power_mw = cap * (l.power_mw / want if want > 0 else 1 / len(outs))
            b["feeds_out"] = [{"module": l.to_module, "kind": l.kind, "power_mw": round(l.power_mw, 1)}
                              for l in outs]
            parts = [f"laser {', '.join(b['laser_ids'])}"] if b["laser_ids"] else []
            parts += [f"fed from {f['module']} ({f['kind'].replace('_', '-')})" for f in b["fed_from"]]
            b["label"] = "; ".join(parts) if parts else ""
            b["input_mw"] = round(b["input_mw"], 1)
            done.add(mid)
            order.append(mid)
    return budget, links


def enforce_budget(d: Design, b: dict | None) -> Design:
    """Scale a module design's source powers to total exactly its allocated input (and its min_power_mw targets
    by the same factor); prefix source labels with the feed origin."""
    if not b or b.get("unbudgeted") or not d.sources:
        return d
    total = sum(s.power_mw for s in d.sources)
    k = b["input_mw"] / total if total > 0 else 1.0
    srcs = []
    for s in d.sources:
        lab = s.label if b["label"] and s.label.startswith(b["label"]) else f"{b['label']}: {s.label}".strip(": ")
        srcs.append(s.model_copy(update={"power_mw": round(s.power_mw * k, 3), "label": lab[:120]}))
    tg = [t.model_copy(update={"value": round(float(t.value) * k, 3)})
          if t.kind == "min_power_mw" and isinstance(t.value, (int, float)) and abs(k - 1) > 1e-3 else t
          for t in d.targets]
    return d.model_copy(update={"sources": srcs, "targets": tg})


def budget_report(rep: VerifyReport, lasers: list[Laser], budget: dict[str, dict], links: list[FiberLink],
                  delivered_fiber: dict[str, float]) -> VerifyReport:
    """Add total_laser_mw / sum_of_module_inputs_mw metrics and power_budget warnings to the merged report.
    sum_of_module_inputs_mw counts light that ENTERS the table (root modules' laser power + unbudgeted modules);
    fed modules re-use upstream light, so they add nothing."""
    total_laser = sum(l.power_mw for l in lasers)
    fresh = sum(b["input_mw"] for b in budget.values() if b["laser_ids"] or b["unbudgeted"])
    checks = list(rep.checks)
    n_warn = 0
    metrics = {**rep.metrics, "total_laser_mw": total_laser, "sum_of_module_inputs_mw": fresh,
               "sum_of_all_module_sources_mw": sum(b["input_mw"] for b in budget.values())}
    checks.append(Check(id="power_budget", severity="info", value=fresh, limit=total_laser,
                        message=f"light entering modules {fresh:.0f} mW vs lasers {total_laser:.0f} mW"))
    if fresh > total_laser * 1.01 + 1e-6:
        n_warn += 1
        un = [m for m, b in budget.items() if b["unbudgeted"]]
        checks.append(Check(id="power_budget", severity="warning", value=fresh, limit=total_laser,
                            message=f"modules draw {fresh:.0f} mW but the lasers only provide {total_laser:.0f} mW"
                                    + (f" (modules with no laser or feed: {', '.join(un)})" if un else "")))
    for mid, b in budget.items():
        promised = sum(f["power_mw"] for f in b["feeds_out"] if f["kind"] == "fiber")
        if promised > 0 and mid in delivered_fiber and delivered_fiber[mid] < 0.9 * promised:
            n_warn += 1
            checks.append(Check(id="power_budget", severity="warning", value=delivered_fiber[mid], limit=promised,
                                message=f"{mid} couples {delivered_fiber[mid]:.0f} mW into fibers but its feeds "
                                        f"promise {promised:.0f} mW downstream"))
    return rep.model_copy(update={"checks": checks, "metrics": metrics,
                                  "score": max(0.0, rep.score - 5.0 * n_warn)})


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
                         emit: Emit, deadline: float, budget: dict | None = None) -> tuple[Design, object, object, dict] | None:
    t0 = time.monotonic()
    region = mod.region
    bp = local_baseplate(table, region)
    mgoal = module_goal(goal, spec, region, links, budget)

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
        res = await _design_module_body(spec, mod, bp, mgoal, memit, mt, agent_id, deadline, t0, budget)
        if res is None:
            raise llm.LLMError("all candidates failed")
        return res


async def _design_module_body(spec, mod, bp, mgoal, memit, mt, agent_id, deadline, t0, budget):

    async def one(i: int) -> tuple:
        d = await asyncio.wait_for(
            llm.generate_model(Design, [prompts.candidate_prompt(mgoal, None, DEFAULT_HINTS[i % len(DEFAULT_HINTS)])],
                               system=prompts.system_prompt(), thinking=MODULE_THINKING,
                               temperature=(1.0, 0.7, 0.85)[i % 3], tag=f"{mod.id}.cand{i}"),
            timeout=min(CAND_TIMEOUT_S, max(10.0, deadline - time.monotonic())))
        d = enforce_budget(d.model_copy(update={"baseplate": bp, "modules": []}), budget)
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
    fixed = enforce_budget(d.model_copy(update={"baseplate": bp}), budget)
    if fixed != d:                 # repairs may resize the plate or change input power; region + budget are fixed
        d = fixed
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
    budget, links = compute_budget(specs, arch.lasers, links)
    specs = [s.model_copy(update={"input_power_mw": budget[s.id]["input_mw"]}) for s in specs]
    table, mods = pack_regions(specs)
    await emit({"type": "status", "stage": "plan",
                "message": f"architecture: {arch.title} — {len(mods)} modules on a "
                           f"{table.width_mm:.0f}x{table.height_mm:.0f} mm table: "
                           + ", ".join(m.title or m.id for m in mods)})
    await emit({"type": "modules", "modules": [dump(m) for m in mods], "table": dump(table),
                "links": [dump(l) for l in links], "title": arch.title,
                "lasers": [dump(l) for l in arch.lasers], "budget": budget})
    for m in mods:
        await tracker.queued(f"module:{m.id}", "module", f"Module {m.id} — {m.title}"[:120], parent="architect",
                             thinking_level=MODULE_THINKING)

    # module design gets what is left of the budget, minus a few seconds for merge/verify
    deadline = max(t_start + time_budget_s - 3.0, time.monotonic() + MIN_MODULE_STAGE_S)
    await emit({"type": "status", "stage": "design",
                "message": f"designing {len(mods)} modules in parallel ({MODULE_CANDIDATES} candidates each)"})
    module_info: dict[str, dict] = {}
    parts: list[tuple[Module, Design]] = []
    delivered_fiber: dict[str, float] = {}
    acc_lock = asyncio.Lock()
    acc_seq: list[int | None] = [None]   # seq of the latest "modules merged so far" iteration

    async def run(spec: ModuleSpec, mod: Module):
        try:
            res = await _design_module(goal, spec, mod, table, links, emit, deadline, budget.get(mod.id))
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
        delivered_fiber[mod.id] = sum(e.power_out_mw or 0.0 for e in tr.elements if e.type == "fiber_coupler")
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
        rep = budget_report(rep, arch.lasers, {m.id: budget[m.id] for m, _ in parts}, links, delivered_fiber)
        await tracker.tool("merge", "verify", f"power budget: {rep.metrics['sum_of_module_inputs_mw']:.0f} mW "
                           f"into modules vs {rep.metrics['total_laser_mw']:.0f} mW of lasers", 0.0)
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
