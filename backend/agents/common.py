"""Shared helpers for the agent pipelines: safe trace+verify, trace summaries for repair
prompts, event serialisation, and the verify→repair loop."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from optics.ir import Check, Design, TraceResult, VerifyReport

from . import llm, prompts

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


POLISH_MIN_S = 20.0   # only start a warnings-only polish round if this much budget is left


def _counts(rep: VerifyReport) -> tuple[int, int]:
    return (sum(c.severity == "error" for c in rep.checks), sum(c.severity == "warning" for c in rep.checks))


async def repair_loop(
    design: Design, tr: TraceResult, rep: VerifyReport, *, goal: str, emit: Emit,
    rounds: int = 3, thinking: str = "low", index_base: int = 0, extra_context: list | None = None,
    deadline: float | None = None,
) -> tuple[Design, TraceResult, VerifyReport]:
    """Repair until the design passes with no warnings, rounds run out, or the time budget is spent.
    Errors are always worth a round while before the deadline; warnings-only polish rounds start only with
    >= POLISH_MIN_S left and are cut off at the deadline (the passing design is kept)."""
    best = (design, tr, rep)
    history: list[str] = []
    for r in range(1, rounds + 1):
        d, t, rp = best
        n_err, n_warn = _counts(rp)
        if rp.passed and n_warn == 0:
            break
        remaining = None if deadline is None else deadline - time.monotonic()
        polish = rp.passed
        if remaining is not None and (remaining <= 0 or (polish and remaining < POLISH_MIN_S)):
            await emit({"type": "status", "stage": "repair", "message": "time budget reached, stopping repair"})
            break
        if polish:
            what = f"polishing {n_warn} warning{'s' if n_warn != 1 else ''} ({headline(rp)})"
            budget = 45.0 if remaining is None else remaining
        else:
            what = f"asking Gemini to fix {n_err} error{'s' if n_err != 1 else ''} ({headline(rp)})"
            budget = 45.0 if remaining is None else max(20.0, remaining + 15.0)
        await emit({"type": "status", "stage": "repair", "message": f"repair round {r}: {what}"})
        msg = prompts.repair_prompt(goal, d, report_summary(rp), trace_summary(d, t), history)
        try:
            t0 = time.monotonic()
            new = await asyncio.wait_for(
                llm.generate_model(Design, (extra_context or []) + [msg], system=prompts.system_prompt(),
                                   thinking=thinking, tag=f"repair{r}"), timeout=budget)
            log.info("repair round %d took %.1fs", r, time.monotonic() - t0)
        except Exception as e:  # noqa: BLE001
            log.warning("repair round %d failed: %s", r, e)
            reason = "ran out of time" if isinstance(e, (asyncio.TimeoutError, TimeoutError)) else \
                (str(e) or type(e).__name__)[:200]
            await emit({"type": "status", "stage": "repair",
                        "message": f"repair round {r} {reason}; keeping the best design so far"})
            continue
        nt, nr = evaluate(new)
        await emit({"type": "candidate", "index": index_base + r - 1, "stage": "repair", "round": r,
                    "design": dump(new), "report": dump(nr), "trace": dump(nt)})
        await emit({"type": "status", "stage": "verify",
                    "message": f"repair round {r}: {headline(nr)}"})
        history.append(f"round {r}: score {rp.score:.0f} -> {nr.score:.0f}; remaining problems: "
                       + "; ".join(c.message for c in nr.checks if c.severity != "info")[:600])
        if rank_key(nr) >= rank_key(rp):
            best = (new, nt, nr)
        else:
            history[-1] += " -> REGRESSED, that attempt was discarded; repair the design shown instead, differently."
    return best


def finalize_event(design: Design, tr: TraceResult, rep: VerifyReport) -> dict:
    return {"type": "final", "design": dump(design), "report": dump(rep), "trace": dump(tr)}


def jdump(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"))
