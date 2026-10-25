# Beamline — build contract

Hackathon project: Gemini (`gemini-4-argon`) agents design tabletop laser-optics setups from a goal
or reproduce them from a paper figure; a Python tracer simulates & verifies the beam line; a three.js
web app shows and edits the design live. Inspired by PyOpticL (../repos/PyOpticL, code-to-CAD optics).

**Source of truth:** the JSON design IR in `backend/optics/ir.py` (`Design`). Read that file's docstring
for units, frames, polarization basis and branch naming. Do not change the schema without the integrator.

## Layout

```
beamline/
  backend/                     Python 3.12+, uv project (pyproject.toml here)
    optics/ir.py               schemas (owned by integrator)
    optics/trace.py            trace(design: Design) -> TraceResult            [physics builder]
    optics/verify.py           verify(design, trace) -> VerifyReport           [physics builder]
    optics/pyopticl_export.py  to_pyopticl(design) -> str (Python source)     [examples builder]
    examples/*.json            hand-written Design fixtures                    [examples builder]
    agents/                    Gemini pipelines                                [agents builder]
      design.py   async design_from_goal(goal, emit) -> Design
      reproduce.py async reproduce_from_image(image_bytes, mime, notes, emit) -> Design
    server.py                  FastAPI app                                     [integrator]
    tests/                     pytest
  web/                         Vite + React + TypeScript + three.js (@react-three/fiber, drei) [web builder]
```

## HTTP API (server on :8000; web dev server proxies /api)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | /api/examples | – | `[{"name": str, "title": str}]` |
| GET | /api/examples/{name} | – | `Design` |
| POST | /api/trace | `{"design": Design}` | `{"trace": TraceResult, "report": VerifyReport}` (≤100 ms target) |
| POST | /api/design | `{"goal": str, "candidates": int=4}` | SSE stream of events (below) |
| POST | /api/reproduce | multipart: `image` file, `notes` str | SSE stream of events |
| POST | /api/export/pyopticl | `{"design": Design}` | `{"code": str}` |

SSE events (`data: <json>\n\n`), each `{"type": ..., ...}`:
- `{"type":"status","stage":"plan|design|verify|repair|extract|done","message":str}`
- `{"type":"candidate","index":int,"design":Design,"report":VerifyReport,"trace":TraceResult}`
- `{"type":"extraction","graph":{...}}` (reproduce only: what the vision step saw)
- `{"type":"final","design":Design,"report":VerifyReport,"trace":TraceResult}`
- `{"type":"error","message":str}`

`emit` callbacks in agents/ take one such event dict (async callable).

## Gemini usage rules
- Key: read `../gemini_key` (repo root `/Users/elevenarms/Code/argonhack/gemini_key`) or `$GEMINI_API_KEY`. Never print/log/commit it.
- Model `gemini-4-argon`. ALWAYS set `thinking_level` explicitly ("low"/"medium"/"high"; "minimal" is
  rejected) and `max_output_tokens` ≥ 16000 — default thinking can eat the whole budget (observed:
  597/600 tokens spent thinking). Output limit is 32768. Check finish_reason.
- Image input works (inline bytes). Use structured output (`response_mime_type="application/json"` +
  schema) for Design JSON.

## Agent console events (added 12:10)

All agent pipelines also emit these fine-grained events (in addition to status/candidate/final/...):

- `{"type":"agent","agent_id":str,"role":str,"state":"queued|running|done|error|cancelled","title":str,"parent":str|null,"model":str|null,"thinking_level":str|null,"elapsed_ms":float|null,"message":str|null}`
  One per state change of each sub-agent. `agent_id` is unique per run, e.g. "planner", "designer-2",
  "repair-1", "vision-3", "merge", "synth", "architect", "module:cooling_422", "verifier".
  `role` ∈ planner | designer | verifier | repair | vision | merge | synth | architect | module | matcher.
- `{"type":"llm_call","agent_id":str,"call_id":str,"model":str,"thinking_level":str,"prompt_tokens":int,"output_tokens":int,"thought_tokens":int,"latency_ms":float,"ttft_ms":float|null,"finish_reason":str}`
- `{"type":"thought","agent_id":str,"text":str}` — streamed thought-summary chunks (Gemini include_thoughts), trimmed to ≤400 chars per event.
- `{"type":"tool","agent_id":str,"name":"trace|verify|merge|match|scale","summary":str,"elapsed_ms":float}` — deterministic tool runs.
- `{"type":"iteration","agent_id":str,"seq":int,"label":str,"design":Design,"trace":TraceResult,"report":VerifyReport,"parent_seq":int|null,"diff":[Change]}`
  Every intermediate design (each candidate, each repair round, each merged module) in run order, so the UI can replay tuning.
  `Change` = `{"op":"add"|"remove"|"move"|"rotate"|"param"|"retarget","element_id":str,"field":str|null,"from":any,"to":any,"note":str|null}`
  computed deterministically by `optics/diff.py: diff_designs(a, b) -> list[Change]` (moves = distance_mm/at changes, rotate = angle/out_direction changes, param = other fields, retarget = beam changes).
