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
                               http_options=types.HttpOptions(timeout=240_000))
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
                if k in ("title", "default"):
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
) -> str:
    """One generate_content call; returns the non-thought text. Retries transient errors."""
    if thinking not in ("low", "medium", "high"):
        raise ValueError("thinking must be low|medium|high")
    cfg: dict[str, Any] = dict(
        max_output_tokens=max(16000, min(max_output_tokens, MAX_OUTPUT_TOKENS)),
        thinking_config=types.ThinkingConfig(thinking_level=thinking),
    )
    if system:
        cfg["system_instruction"] = system
    if temperature is not None:
        cfg["temperature"] = temperature
    if json_schema is not None or json_mode:
        cfg["response_mime_type"] = "application/json"
    if json_schema is not None:
        cfg["response_json_schema"] = json_schema

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        try:
            resp = await client().aio.models.generate_content(
                model=MODEL, contents=contents, config=types.GenerateContentConfig(**cfg))
        except Exception as e:  # noqa: BLE001
            dt = time.perf_counter() - t0
            msg = str(e)
            transient = any(s in msg for s in ("429", "500", "502", "503", "504", "UNAVAILABLE",
                                                 "RESOURCE_EXHAUSTED", "timed out", "Timeout"))
            rec = {"tag": tag, "ok": False, "latency_s": round(dt, 2), "error": msg[:300]}
            CALL_LOG.append(rec)
            log.warning("llm %s failed after %.1fs: %s", tag, dt, msg[:300])
            last_err = e
            if json_schema is not None and ("schema" in msg.lower() or "400" in msg) and not transient:
                raise _SchemaRejected(msg) from e
            if not transient or attempt == retries:
                raise LLMError(f"{tag}: {msg[:500]}") from e
            await asyncio.sleep(2 * (attempt + 1))
            continue
        dt = time.perf_counter() - t0
        cand = (resp.candidates or [None])[0]
        finish = str(getattr(cand, "finish_reason", None) or "")
        u = resp.usage_metadata
        rec = {
            "tag": tag, "ok": True, "latency_s": round(dt, 2), "thinking": thinking,
            "finish": finish.replace("FinishReason.", ""),
            "prompt_tokens": getattr(u, "prompt_token_count", None),
            "output_tokens": getattr(u, "candidates_token_count", None),
            "thought_tokens": getattr(u, "thoughts_token_count", None),
        }
        CALL_LOG.append(rec)
        log.info("llm %s %.1fs finish=%s in=%s out=%s think=%s", tag, dt, rec["finish"],
                 rec["prompt_tokens"], rec["output_tokens"], rec["thought_tokens"])
        text = ""
        if cand is not None and cand.content and cand.content.parts:
            text = "".join(p.text or "" for p in cand.content.parts if not getattr(p, "thought", False))
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
