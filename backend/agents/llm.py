"""Shared async Gemini wrapper: JSON generation validated into Pydantic models.

- Model `gemini-4-argon`; thinking_level always explicit; max_output_tokens >= 16000.
- Structured output via `response_json_schema` (sanitized Pydantic JSON schema). If the API
  rejects the schema we fall back to plain JSON mode with the schema text in the prompt.
- Pydantic validation; on failure one retry that feeds the validation error back.
- Timing + token usage logged via the `beamline.llm` logger and kept in `CALL_LOG`.
The API key is read from $GEMINI_API_KEY or the repo-root `gemini_key` file and never logged.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

log = logging.getLogger("beamline.llm")

MODEL = os.environ.get("BEAMLINE_MODEL", "gemini-4-argon")
MAX_OUTPUT_TOKENS = 32768
KEY_FILE = Path(__file__).resolve().parents[3] / "gemini_key"

T = TypeVar("T", bound=BaseModel)

CALL_LOG: list[dict[str, Any]] = []   # per-call timing/usage records (no prompt text)
_client: genai.Client | None = None
_schema_rejected: set[str] = set()    # model names whose schema the API refused


class LLMError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text().strip()
    if not key:
        raise LLMError("no Gemini API key: set GEMINI_API_KEY or create the gemini_key file")
    return key


def client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=_api_key(),
                               http_options=types.HttpOptions(timeout=180_000))
    return _client


# ───────────────────────────── schema helpers ─────────────────────────────

def gemini_schema(model: type[BaseModel]) -> dict:
    """Pydantic JSON schema made friendlier for Gemini: tuples -> fixed-length arrays,
    drop titles/defaults noise, inline $refs."""
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return walk(copy.deepcopy(defs[name]))
            out = {}
            for k, v in node.items():
                if k == "properties" and isinstance(v, dict):
                    out[k] = {pk: walk(pv) for pk, pv in v.items()}  # property names are data
                    continue
                if k in ("title", "default") and not isinstance(v, (dict, list)):
                    continue
                if k == "prefixItems":
                    items = [walk(x) for x in v]
                    out["items"] = items[0]
                    out["minItems"] = out["maxItems"] = len(items)
                    continue
                out[k] = walk(v)
            # nested tuple ((a,b),(c,d)) handled recursively; drop "items": false leftovers
            if out.get("items") is False:
                out.pop("items")
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(raw)


def _extract_json(text: str) -> Any:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            return json.loads(text[s:e + 1])
        raise


# ───────────────────────────── core calls ─────────────────────────────

_HEADER = re.compile(r"^\s*(#{1,6}\s+.*|\*\*[^*\n]{1,120}\*\*\s*)$", re.M)
_call_counter = 0
STREAM = os.environ.get("BEAMLINE_STREAM", "1") != "0"


class _ThoughtBatcher:
    """Collects streamed thought-summary text and forwards ~250-400 char chunks as `thought` events."""

    def __init__(self, cur):
        self.cur = cur
        self.buf = ""

    @staticmethod
    def clean(text: str) -> str:
        text = _HEADER.sub("", text)
        text = text.replace("**", "")
        return re.sub(r"\s+", " ", text)

    async def add(self, text: str) -> None:
        if self.cur is None:
            return
        self.buf += self.clean(text)
        while len(self.buf) >= 250:
            cut = -1
            for m in re.finditer(r"[.!?;:]\s", self.buf[:400]):
                if m.end() >= 200:
                    cut = m.end()
            if cut < 0:
                cut = self.buf.rfind(" ", 0, 400)
                cut = cut if cut > 150 else min(len(self.buf), 400)
            chunk, self.buf = self.buf[:cut], self.buf[cut:]
            await self._send(chunk)

    async def flush(self) -> None:
        if self.cur is not None and self.buf.strip():
            await self._send(self.buf)
        self.buf = ""

    async def _send(self, chunk: str) -> None:
        tracker, agent_id = self.cur
        try:
            await tracker.thought(agent_id, chunk)
        except Exception:  # noqa: BLE001
            pass


async def _emit_call(cur, rec: dict, call_id: str) -> None:
    if cur is None:
        return
    tracker, agent_id = cur
    try:
        await tracker.emit({
            "type": "llm_call", "agent_id": agent_id, "call_id": call_id, "model": MODEL,
            "thinking_level": rec.get("thinking"), "prompt_tokens": rec.get("prompt_tokens") or 0,
            "output_tokens": rec.get("output_tokens") or 0, "thought_tokens": rec.get("thought_tokens") or 0,
            "latency_ms": round(rec.get("latency_s", 0) * 1000, 1),
            "ttft_ms": rec.get("ttft_ms"), "finish_reason": rec.get("finish") or ("ERROR" if not rec.get("ok") else ""),
        })
    except Exception:  # noqa: BLE001
        pass


_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
TOKENS_FLUSH_S = float(os.environ.get("BEAMLINE_TOKENS_FLUSH_S", "0.12"))
TOKENS_FLUSH_CHARS = int(os.environ.get("BEAMLINE_TOKENS_FLUSH_CHARS", "160"))


class _TokenStreamer:
    """Forwards raw streamed text as `tokens` events, batched per call (every ~120 ms or 160 chars)."""

    def __init__(self, cur, call_id: str):
        self.cur, self.call_id = cur, call_id
        self.buf = {"output": "", "thought": ""}
        self.chars = {"output": 0, "thought": 0}
        self.usage_tokens: int | None = None
        self.t_first: float | None = None
        self.last_flush = time.perf_counter()
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def start(self) -> None:
        if self.cur is not None:
            self._task = asyncio.create_task(self._ticker())

    async def _ticker(self) -> None:
        try:
            while True:
                await asyncio.sleep(TOKENS_FLUSH_S)
                if time.perf_counter() - self.last_flush >= TOKENS_FLUSH_S:
                    await self.flush()
        except asyncio.CancelledError:
            pass

    async def add(self, kind: str, text: str, usage_tokens: int | None) -> None:
        if self.cur is None:
            return
        if self.t_first is None:
            self.t_first = time.perf_counter()
        if usage_tokens:
            self.usage_tokens = usage_tokens
        text = _CTRL.sub("", text)
        self.buf[kind] += text
        self.chars[kind] += len(text)
        if len(self.buf[kind]) >= TOKENS_FLUSH_CHARS:
            await self.flush()

    def _n_tokens(self) -> int:
        return self.usage_tokens if self.usage_tokens else self.chars["output"] // 4

    async def flush(self) -> None:
        if self.cur is None:
            return
        async with self._lock:
            self.last_flush = time.perf_counter()
            for kind in ("thought", "output"):
                text = self.buf[kind]
                if not text:
                    continue
                self.buf[kind] = ""
                n = self._n_tokens()
                dt = (time.perf_counter() - self.t_first) if self.t_first else 0.0
                tps = round(n / dt, 1) if dt > 0.05 and n else None
                tracker, agent_id = self.cur
                try:
                    await tracker.emit({"type": "tokens", "agent_id": agent_id, "call_id": self.call_id,
                                        "kind": kind, "text": text, "n_tokens_so_far": n, "tps": tps})
                except Exception:  # noqa: BLE001
                    pass

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await self.flush()


async def _call_stream(cfg: dict, contents, cur, call_id: str = "") -> tuple[str, str, Any, float | None]:
    """Streaming call; forwards raw `tokens` deltas and cleaned `thought` summaries.
    Returns (text, finish, usage, ttft_s)."""
    t0 = time.perf_counter()
    ttft = None
    texts: list[str] = []
    finish, usage = "", None
    batcher = _ThoughtBatcher(cur)
    tokens = _TokenStreamer(cur, call_id)
    stream = await client().aio.models.generate_content_stream(
        model=MODEL, contents=contents, config=types.GenerateContentConfig(**cfg))
    tokens.start()
    try:
        async for chunk in stream:
            if ttft is None:
                ttft = time.perf_counter() - t0
            if chunk.usage_metadata is not None:
                usage = chunk.usage_metadata
            n_out = getattr(chunk.usage_metadata, "candidates_token_count", None) if chunk.usage_metadata else None
            cand = (chunk.candidates or [None])[0]
            if cand is None:
                continue
            if cand.finish_reason:
                finish = str(cand.finish_reason)
            for p in (cand.content.parts if cand.content and cand.content.parts else []):
                if not p.text:
                    continue
                if getattr(p, "thought", False):
                    await tokens.add("thought", p.text, n_out)
                    await batcher.add(p.text)
                else:
                    texts.append(p.text)
                    await tokens.add("output", p.text, n_out)
    finally:
        await tokens.close()
    await batcher.flush()
    return "".join(texts), finish, usage, ttft


async def _call_once(cfg: dict, contents) -> tuple[str, str, Any, float | None]:
    resp = await client().aio.models.generate_content(
        model=MODEL, contents=contents, config=types.GenerateContentConfig(**cfg))
    cand = (resp.candidates or [None])[0]
    text = ""
    if cand is not None and cand.content and cand.content.parts:
        text = "".join(p.text or "" for p in cand.content.parts if not getattr(p, "thought", False))
    return text, str(getattr(cand, "finish_reason", None) or ""), resp.usage_metadata, None


async def generate(
    contents: list[Any],
    *,
    system: str | None = None,
    thinking: str = "low",
    temperature: float | None = None,
    json_schema: dict | None = None,
    json_mode: bool = False,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
    tag: str = "call",
    retries: int = 2,
    stream: bool | None = None,
) -> str:
    """One model call (streaming with thought summaries by default); returns the non-thought text.
    Emits `llm_call` / `thought` console events for the current agent (see events.py). Retries transient
    errors; falls back to non-streaming if the streaming call fails non-transiently."""
    global _call_counter
    from .events import current
    if thinking not in ("low", "medium", "high"):
        raise ValueError("thinking must be low|medium|high")
    use_stream = STREAM if stream is None else stream
    cfg: dict[str, Any] = dict(
        max_output_tokens=max(16000, min(max_output_tokens, MAX_OUTPUT_TOKENS)),
        thinking_config=types.ThinkingConfig(thinking_level=thinking, include_thoughts=use_stream),
    )
    if system:
        cfg["system_instruction"] = system
    if temperature is not None:
        cfg["temperature"] = temperature
    if json_schema is not None or json_mode:
        cfg["response_mime_type"] = "application/json"
    if json_schema is not None:
        cfg["response_json_schema"] = json_schema
    cur = current()

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        _call_counter += 1
        call_id = f"{tag}-{_call_counter}"
        t0 = time.perf_counter()
        try:
            if use_stream:
                text, finish, u, ttft = await _call_stream(cfg, contents, cur, call_id)
            else:
                text, finish, u, ttft = await _call_once(cfg, contents)
        except Exception as e:  # noqa: BLE001
            dt = time.perf_counter() - t0
            msg = str(e)
            transient = any(s in msg for s in ("429", "500", "502", "503", "504", "UNAVAILABLE",
                                                 "RESOURCE_EXHAUSTED", "timed out", "Timeout"))
            rec = {"tag": tag, "ok": False, "latency_s": round(dt, 2), "thinking": thinking,
                   "stream": use_stream, "error": msg[:300]}
            CALL_LOG.append(rec)
            await _emit_call(cur, rec, call_id)
            log.warning("llm %s failed after %.1fs: %s", tag, dt, msg[:300])
            last_err = e
            if json_schema is not None and ("schema" in msg.lower() or "400" in msg) and not transient:
                raise _SchemaRejected(msg) from e
            if use_stream and not transient:
                log.warning("llm %s: streaming failed, falling back to non-streaming", tag)
                use_stream = False
                cfg["thinking_config"] = types.ThinkingConfig(thinking_level=thinking)
                continue
            if not transient or attempt == retries:
                raise LLMError(f"{tag}: {msg[:500]}") from e
            await asyncio.sleep(2 * (attempt + 1))
            continue
        dt = time.perf_counter() - t0
        finish = finish.replace("FinishReason.", "")
        rec = {
            "tag": tag, "ok": True, "latency_s": round(dt, 2), "thinking": thinking, "stream": use_stream,
            "ttft_ms": None if ttft is None else round(ttft * 1000, 1),
            "finish": finish,
            "prompt_tokens": getattr(u, "prompt_token_count", None),
            "output_tokens": getattr(u, "candidates_token_count", None),
            "thought_tokens": getattr(u, "thoughts_token_count", None),
        }
        CALL_LOG.append(rec)
        await _emit_call(cur, rec, call_id)
        log.info("llm %s %.1fs ttft=%s finish=%s in=%s out=%s think=%s", tag, dt, rec["ttft_ms"], finish,
                 rec["prompt_tokens"], rec["output_tokens"], rec["thought_tokens"])
        if "MAX_TOKENS" in finish:
            raise LLMError(f"{tag}: hit max_output_tokens (thought={rec['thought_tokens']})")
        if finish and "STOP" not in finish:
            last_err = LLMError(f"{tag}: finish_reason={finish}")
            if attempt == retries:
                raise last_err
            continue
        if not text.strip():
            last_err = LLMError(f"{tag}: empty response")
            if attempt == retries:
                raise last_err
            continue
        return text
    raise LLMError(f"{tag}: {last_err}")


class _SchemaRejected(LLMError):
    pass


async def generate_model(
    model: type[T],
    contents: list[Any],
    *,
    system: str | None = None,
    thinking: str = "low",
    temperature: float | None = None,
    tag: str = "json",
    use_schema: bool = True,
) -> T:
    """Generate JSON validated into `model`. One corrective retry on validation failure."""
    schema = gemini_schema(model)
    key = model.__name__
    mode_schema = use_schema and key not in _schema_rejected
    schema_note = ("\n\nReturn ONLY a JSON object matching this JSON schema:\n"
                   + json.dumps(schema, separators=(",", ":")))
    contents = [_to_content(contents)]
    if not mode_schema:
        contents[0].parts.append(types.Part.from_text(text=schema_note))

    for attempt in range(2):
        try:
            text = await generate(contents, system=system, thinking=thinking, temperature=temperature,
                                  json_schema=schema if mode_schema else None, json_mode=True,
                                  tag=f"{tag}#{attempt}")
        except _SchemaRejected as e:
            log.warning("schema for %s rejected by API, falling back to prompt schema: %s", key, str(e)[:200])
            _schema_rejected.add(key)
            mode_schema = False
            contents[0].parts.append(types.Part.from_text(text=schema_note))
            text = await generate(contents, system=system, thinking=thinking, temperature=temperature,
                                  json_mode=True, tag=f"{tag}#{attempt}-noschema")
        try:
            return model.model_validate(_extract_json(text))
        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            if attempt == 1:
                raise LLMError(f"{tag}: invalid {key} JSON after retry: {str(e)[:600]}") from e
            log.info("%s: validation failed, retrying with error feedback", tag)
            contents = contents + [
                types.Content(role="model", parts=[types.Part.from_text(text=text[:60000])]),
                types.Content(role="user", parts=[types.Part.from_text(
                    text=f"That JSON failed validation:\n{str(e)[:3000]}\n"
                         f"Return the complete corrected JSON object only.")]),
            ]
    raise LLMError("unreachable")


def _to_content(items: list[Any]) -> types.Content:
    parts = []
    for it in items:
        if isinstance(it, str):
            parts.append(types.Part.from_text(text=it))
        elif isinstance(it, types.Part):
            parts.append(it)
        else:
            raise TypeError(f"unsupported content item {type(it)}")
    return types.Content(role="user", parts=parts)


def image_part(data: bytes, mime: str) -> types.Part:
    return types.Part.from_bytes(data=data, mime_type=mime)


def usage_summary(records: list[dict] | None = None) -> dict:
    recs = CALL_LOG if records is None else records
    ok = [r for r in recs if r.get("ok")]
    return {
        "calls": len(recs), "ok": len(ok),
        "prompt_tokens": sum(r.get("prompt_tokens") or 0 for r in ok),
        "output_tokens": sum(r.get("output_tokens") or 0 for r in ok),
        "thought_tokens": sum(r.get("thought_tokens") or 0 for r in ok),
    }
