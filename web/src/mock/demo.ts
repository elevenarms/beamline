import type { AgentEvent, Design, Element, Paper } from "../types";
import { traceDesign } from "./tracer";
import { mockAgentStream } from "./agent";
import { rbAomFiber } from "./designs";

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((res, rej) => {
    const t = setTimeout(res, ms);
    signal?.addEventListener("abort", () => { clearTimeout(t); rej(new DOMException("aborted", "AbortError")); });
  });

interface CatalogEntry { slug: string; title: string; citation: string; url: string; license: string; notes_for_reproduce?: string; design_goal?: string }

/** Offline paper search over the bundled, licensed figure catalog (demo/figures/catalog.json). */
export async function mockSearchPapers(q: string): Promise<Paper[]> {
  let cat: CatalogEntry[] = [];
  try { cat = await (await fetch("/demo/figures/catalog.json")).json(); } catch { /* offline */ }
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
  const score = (e: CatalogEntry) => terms.reduce((a, t) => a + (`${e.title} ${e.notes_for_reproduce ?? ""}`.toLowerCase().includes(t) ? 1 : 0), 0);
  return cat
    .map((e) => ({ e, s: score(e) }))
    .sort((a, b) => b.s - a.s)
    .map(({ e, s }) => ({
      arxiv_id: e.slug,
      title: e.title,
      authors: [e.citation],
      year: null,
      abs_url: e.url,
      license: e.license,
      figures: [{ id: e.slug, url: `/demo/figures/${e.slug}.png`, caption: e.notes_for_reproduce ?? e.title, setup_score: 0.5 + 0.1 * s }],
    }));
}

/** figure → extraction (with box_2d from the design's own layout) → the mock design pipeline */
export async function* mockReproduceUrl(imageUrl: string, notes: string, citation: string, signal?: AbortSignal): AsyncGenerator<AgentEvent> {
  yield { type: "figure", url: imageUrl, citation };
  yield { type: "status", stage: "extract", message: `fetched figure (${citation.slice(0, 60)})` };
  await sleep(900, signal);
  const d = rbAomFiber;
  const t = traceDesign(d).trace;
  const bp = d.baseplate!;
  const comps = t.elements.filter((e) => e.position).map((e) => {
    const [x, y] = e.position!;
    const cx = (x / bp.width_mm) * 1000, cy = 1000 - (y / bp.height_mm) * 1000;
    return { id: e.id, type: e.type, label: d.elements?.find((x) => x.id === e.id)?.label ?? e.id, box_2d: [cy - 45, cx - 30, cy + 45, cx + 30] };
  });
  yield { type: "extraction", graph: { components: comps, beams: t.segments.map((s) => ({ id: s.id })) } };
  await sleep(700, signal);
  yield* mockAgentStream("design", notes || "rb aom fiber", signal);
}

/** client-side detune: tilt fold mirrors and shift couplers so the tuner has something to recover */
export function mockDetune(d: Design): Design {
  const r = structuredClone(d);
  let n = 0;
  for (const e of r.elements ?? []) {
    if (n >= 3) break;
    if (e.type === "mirror") {
      if (e.out_direction_deg != null) e.out_direction_deg = +(e.out_direction_deg + (n % 2 ? -1.2 : 1.4)).toFixed(2);
      else if (e.angle_deg != null) e.angle_deg = +(e.angle_deg + 0.7).toFixed(2);
      else continue;
      n++;
    }
  }
  return r;
}

const objective = (d: Design) => traceDesign(d).report.metrics.delivered_mw ?? 0;

/** deterministic coordinate-descent style tune pass computed with the in-browser tracer */
export async function* mockTune(design: Design, reference?: Design, signal?: AbortSignal): AsyncGenerator<AgentEvent> {
  let cur = structuredClone(design);
  const knobs: { id: string; field: keyof Element; target: number }[] = [];
  for (const e of cur.elements ?? []) {
    const ref = reference?.elements?.find((x) => x.id === e.id);
    for (const f of ["out_direction_deg", "angle_deg", "distance_mm"] as (keyof Element)[]) {
      const v = e[f] as number | null | undefined, rv = ref?.[f] as number | null | undefined;
      if (v != null && rv != null && Math.abs(v - rv) > 1e-6) knobs.push({ id: e.id, field: f, target: rv });
    }
  }
  if (!knobs.length) {
    const m = cur.elements?.find((e) => e.type === "mirror" && e.out_direction_deg != null);
    if (m) knobs.push({ id: m.id, field: "out_direction_deg", target: m.out_direction_deg! });
  }
  const tr0 = traceDesign(cur);
  yield { type: "tune_start", order: knobs.map((k) => k.id), objective: "delivered_mw", baseline: { objective: tr0.report.metrics.delivered_mw ?? 0, delivered_mw: tr0.report.metrics.delivered_mw ?? 0, score: tr0.report.score } };
  let best = objective(cur);
  for (const k of knobs) {
    const el = cur.elements!.find((e) => e.id === k.id)!;
    const from = el[k.field] as number;
    const before = best;
    const span = k.target - from;
    // sweep past the optimum and back, like a hand on a kinematic knob
    const vals = [0.2, 0.45, 0.7, 0.9, 1.08, 1.0].map((f) => +(from + span * f).toFixed(3));
    let bestV = from;
    for (const v of vals) {
      const trial = structuredClone(cur);
      (trial.elements!.find((e) => e.id === k.id)! as unknown as Record<string, unknown>)[k.field] = v;
      const r = traceDesign(trial);
      const obj = r.report.metrics.delivered_mw ?? 0;
      const better = obj >= best - 1e-9;
      if (better) { best = obj; bestV = v; }
      const fc = r.trace.elements.find((e) => e.type === "fiber_coupler" && e.coupling_efficiency != null);
      yield { type: "tune_step", element_id: k.id, field: k.field, value: v, objective: obj, metrics: { delivered_mw: obj, coupling: fc?.coupling_efficiency ?? null, score: r.report.score }, best_so_far: better, patch: { [k.field]: v } };
      await sleep(10, signal);
    }
    (cur.elements!.find((e) => e.id === k.id)! as unknown as Record<string, unknown>)[k.field] = bestV;
    yield { type: "tune_done", element_id: k.id, field: k.field, from, to: bestV, gain: before > 0 ? (best - before) / before : best > 0 ? 1 : 0 };
  }
  const fin = traceDesign(cur);
  yield { type: "final", design: cur, trace: fin.trace, report: fin.report, summary: { objective_before: tr0.report.metrics.delivered_mw ?? 0, objective_after: fin.report.metrics.delivered_mw ?? 0, steps: knobs.length * 6 } };
}
