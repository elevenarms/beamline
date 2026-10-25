import type { AgentEvent, Design, MatchRow } from "../types";
import { traceDesign } from "./tracer";
import { MOCK_EXAMPLES, rbAomFiber, srTwoColor } from "./designs";

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((res, rej) => {
    const t = setTimeout(res, ms);
    signal?.addEventListener("abort", () => { clearTimeout(t); rej(new DOMException("aborted", "AbortError")); });
  });

function pickBase(text: string): Design {
  const t = text.toLowerCase();
  if (/(461|689|sr|two.?color|dichroic)/.test(t)) return srTwoColor;
  if (/(mach|zehnder|interfer|532)/.test(t)) return MOCK_EXAMPLES[1].design;
  return rbAomFiber;
}

function variant(base: Design, i: number): Design {
  const d = structuredClone(base);
  d.name = `${base.name}_c${i + 1}`;
  const els = d.elements ?? [];
  // candidates differ in a few knobs; candidate 0 is the hand-tuned one
  if (i === 1) for (const e of els) if (e.type === "half_wave_plate") e.fast_axis_deg = (e.fast_axis_deg ?? 0) + 9;
  if (i === 2) for (const e of els) if (e.type === "lens") e.focal_length_mm = (e.focal_length_mm ?? 100) * 0.6;
  if (i === 3) for (const e of els) if (e.type === "iris") e.aperture_mm = 0.6;
  return d;
}

/** Offline stand-in for the Gemini design / reproduce SSE pipelines. */
export async function* mockAgentStream(kind: "design" | "reproduce", text: string, signal?: AbortSignal): AsyncGenerator<AgentEvent> {
  const base = pickBase(text);
  try {
    if (kind === "reproduce") {
      yield { type: "status", stage: "extract", message: "Reading figure: detecting components and beam paths" };
      await sleep(900, signal);
      yield {
        type: "extraction",
        graph: {
          components: (base.elements ?? []).map((e) => ({ id: e.id, type: e.type })),
          sources: base.sources.map((s) => ({ id: s.id, wavelength_nm: s.wavelength_nm })),
        },
      };
      await sleep(500, signal);
    }
    const emitMatch = kind === "reproduce";
    yield { type: "status", stage: "plan", message: "Planning beam paths, branch topology and component budget" };
    await sleep(800, signal);
    yield { type: "status", stage: "design", message: "Generating 4 candidate layouts" };
    await sleep(700, signal);
    let best: { d: Design; score: number; r: ReturnType<typeof traceDesign> } | null = null;
    for (let i = 0; i < 4; i++) {
      const d = variant(base, i);
      const r = traceDesign(d);
      yield { type: "status", stage: "verify", message: `Tracing candidate ${i + 1}: ${r.trace.segments.length} segments` };
      await sleep(450, signal);
      yield { type: "candidate", index: i, design: d, report: r.report, trace: r.trace };
      if (!best || r.report.score > best.score) best = { d, score: r.report.score, r };
      await sleep(350, signal);
    }
    if (emitMatch) {
      const rows: MatchRow[] = (best!.d.elements ?? []).map((e) => ({ figure_label: e.label || e.id, figure_type: e.type, design_id: e.id, status: "matched" as const }));
      rows.push({ figure_label: "λ/4 plate (fig. label QWP)", figure_type: "quarter_wave_plate", design_id: null, status: "missing" });
      const matched = rows.filter((r) => r.status === "matched").length;
      yield { type: "match", rows, summary: { matched, in_figure: rows.length } };
      await sleep(300, signal);
    }
    yield { type: "status", stage: "repair", message: "Best candidate passes; no repair needed" };
    await sleep(500, signal);
    yield { type: "status", stage: "done", message: `Selected candidate (score ${best!.score.toFixed(0)})` };
    yield { type: "final", design: best!.d, report: best!.r.report, trace: best!.r.trace };
  } catch (e) {
    if ((e as Error).name !== "AbortError") yield { type: "error", message: String(e) };
  }
}
