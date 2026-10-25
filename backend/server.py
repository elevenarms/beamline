"""Beamline API server.  Run:  cd backend && uv run uvicorn server:app --reload --port 8000"""
from __future__ import annotations

import asyncio
import json
import time
import traceback
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from optics.ir import Design

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE / "examples"
WEB_DIST = HERE.parent / "web" / "dist"

app = FastAPI(title="Beamline")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class DesignBody(BaseModel):
    design: Design


class GoalBody(BaseModel):
    goal: str
    candidates: int = 4


def _trace_and_verify(design: Design) -> dict[str, Any]:
    # Imported lazily so the server boots while builders are still writing these modules.
    from optics.trace import trace
    from optics.verify import verify

    t = trace(design)
    return {"trace": t.model_dump(mode="json"), "report": verify(design, t).model_dump(mode="json")}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.get("/api/examples")
def list_examples() -> list[dict[str, str]]:
    out = []
    for p in sorted(EXAMPLES.glob("*.json")):
        try:
            out.append({"name": p.stem, "title": json.loads(p.read_text()).get("name", p.stem)})
        except ValueError:
            continue
    return out


@app.get("/api/examples/{name}")
def get_example(name: str) -> dict[str, Any]:
    path = (EXAMPLES / f"{name}.json").resolve()
    if path.parent != EXAMPLES.resolve() or not path.is_file():
        raise HTTPException(404, f"no example {name!r}")
    return Design.model_validate_json(path.read_text()).model_dump(mode="json")


@app.post("/api/trace")
def trace_endpoint(body: DesignBody) -> dict[str, Any]:
    t0 = time.perf_counter()
    result = _trace_and_verify(body.design)
    result["elapsed_ms"] = (time.perf_counter() - t0) * 1000
    return result


@app.post("/api/export/pyopticl")
def export_pyopticl(body: DesignBody) -> dict[str, str]:
    from optics.pyopticl_export import to_pyopticl

    return {"code": to_pyopticl(body.design)}


Emit = Callable[[dict[str, Any]], Awaitable[None]]


def _stream(run: Callable[[Emit], Awaitable[Any]]) -> EventSourceResponse:
    """Run an agent pipeline, forwarding its emitted events as SSE `data:` lines."""
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def emit(event: dict[str, Any]) -> None:
        await queue.put(event)

    async def runner() -> None:
        try:
            await run(emit)
        except Exception as e:
            traceback.print_exc()
            await queue.put({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            await queue.put(None)

    async def events():
        task = asyncio.create_task(runner())
        try:
            while (event := await queue.get()) is not None:
                yield {"data": json.dumps(_jsonable(event))}
        finally:
            task.cancel()

    return EventSourceResponse(events(), ping=10)


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


@app.post("/api/design")
async def design_endpoint(body: GoalBody) -> EventSourceResponse:
    from agents.design import design_from_goal

    return _stream(lambda emit: design_from_goal(body.goal, emit, candidates=max(1, min(body.candidates, 8))))


@app.post("/api/reproduce")
async def reproduce_endpoint(image: UploadFile = File(...), notes: str = Form("")) -> EventSourceResponse:
    from agents.reproduce import reproduce_from_image

    data = await image.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "image too large (max 20 MB)")
    mime = image.content_type or "image/png"
    return _stream(lambda emit: reproduce_from_image(data, mime, notes, emit))


# Serve the built web app (npm run build) from the same origin for the demo.
if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        target = (WEB_DIST / path).resolve()
        if path and target.is_file() and WEB_DIST.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(WEB_DIST / "index.html")
