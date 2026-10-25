"""Beamline API server.  Run:  cd backend && uv run uvicorn server:app --reload --port 8000"""
from __future__ import annotations

import asyncio
import json
import time
import traceback
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

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

from agents.cover import router as cover_router  # noqa: E402  (Nano Banana cover renders)

app.include_router(cover_router)
from agents.paper_pdf import router as paper_pdf_router  # noqa: E402  (arXiv PDF proxy)

app.include_router(paper_pdf_router)
from optics.build_doc_api import router as build_doc_router  # noqa: E402  (build document PDF)

app.include_router(build_doc_router)


class DesignBody(BaseModel):
    design: Design


class GoalBody(BaseModel):
    goal: str
    candidates: int = 4
    # "single": one design pass; "hierarchical": architect splits into modules designed in parallel;
    # "auto": hierarchical when the goal reads like a multi-subsystem apparatus.
    mode: Literal["auto", "single", "hierarchical"] = "auto"


_BIG_HINTS = ("apparatus", "full laser system", "quantum computer", "subsystems", "entire", "complete system",
              "whole table", "multiple lasers", "cooling, repump", "laboratory setup")


def _wants_hierarchical(body: GoalBody) -> bool:
    if body.mode != "auto":
        return body.mode == "hierarchical"
    goal = body.goal.lower()
    return any(h in goal for h in _BIG_HINTS) or goal.count(",") >= 4


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
    if _wants_hierarchical(body):
        from agents.hierarchical import design_hierarchical

        return _stream(lambda emit: design_hierarchical(body.goal, emit))
    from agents.design import design_from_goal

    return _stream(lambda emit: design_from_goal(body.goal, emit, candidates=max(1, min(body.candidates, 8))))


@app.post("/api/reproduce")
async def reproduce_endpoint(image: UploadFile = File(...), notes: str = Form("")) -> EventSourceResponse:
    from agents.reproduce import reproduce_from_image

    data = await image.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "image too large (max 20 MB)")
    mime = image.content_type or "image/png"
    t_req = time.monotonic()
    return _stream(lambda emit: reproduce_from_image(data, mime, notes, emit, started_at=t_req))


class ReproduceUrlBody(BaseModel):
    image_url: str
    notes: str = ""
    citation: str = ""


@app.get("/api/papers/search")
async def papers_search(q: str, limit: int = 6) -> list[dict[str, Any]]:
    from agents.papers import search_papers

    if not q.strip():
        raise HTTPException(400, "empty query")
    try:
        return await search_papers(q, limit)
    except Exception as e:  # arXiv down / rate limited
        raise HTTPException(502, f"paper search failed: {type(e).__name__}: {e}") from e


@app.post("/api/reproduce_url")
async def reproduce_url_endpoint(body: ReproduceUrlBody) -> EventSourceResponse:
    from urllib.parse import urlparse

    from agents.papers import ALLOWED_HOSTS, fetch_image
    from agents.reproduce import reproduce_from_image

    t_req = time.monotonic()
    u = urlparse(body.image_url)
    if u.scheme != "https" or (u.hostname or "").lower() not in ALLOWED_HOSTS:
        raise HTTPException(400, f"image_url must be https on one of: {', '.join(sorted(ALLOWED_HOSTS))}")

    async def run(emit: Emit) -> Any:
        await emit({"type": "figure", "url": body.image_url, "citation": body.citation})
        data, mime = await fetch_image(body.image_url)
        await emit({"type": "status", "stage": "budget", "message": f"figure fetched ({len(data) // 1024} kB)",
                    "elapsed_s": round(time.monotonic() - t_req, 1), "deadline_s": 115})
        return await reproduce_from_image(data, mime, body.notes, emit, started_at=t_req)

    return _stream(run)


# ── alignment / tuning (optics/tune.py) ──
class TuneBody(BaseModel):
    design: Design
    objective: str = "auto"
    pace_ms: float = 0.0


class DetuneBody(BaseModel):
    design: Design
    seed: int = 0


@app.post("/api/tune")
async def tune_endpoint(body: TuneBody) -> EventSourceResponse:
    from optics.tune import tune

    return _stream(lambda emit: tune(body.design, emit, objective=body.objective, pace_ms=body.pace_ms))


@app.post("/api/detune")
def detune_endpoint(body: DetuneBody) -> dict[str, Any]:
    from optics.tune import detune

    d = detune(body.design, body.seed)
    return {"design": d.model_dump(mode="json"), **_trace_and_verify(d)}


# ── build kit: BOM + printable baseplate (optics/bom.py) ──
@app.post("/api/bom")
def bom_endpoint(body: DesignBody) -> dict[str, Any]:
    from optics.bom import build_kit, design_hash

    bom, _ = build_kit(body.design)
    token = design_hash(body.design)
    return {**bom, "token": token,
            "stl_urls": {p["name"]: f"/api/stl/{token}/{p['name']}.stl" for p in bom["printed"]}}


@app.post("/api/build_kit")
def build_kit_endpoint(body: DesignBody):
    from fastapi.responses import Response

    from optics.bom import kit_zip

    data = kit_zip(body.design)
    fname = "".join(c if c.isalnum() or c in "-_" else "_" for c in body.design.name) or "design"
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{fname}_kit.zip"'})


@app.get("/api/stl/{token}/{name}.stl")
def stl_endpoint(token: str, name: str):
    from optics.bom import KIT_ROOT

    if not token.isalnum() or not all(c.isalnum() or c in "-_" for c in name):
        raise HTTPException(400, "bad path")
    path = KIT_ROOT / token / "stl" / f"{name}.stl"
    if not path.is_file():
        raise HTTPException(404, "unknown kit/part (POST /api/bom first)")
    return FileResponse(path, media_type="model/stl", filename=f"{name}.stl")


# Serve the built web app (npm run build) from the same origin for the demo.
if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        target = (WEB_DIST / path).resolve()
        if path and target.is_file() and WEB_DIST.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(WEB_DIST / "index.html")
