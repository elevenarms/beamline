"""CLI for the agent pipelines.

  uv run python -m agents.cli design "AOM double-pass at 780 nm, fiber in fiber out" [-n 4] [-o out.json]
  uv run python -m agents.cli reproduce path/to/fig.png [--notes "..."] [-o out.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import mimetypes
import re
import time
from pathlib import Path

from . import llm


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "design"


async def _main() -> None:
    ap = argparse.ArgumentParser(prog="agents.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("design")
    d.add_argument("goal")
    d.add_argument("-n", "--candidates", type=int, default=4)
    d.add_argument("-r", "--repair-rounds", type=int, default=3)
    d.add_argument("-o", "--out")
    r = sub.add_parser("reproduce")
    r.add_argument("image")
    r.add_argument("--notes", default="")
    r.add_argument("-r", "--repair-rounds", type=int, default=3)
    r.add_argument("-o", "--out")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--events", help="also write all events as JSONL here")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("beamline").setLevel(logging.INFO)
    for noisy in ("httpx", "google_genai", "google_genai.models"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    t0 = time.monotonic()
    ev_f = open(args.events, "w") if args.events else None

    async def emit(ev: dict) -> None:
        dt = time.monotonic() - t0
        if ev_f:
            ev_f.write(json.dumps({"t": round(dt, 2), **ev}) + "\n")
            ev_f.flush()
        t = ev["type"]
        if t == "status":
            print(f"[{dt:6.1f}s] {ev['stage']:<7} {ev['message']}", flush=True)
        elif t in ("candidate", "final"):
            rep = ev["report"]
            errs = [c for c in rep["checks"] if c["severity"] == "error"]
            tag = f"candidate {ev['index']} ({ev.get('stage', '')})" if t == "candidate" else "FINAL"
            print(f"[{dt:6.1f}s] {tag}: '{ev['design']['name']}' score={rep['score']:.1f} "
                  f"passed={rep['passed']} errors={len(errs)} elements={len(ev['design']['elements'])}", flush=True)
            for c in errs[:6]:
                print(f"            - {c['id']}: {c['message'][:140]}")
        elif t == "extraction":
            g = ev["graph"]
            print(f"[{dt:6.1f}s] extraction: {len(g['components'])} components, {len(g['beams'])} beams, "
                  f"{len(g.get('parameters', []))} params", flush=True)
            for c in g["components"]:
                print(f"            {c['id']:<8} {c['type']:<18} {c.get('label', '')[:40]}")
        elif t == "agent":
            el = f" {ev['elapsed_ms'] / 1000:.1f}s" if ev.get("elapsed_ms") else ""
            print(f"[{dt:6.1f}s]   agent {ev['agent_id']:<12} {ev['state']:<9}{el} {ev['title'][:60] if ev['state'] == 'running' else ''}")
        elif t == "tool":
            print(f"[{dt:6.1f}s]   tool  {ev['agent_id']:<12} {ev['summary'][:120]}")
        elif t == "thought":
            print(f"[{dt:6.1f}s]   think {ev['agent_id']:<12} {ev['text'][:140]}")
        elif t == "llm_call":
            print(f"[{dt:6.1f}s]   llm   {ev['agent_id']:<12} {ev['latency_ms'] / 1000:.1f}s ttft={ev['ttft_ms']} "
                  f"in={ev['prompt_tokens']} out={ev['output_tokens']} think={ev['thought_tokens']} {ev['finish_reason']}")
        elif t == "iteration":
            print(f"[{dt:6.1f}s]   iter  #{ev['seq']} {ev['label']} (parent {ev['parent_seq']}) score={ev['report']['score']:.1f} "
                  f"{len(ev['diff'])} changes" + (f" — {ev['rationale'][:100]}" if ev.get("rationale") else ""))
            if ev["parent_seq"] is not None:
                for c in ev["diff"][:6]:
                    print(f"              {c['op']:<8} {c['element_id']:<10} {(c.get('note') or '')[:110]}")
        elif t == "match":
            sm = ev["summary"]
            print(f"[{dt:6.1f}s] match: {sm['matched']}/{sm['in_figure']} figure components matched")
            for row in ev["rows"]:
                print(f"            {row['status']:<8} {row['figure_type']:<18} {row['figure_label'][:28]:<28} -> {row['design_id']}")
        elif t == "error":
            print(f"[{dt:6.1f}s] ERROR {ev['message']}")

    if args.cmd == "design":
        from .design import design_from_goal
        design = await design_from_goal(args.goal, emit, candidates=args.candidates,
                                        repair_rounds=args.repair_rounds)
        out = args.out or f"design_{_slug(args.goal)}.json"
    else:
        from .reproduce import reproduce_from_image
        p = Path(args.image)
        mime = mimetypes.guess_type(p.name)[0] or "image/png"
        design = await reproduce_from_image(p.read_bytes(), mime, args.notes, emit,
                                            repair_rounds=args.repair_rounds)
        out = args.out or f"reproduce_{_slug(p.stem)}.json"
    Path(out).write_text(design.model_dump_json(indent=2))
    print(f"saved {out}  ({time.monotonic() - t0:.1f}s total)")
    print("LLM usage:", json.dumps(llm.usage_summary()))
    for rec in llm.CALL_LOG:
        print("   ", json.dumps(rec))
    if ev_f:
        ev_f.close()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
