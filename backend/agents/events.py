"""Agent-console event helpers (see CONTRACT.md "Agent console events"). Stable, tiny API:

    tracker = AgentTracker(emit)
    async with tracker.agent("designer-2", "designer", "Designer 2 — U-shaped layout", parent="planner",
                             thinking_level="low"):
        await tracker.thought("designer-2", "placing the PBS first ...")
        await tracker.tool("designer-2", "verify", "verify: score 67, 1 error — ...", 0.4)
        seq = await tracker.iteration("designer-2", "candidate 2", design, trace, report)

Inside `agent(...)` the current (tracker, agent_id) is stored in a ContextVar, so llm.py can attribute
`llm_call` and streamed `thought` events to the right agent without extra plumbing.
"""
from __future__ import annotations

import contextvars
import time
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

Emit = Callable[[dict], Awaitable[None]]

# (tracker, agent_id) of the agent whose code is currently running in this task
CURRENT: contextvars.ContextVar[tuple["AgentTracker", str] | None] = contextvars.ContextVar(
    "beamline_current_agent", default=None)


def _dump(x: Any) -> Any:
    return x.model_dump(mode="json") if hasattr(x, "model_dump") else x


class AgentTracker:
    def __init__(self, emit: Emit, model: str | None = None):
        self.emit = emit
        self.model = model
        self._seq = 0
        self._designs: dict[int, Any] = {}   # seq -> Design, for diffs

    async def _agent_event(self, agent_id: str, role: str, state: str, title: str, parent: str | None,
                           thinking_level: str | None, elapsed_ms: float | None, message: str | None) -> None:
        await self.emit({"type": "agent", "agent_id": agent_id, "role": role, "state": state, "title": title,
                         "parent": parent, "model": self.model if thinking_level else None,
                         "thinking_level": thinking_level, "elapsed_ms": elapsed_ms, "message": message})

    async def queued(self, agent_id: str, role: str, title: str, parent: str | None = None,
                     thinking_level: str | None = None) -> None:
        await self._agent_event(agent_id, role, "queued", title, parent, thinking_level, None, None)

    @asynccontextmanager
    async def agent(self, agent_id: str, role: str, title: str, parent: str | None = None,
                    thinking_level: str | None = None, queued: bool = True):
        """Emit queued -> running -> done | error | cancelled around the body. Re-raises errors."""
        if queued:
            await self._agent_event(agent_id, role, "queued", title, parent, thinking_level, None, None)
        t0 = time.perf_counter()
        await self._agent_event(agent_id, role, "running", title, parent, thinking_level, None, None)
        token = CURRENT.set((self, agent_id))
        state, message = "done", None
        try:
            yield self
        except BaseException as e:  # noqa: BLE001 — includes CancelledError
            import asyncio
            if isinstance(e, asyncio.CancelledError):
                state, message = "cancelled", "stopped early: enough results from the other agents"
            elif isinstance(e, (asyncio.TimeoutError, TimeoutError)):
                state, message = "cancelled", "stopped: time budget reached (keeping the best design so far)"
            else:
                state, message = "error", (str(e) or type(e).__name__)[:300]
            raise
        finally:
            CURRENT.reset(token)
            try:
                await self._agent_event(agent_id, role, state, title, parent, thinking_level,
                                        round((time.perf_counter() - t0) * 1000, 1), message)
            except BaseException:  # noqa: BLE001 — never mask the original outcome
                pass

    async def thought(self, agent_id: str, text: str) -> None:
        text = text.strip()
        if text:
            await self.emit({"type": "thought", "agent_id": agent_id, "text": text[:400]})

    async def tool(self, agent_id: str, name: str, summary: str, elapsed_ms: float) -> None:
        await self.emit({"type": "tool", "agent_id": agent_id, "name": name, "summary": summary,
                         "elapsed_ms": round(elapsed_ms, 2)})

    async def iteration(self, agent_id: str, label: str, design, trace, report, parent_seq: int | None = None,
                        notes: dict[str, str] | None = None, rationale: str | None = None) -> int:
        """Emit one design iteration; returns its seq. `notes` maps element_id -> why (appended to that
        element's change notes); `rationale` is a one-line summary of the whole step."""
        from optics.diff import diff_designs
        self._seq += 1
        seq = self._seq
        parent = self._designs.get(parent_seq) if parent_seq is not None else None
        try:
            diff = diff_designs(parent, design)
        except Exception:  # noqa: BLE001
            diff = []
        if notes:
            for ch in diff:
                why = notes.get(ch.get("element_id"))
                if why:
                    ch["note"] = f"{ch['note']} — {why}" if ch.get("note") else why
        self._designs[seq] = design
        ev = {"type": "iteration", "agent_id": agent_id, "seq": seq, "label": label, "design": _dump(design),
              "trace": _dump(trace), "report": _dump(report), "parent_seq": parent_seq, "diff": diff}
        if rationale:
            ev["rationale"] = rationale
        await self.emit(ev)
        return seq


def current() -> tuple[AgentTracker, str] | None:
    return CURRENT.get()
