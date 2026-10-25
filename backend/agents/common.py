"""Shared helpers for the agent pipelines: safe trace+verify, trace summaries for repair
prompts, event serialisation, and the verify→repair loop."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from optics.ir import Check, Design, TraceResult, VerifyReport

from . import llm, prompts
from .events import AgentTracker

log = logging.getLogger("beamline.agents")

Emit = Callable[[dict], Awaitable[None]]


async def noop_emit(_: dict) -> None:
    return None


def dump(model) -> dict:
    return model.model_dump(mode="json")


def evaluate(design: Design) -> tuple[TraceResult, VerifyReport]:
    """trace + verify, never raising: tracer crashes become a failing report."""
    from optics.trace import trace
    from optics.verify import verify
    try:
        tr = trace(design)
    except Exception as e:  # noqa: BLE001
        log.exception("trace crashed")
        tr = TraceResult(segments=[], elements=[], branches=[])
        return tr, VerifyReport(passed=False, score=0.0, checks=[Check(
            id="trace_error", severity="error", message=f"tracer crashed: {type(e).__name__}: {e}")])
    try:
        rep = verify(design, tr)
    except Exception as e:  # noqa: BLE001
        log.exception("verify crashed")
        rep = VerifyReport(passed=False, score=0.0, checks=[Check(
            id="verify_error", severity="error", message=f"verifier crashed: {type(e).__name__}: {e}")])
    return tr, rep


def design_blurb(d: Design) -> str:
    """One console line describing a freshly generated design."""
    kinds: dict[str, int] = {}
    for e in d.elements:
        kinds[e.type] = kinds.get(e.type, 0) + 1
    parts = ", ".join(f"{n}x {k.replace('_', ' ')}" for k, n in sorted(kinds.items(), key=lambda x: -x[1]))
    head = f"Drafted '{d.name}' on a {d.baseplate.width_mm:.0f}x{d.baseplate.height_mm:.0f} mm plate: {parts}."
    if d.description:
        head += " " + d.description
    return head[:400]


def trace_tool_summary(tr: TraceResult) -> str:
    unplaced = [e.id for e in tr.elements if not e.placed]
    out = f"trace: {len(tr.segments)} segments, {len(tr.branches)} branches"
    if unplaced:
        out += f", {len(unplaced)} unplaced ({', '.join(unplaced[:4])}{'…' if len(unplaced) > 4 else ''})"
    return out


def verify_tool_summary(rep: VerifyReport) -> str:
    errs = [c for c in rep.checks if c.severity == "error"]
    warns = [c for c in rep.checks if c.severity == "warning"]
    out = f"verify: score {rep.score:.0f}"
    if rep.passed and not warns:
        return out + ", all checks passed"
    parts = []
    if errs:
        parts.append(f"{len(errs)} error{'s' if len(errs) != 1 else ''}")
    if warns:
        parts.append(f"{len(warns)} warning{'s' if len(warns) != 1 else ''}")
    out += ", " + ", ".join(parts)
    first = (errs or warns)[0]
    msg = first.message
    m = re.search(r"on (\S+) \(([\d.]+) mW\)", msg) if first.id == "stray_beam" else None
    if m:
        msg = f"{float(m.group(2)):.2g} mW on {m.group(1)}"
    elif first.element_id and first.element_id not in msg:
        msg = f"at {first.element_id}: {msg}"
    return (out + f" — {first.id.replace('_', ' ')} {msg}")[:180]


async def evaluate_tracked(design: Design, tracker: AgentTracker | None, agent_id: str
                           ) -> tuple[TraceResult, VerifyReport]:
    """evaluate() with `tool` console events for the trace and verify runs."""
    from optics.trace import trace
    from optics.verify import verify
    t0 = time.perf_counter()
    try:
        tr = trace(design)
    except Exception as e:  # noqa: BLE001
        log.exception("trace crashed")
        tr = TraceResult(segments=[], elements=[], branches=[])
        rep = VerifyReport(passed=False, score=0.0, checks=[Check(
            id="trace_error", severity="error", message=f"tracer crashed: {type(e).__name__}: {e}")])
        if tracker:
            await tracker.tool(agent_id, "trace", f"trace crashed: {type(e).__name__}", (time.perf_counter() - t0) * 1e3)
        return tr, rep
    t1 = time.perf_counter()
    if tracker:
        await tracker.tool(agent_id, "trace", trace_tool_summary(tr), (t1 - t0) * 1e3)
    t1 = time.perf_counter()
    try:
        rep = verify(design, tr)
    except Exception as e:  # noqa: BLE001
        log.exception("verify crashed")
        rep = VerifyReport(passed=False, score=0.0, checks=[Check(
            id="verify_error", severity="error", message=f"verifier crashed: {type(e).__name__}: {e}")])
    if tracker:
        await tracker.tool(agent_id, "verify", verify_tool_summary(rep), (time.perf_counter() - t1) * 1e3)
    return tr, rep


def headline(rep: VerifyReport) -> str:
    """Short audience-readable verdict, e.g. 'score 62 — stray beam at PBS1 (+2 more errors)'."""
    errs = [c for c in rep.checks if c.severity == "error"]
    if rep.passed:
        return f"score {rep.score:.0f} — all checks passed"
    if not errs:
        return f"score {rep.score:.0f} — targets not met"
    c = errs[0]
    where = f" at {c.element_id}" if c.element_id and c.element_id not in c.message else ""
    more = f" (+{len(errs) - 1} more)" if len(errs) > 1 else ""
    return f"score {rep.score:.0f} — {c.id.replace('_', ' ')}{where}: {c.message[:90]}{more}"


def rank_key(rep: VerifyReport) -> tuple:
    n_err = sum(c.severity == "error" for c in rep.checks)
    return (rep.passed, rep.score, -n_err)


def _f(x: float | None, nd: int = 1) -> str:
    return "?" if x is None else f"{x:.{nd}f}"


def trace_summary(design: Design, tr: TraceResult, max_lines: int = 160) -> str:
    """Compact, model-readable digest of a trace."""
    lines: list[str] = []
    lines.append(f"branches: {', '.join(tr.branches) or '(none)'}")
    by_branch: dict[str, list] = defaultdict(list)
    for s in tr.segments:
        by_branch[s.branch].append(s)
    lines.append("segments per branch (start_element -> end_element, dir, length, power, pol, w_end, end_reason):")
    for b, segs in by_branch.items():
        lines.append(f"  [{b}]")
        for s in segs:
            fs = f" shift={s.freq_shift_mhz:+.0f}MHz" if s.freq_shift_mhz else ""
            lines.append(
                f"    {s.start_element or '?'} ({_f(s.start[0],0)},{_f(s.start[1],0)}) -> "
                f"{s.end_element or '-'} ({_f(s.end[0],0)},{_f(s.end[1],0)}) dir={_f(s.direction_deg,0)}° "
                f"L={_f(s.length_mm,0)} P={_f(s.power_mw,2)}mW pol={s.polarization_label} "
                f"w={_f(s.w_end_mm,2)}mm{fs} [{s.end_reason}]")
    lines.append("elements (placed?, position, angle, power in, clip, extra):")
    for e in tr.elements:
        if not e.placed:
            lines.append(f"  {e.id} {e.type}: NOT PLACED — {e.error or 'unknown reason'}")
            continue
        pin = ", ".join(f"{h.power_in_mw:.2f}mW(clip {h.clip_loss:.0%}, off {h.offset_mm:.1f}mm)" for h in e.hits)
        extra = ""
        if e.coupling_efficiency is not None:
            extra += f" coupling={e.coupling_efficiency:.2f}"
        if e.power_out_mw is not None:
            extra += f" absorbed/coupled={e.power_out_mw:.2f}mW"
        if not e.hits:
            extra += " (NOT HIT by any beam)"
        pos = f"({_f(e.position[0],0)},{_f(e.position[1],0)})" if e.position else "?"
        lines.append(f"  {e.id} {e.type} @{pos} angle={_f(e.angle_deg,0)} hits=[{pin}]{extra}")
        if e.error:
            lines.append(f"    note: {e.error}")
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... ({len(lines) - max_lines} more lines truncated)"]
    return "\n".join(lines)


def report_summary(rep: VerifyReport) -> str:
    out = [f"passed={rep.passed} score={rep.score:.1f}"]
    if rep.metrics:
        out.append("metrics: " + ", ".join(f"{k}={v:.3g}" for k, v in rep.metrics.items()))
    order = {"error": 0, "warning": 1, "info": 2}
    for c in sorted(rep.checks, key=lambda c: order[c.severity]):
        loc = " ".join(x for x in (f"element={c.element_id}" if c.element_id else "",
                                    f"segment={c.segment_id}" if c.segment_id else "") if x)
        val = f" (value={c.value:.3g}, limit={c.limit:.3g})" if c.value is not None and c.limit is not None else ""
        out.append(f"- [{c.severity}] {c.id}: {c.message} {loc}{val}".rstrip())
    return "\n".join(out)


POLISH_MIN_S = 20.0
ERROR_OVERRUN_S = 25.0   # failing designs get this much extra time for repair   # only start a warnings-only polish round if this much budget is left


def _counts(rep: VerifyReport) -> tuple[int, int]:
    return (sum(c.severity == "error" for c in rep.checks), sum(c.severity == "warning" for c in rep.checks))


def _clean(rep: VerifyReport) -> bool:
    return rep.passed and not any(c.severity == "warning" for c in rep.checks)


async def autofix_step(design: Design, tr: TraceResult, rep: VerifyReport, tracker: AgentTracker | None,
                       agent_id: str, parent_seq: int | None
                       ) -> tuple[Design, TraceResult, VerifyReport, int | None, bool]:
    """Deterministic stray-beam termination (optics/autofix.py). Emits a `tool` "autofix" event and an
    "autofix" iteration when it changed something. Returns (design, trace, report, seq, improved)."""
    if _clean(rep) or not any(c.id == "stray_beam" for c in rep.checks):
        return design, tr, rep, parent_seq, False
    try:
        from optics.autofix import terminate_strays
    except Exception:  # noqa: BLE001
        return design, tr, rep, parent_seq, False
    t0 = time.perf_counter()
    try:
        fixed, changes = terminate_strays(design, tr)
    except Exception as e:  # noqa: BLE001
        log.warning("autofix crashed: %s", e)
        return design, tr, rep, parent_seq, False
    if not changes:
        if tracker:
            await tracker.tool(agent_id, "autofix", "autofix: no safe dump placement found for the stray beams",
                               (time.perf_counter() - t0) * 1e3)
        return design, tr, rep, parent_seq, False
    n_add = sum(c["op"] == "add" for c in changes)
    nt, nr = evaluate(fixed)
    if tracker:
        await tracker.tool(agent_id, "autofix",
                           f"autofix: added {n_add} beam dump{'s' if n_add != 1 else ''} → score {rep.score:.0f} → "
                           f"{nr.score:.0f}", (time.perf_counter() - t0) * 1e3)
    if rank_key(nr) < rank_key(rep):
        return design, tr, rep, parent_seq, False
    seq = parent_seq
    if tracker:
        seq = await tracker.iteration(agent_id, "autofix", fixed, nt, nr, parent_seq=parent_seq,
                                      rationale=f"Terminated {n_add} stray beam{'s' if n_add != 1 else ''} with "
                                                "auto-placed beam dumps (deterministic, no LLM).")
    return fixed, nt, nr, seq, True


class ChangeNote(BaseModel):
    element_id: str
    why: str = Field(description="short lab-notebook reason for changing / adding / removing this element")


class RepairResult(BaseModel):
    rationale: str = Field(description="one sentence: what was wrong and what you changed")
    notes: list[ChangeNote] = Field(default_factory=list)
    design: Design


async def repair_loop(
    design: Design, tr: TraceResult, rep: VerifyReport, *, goal: str, emit: Emit,
    rounds: int = 3, thinking: str = "low", index_base: int = 0, extra_context: list | None = None,
    deadline: float | None = None, tracker: AgentTracker | None = None, parent_seq: int | None = None,
    parent_agent: str | None = None,
) -> tuple[Design, TraceResult, VerifyReport]:
    """Repair until the design passes with no warnings, rounds run out, or the time budget is spent.
    Errors are always worth a round while before the deadline; warnings-only polish rounds start only with
    >= POLISH_MIN_S left and are cut off at the deadline (the passing design is kept).
    Each round is a console agent "repair-N" emitting an `iteration` whose parent is the design it repaired."""
    tracker = tracker or AgentTracker(emit, model=llm.MODEL)
    best = (design, tr, rep)
    best_seq = parent_seq
    history: list[str] = []
    next_idx = index_base
    for r in range(1, rounds + 1):
        d, t, rp = best
        if not _clean(rp):
            d, t, rp, best_seq, improved = await autofix_step(d, t, rp, tracker, parent_agent or "repair",
                                                              best_seq)
            if improved:
                best = (d, t, rp)
                next_idx += 1
                await emit({"type": "candidate", "index": next_idx - 1, "stage": "autofix", "round": r,
                            "design": dump(d), "report": dump(rp), "trace": dump(t)})
                await emit({"type": "status", "stage": "repair",
                            "message": f"autofix terminated stray beams: {headline(rp)}"})
        n_err, n_warn = _counts(rp)
        if rp.passed and n_warn == 0:
            break
        remaining = None if deadline is None else deadline - time.monotonic()
        polish = rp.passed
        # a failing design may overrun the budget by ERROR_OVERRUN_S; polishing a passing one may not
        if remaining is not None and (remaining <= -ERROR_OVERRUN_S or (polish and remaining < POLISH_MIN_S)):
            await emit({"type": "status", "stage": "repair", "message": "time budget reached, stopping repair"})
            break
        if polish:
            what = f"polishing {n_warn} warning{'s' if n_warn != 1 else ''} ({headline(rp)})"
            budget = 45.0 if remaining is None else remaining
        else:
            what = f"asking Gemini to fix {n_err} error{'s' if n_err != 1 else ''} ({headline(rp)})"
            budget = 45.0 if remaining is None else max(20.0, remaining + ERROR_OVERRUN_S)
        await emit({"type": "status", "stage": "repair", "message": f"repair round {r}: {what}"})
        msg = prompts.repair_prompt(goal, d, report_summary(rp), trace_summary(d, t), history)
        aid = f"repair-{r}"
        title = f"Repair {r} — " + ("polish warnings" if polish else f"fix {n_err} error{'s' if n_err != 1 else ''}")
        try:
            async with tracker.agent(aid, "repair", title, parent=parent_agent, thinking_level=thinking):
                t0 = time.monotonic()
                res = await asyncio.wait_for(
                    llm.generate_model(RepairResult, (extra_context or []) + [msg], system=prompts.system_prompt(),
                                       thinking=thinking, tag=f"repair{r}"), timeout=budget)
                log.info("repair round %d took %.1fs", r, time.monotonic() - t0)
                new = res.design
                if res.rationale:
                    await tracker.thought(aid, f"Rationale: {res.rationale}")
                nt, nr = await evaluate_tracked(new, tracker, aid)
                notes = {n.element_id: n.why for n in res.notes}
                seq = await tracker.iteration(aid, f"repair {r}", new, nt, nr, parent_seq=best_seq,
                                              notes=notes, rationale=res.rationale)
        except Exception as e:  # noqa: BLE001
            log.warning("repair round %d failed: %s", r, e)
            reason = "ran out of time" if isinstance(e, (asyncio.TimeoutError, TimeoutError)) else \
                (str(e) or type(e).__name__)[:200]
            await emit({"type": "status", "stage": "repair",
                        "message": f"repair round {r} {reason}; keeping the best design so far"})
            continue
        next_idx += 1
        await emit({"type": "candidate", "index": next_idx - 1, "stage": "repair", "round": r,
                    "design": dump(new), "report": dump(nr), "trace": dump(nt)})
        await emit({"type": "status", "stage": "verify",
                    "message": f"repair round {r}: {headline(nr)}"})
        history.append(f"round {r}: score {rp.score:.0f} -> {nr.score:.0f}; remaining problems: "
                       + "; ".join(c.message for c in nr.checks if c.severity != "info")[:600])
        if rank_key(nr) >= rank_key(rp):
            best = (new, nt, nr)
            best_seq = seq
        else:
            history[-1] += " -> REGRESSED, that attempt was discarded; repair the design shown instead, differently."
    return best


def finalize_event(design: Design, tr: TraceResult, rep: VerifyReport) -> dict:
    return {"type": "final", "design": dump(design), "report": dump(rep), "trace": dump(tr)}


def jdump(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"))
