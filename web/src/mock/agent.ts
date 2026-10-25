import type { AgentEvent, Design, MatchRow } from "../types";
import { traceDesign } from "./tracer";
import { diffDesigns } from "../lib/diff";
import { MOCK_EXAMPLES, bigApparatusModules, mergeDesigns, rbAomFiber, srTwoColor } from "./designs";

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
async function* hierarchical(signal?: AbortSignal): AsyncGenerator<AgentEvent> {
  const parts = bigApparatusModules();
  const full = mergeDesigns("mock_big_apparatus", parts);
  yield ag("architect", "architect", "running", "Architect", null, { thinking_level: "high" });
  yield { type: "status", stage: "plan", message: "Decomposing apparatus into subsystems" };
  yield th("architect", "Twelve breadboard modules: four 780 nm AOM/fiber stations, four interferometers, four two-colour combiners; fiber-link the combiners to the AOM stations.");
  await sleep(900, signal);
  yield llm("architect", 3900, 2600, 5100, 14200, "high");
  const mods = full.modules ?? [];
  const links = mods.filter((_, i) => i % 3 === 0 && mods[i + 2]).map((m, i) => ({ from_module: m.id, to_module: mods[i * 3 + 2].id, purpose: "780 nm reference" }));
  yield { type: "modules", modules: mods, table: full.baseplate, links, title: "Synthetic 12-module apparatus" };
  for (const m of mods) yield ag(`module:${m.id}`, "module", "queued", m.title ?? m.id, "architect");
  yield ag("architect", "architect", "done", "Architect", null, { elapsed_ms: 15800, thinking_level: "high" });
  await sleep(500, signal);
  let acc: Design = { ...full, sources: [], elements: [], targets: [] };
  let seq = 0;
  for (const p of parts) {
    const m = p.modules![0];
    const id = `module:${m.id}`;
    yield ag(id, "module", "running", m.title ?? m.id, "architect");
    yield { type: "status", stage: "design", message: `Designing ${m.title}`, module_id: m.id } as AgentEvent;
    await sleep(160, signal);
    yield llm(id, 4800, 2400, 3600, 18000);
    const r = traceDesign({ ...p, baseplate: full.baseplate });
    yield tool(id, "verify", verifySummary(r), 3);
    yield { type: "module_done", module_id: m.id, design: p, report: r.report, trace: r.trace };
    acc = { ...acc, sources: [...acc.sources, ...p.sources], elements: [...(acc.elements ?? []), ...(p.elements ?? [])], targets: [...(acc.targets ?? []), ...(p.targets ?? [])] };
    const ra = traceDesign(acc);
    yield tool("merge", "merge", `${(acc.elements ?? []).length} elements  ${ra.trace.segments.length} segments`, 6);
    yield { type: "iteration", agent_id: "merge", seq: ++seq, label: `+${m.id}`, design: acc, trace: ra.trace, report: ra.report, parent_seq: seq > 1 ? seq - 1 : null, diff: [] };
    yield ag(id, "module", "done", m.title ?? m.id, "architect", { elapsed_ms: 18000 + seq * 700 });
    await sleep(160, signal);
  }
  yield { type: "status", stage: "verify", message: "Global verification across modules" };
  await sleep(600, signal);
  const r = traceDesign(full);
  yield { type: "status", stage: "done", message: `Apparatus assembled: ${(full.elements ?? []).length} elements` };
  yield { type: "final", design: full, report: r.report, trace: r.trace };
}

const MODEL = "gemini-4-argon";
const ag = (agent_id: string, role: string, state: "queued" | "running" | "done" | "error", title: string, parent: string | null, extra: Partial<{ elapsed_ms: number; message: string; thinking_level: string }> = {}): AgentEvent =>
  ({ type: "agent", agent_id, role, state, title, parent, model: MODEL, thinking_level: extra.thinking_level ?? "medium", elapsed_ms: extra.elapsed_ms ?? null, message: extra.message ?? null });
let callN = 0;
const llm = (agent_id: string, pin: number, pout: number, pth: number, lat: number, level = "medium"): AgentEvent =>
  ({ type: "llm_call", agent_id, call_id: `c${++callN}`, model: MODEL, thinking_level: level, prompt_tokens: pin, output_tokens: pout, thought_tokens: pth, latency_ms: lat, ttft_ms: lat * 0.35, finish_reason: "STOP" });
const th = (agent_id: string, text: string): AgentEvent => ({ type: "thought", agent_id, text });
const tool = (agent_id: string, name: string, summary: string, ms: number): AgentEvent => ({ type: "tool", agent_id, name, summary, elapsed_ms: ms });
const firstErr = (r: ReturnType<typeof traceDesign>) => {
  const c = r.report.checks.find((x) => x.severity !== "info");
  return c ? `${c.id} ${c.value != null ? c.value.toFixed(2) : ""} ${c.element_id ?? c.segment_id ?? ""}`.trim() : "all checks ok";
};
const verifySummary = (r: ReturnType<typeof traceDesign>) => {
  const e = r.report.checks.filter((c) => c.severity === "error").length, w = r.report.checks.filter((c) => c.severity === "warning").length;
  return `score ${r.report.score.toFixed(0)}  ${e} err  ${w} warn  ${firstErr(r)}`;
};

/** best candidate → small, physically-motivated repairs so the tuning replay has visible moves */
function repairOf(d: Design, round: number): Design {
  const r = structuredClone(d);
  r.name = `${d.name.replace(/_c\d+$/, "")}_r${round}`;
  const els = r.elements ?? [];
  if (round === 1) {
    if (els.some((e) => e.beam === "L1.t.t" && e.type === "aom") && !els.some((e) => e.beam === "L1.t.t.0")) {
      els.push({ id: "BD3", type: "beam_dump", label: "0-order dump", beam: "L1.t.t.0", distance_mm: 120 });
    }
    for (const e of els) if (e.type === "iris" && e.distance_mm != null) e.distance_mm = e.distance_mm - 8;
  } else {
    for (const e of els) if (e.type === "half_wave_plate" && e.fast_axis_deg != null) e.fast_axis_deg = +(e.fast_axis_deg + 2.5).toFixed(2);
    const m = els.find((e) => e.type === "mirror" && e.distance_mm != null && e.beam !== "L1");
    if (m) m.distance_mm = m.distance_mm! + 12;
  }
  r.elements = els;
  return r;
}

// synthetic token deltas (JSON-ish design text + thought prose), interleaved across agents
const WORDS = ['{"id":"M1",', '"type":"mirror",', '"beam":"L1",', '"distance_mm":45,', '"out_direction_deg":90},', '{"id":"PBS1",', '"type":"pbs",', '"split_ratio":0.5},', '"focal_length_mm":150,', '"aom_frequency_mhz":110,', '"angle_deg":0,', '"label":"fold mirror",', '"targets":[', '{"element_id":"F1",', '"kind":"min_power_mw",', '"value":8}]'];
const PROSE = ["keep the fold before the PBS", "so the AOM arm stays long;", "check clipping at the iris", "w ≈ 0.36 mm at the AOM,", "aperture 2 mm is fine;", "dump the 0th order", "before it leaves the plate."];
async function* tokenBurst(ids: string[], ms: number, signal?: AbortSignal): AsyncGenerator<AgentEvent> {
  const n: Record<string, number> = {};
  const t0 = Date.now();
  let k = 0;
  while (Date.now() - t0 < ms) {
    for (const id of ids) {
      const salt = [...id].reduce((a, ch) => a + ch.charCodeAt(0), 0);
      const thought = (k + salt) % 5 === 0;
      const text = Array.from({ length: 3 + ((k * 7 + id.length) % 4) }, (_, i) => (thought ? PROSE : WORDS)[(k * 3 + i + salt) % (thought ? PROSE.length : WORDS.length)]).join(" ") + " ";
      n[id] = (n[id] ?? 0) + Math.round(text.length / 3.6);
      yield { type: "tokens", agent_id: id, call_id: `${id}#1`, kind: thought ? "thought" : "output", text, n_tokens_so_far: n[id], tps: 120 + ((k * 37 + salt * 13) % 110) };
    }
    k++;
    await sleep(110, signal);
  }
}

const THOUGHTS = [
  "Fold the beam early so the AOM arm has a long straight run; keep 25 mm clearance around mounts.",
  "The +1 order separates by only ~1.2° at 110 MHz, so the order-select iris must sit ≥ 50 mm after the AOM.",
  "Focusing through the AOM with f = 150 mm keeps w ≈ 0.36 mm inside a 2 mm aperture, so clipping is negligible.",
  "PBS split ratio set by λ/2 at 11.25° → 85 % to the AOM arm, 15 % to the reference fiber.",
];

export async function* mockAgentStream(kind: "design" | "reproduce", text: string, signal?: AbortSignal): AsyncGenerator<AgentEvent> {
  if (kind === "design" && /(apparatus|full|big|modules|ion trap|whole)/i.test(text)) {
    try { yield* hierarchical(signal); } catch (e) { if ((e as Error).name !== "AbortError") yield { type: "error", message: String(e) }; }
    return;
  }
  const base = pickBase(text);
  let seq = 0;
  try {
    if (kind === "reproduce") {
      yield ag("vision-1", "vision", "running", "Figure reader", null, { thinking_level: "high" });
      yield { type: "status", stage: "extract", message: "Reading figure: detecting components and beam paths" };
      yield th("vision-1", "Red line enters bottom-left, two right-angle folds; small squares are kinematic mirrors.");
      await sleep(900, signal);
      yield llm("vision-1", 2310, 1840, 2950, 8400, "high");
      yield {
        type: "extraction",
        graph: {
          components: (base.elements ?? []).map((e) => ({ id: e.id, type: e.type })),
          sources: base.sources.map((s) => ({ id: s.id, wavelength_nm: s.wavelength_nm })),
        },
      };
      yield ag("vision-1", "vision", "done", "Figure reader", null, { elapsed_ms: 9100, thinking_level: "high" });
      await sleep(500, signal);
    }
    const emitMatch = kind === "reproduce";
    yield ag("planner", "planner", "running", "Planner", null);
    for (let i = 0; i < 4; i++) yield ag(`designer-${i + 1}`, "designer", "queued", `Designer ${i + 1}`, "planner");
    yield { type: "status", stage: "plan", message: "Planning beam paths, branch topology and component budget" };
    yield* tokenBurst(["planner"], 900, signal);
    yield th("planner", "Goal: ≥ 8 mW frequency-shifted light in a fiber plus an SAS pickoff. Budget ~16 optics on an 18×9 inch plate.");
    await sleep(500, signal);
    yield th("planner", "Branch plan: L1 → isolator → λ/2 → two folds → 5 % pickoff (SAS) → PBS; PBS.t → AOM +1 → fiber, PBS.r → reference fiber.");
    await sleep(400, signal);
    yield llm("planner", 4120, 1210, 3380, 6300);
    yield ag("planner", "planner", "done", "Planner", null, { elapsed_ms: 1300 });
    yield { type: "status", stage: "design", message: "Generating 4 candidate layouts" };
    let best: { d: Design; score: number; r: ReturnType<typeof traceDesign>; seq: number } | null = null;
    for (let i = 0; i < 4; i++) yield ag(`designer-${i + 1}`, "designer", "running", `Designer ${i + 1}`, "planner");
    yield* tokenBurst(["designer-1", "designer-2", "designer-3", "designer-4"], 2600, signal);
    for (let i = 0; i < 4; i++) {
      const id = `designer-${i + 1}`;
      yield* tokenBurst([id, ...["designer-1", "designer-2", "designer-3", "designer-4"].slice(i + 1)], 350, signal);
      yield th(id, THOUGHTS[i % THOUGHTS.length]);
      await sleep(300, signal);
      yield llm(id, 5200 + i * 130, 2900 + i * 210, 4100 + i * 300, 11800 + i * 900);
      const d = variant(base, i);
      const r = traceDesign(d);
      yield tool(id, "trace", `${r.trace.segments.length} segments  ${r.trace.branches.length} branches  ${r.trace.elements.filter((e) => e.placed).length}/${r.trace.elements.length} placed`, 4 + i);
      yield tool(id, "verify", verifySummary(r), 2);
      yield { type: "status", stage: "verify", message: `Tracing candidate ${i + 1}: ${r.trace.segments.length} segments` };
      const s = ++seq;
      yield { type: "iteration", agent_id: id, seq: s, label: `cand ${i + 1}`, design: d, trace: r.trace, report: r.report, parent_seq: null, diff: [] };
      yield { type: "candidate", index: i, design: d, report: r.report, trace: r.trace };
      yield ag(id, "designer", "done", `Designer ${i + 1}`, "planner", { elapsed_ms: 13000 + i * 900 });
      if (!best || r.report.score > best.score) best = { d, score: r.report.score, r, seq: s };
      await sleep(450, signal);
    }
    // repair rounds on the best candidate
    let cur = best!;
    for (let round = 1; round <= 2; round++) {
      const id = `repair-${round}`;
      yield ag(id, "repair", "running", `Repair ${round}`, `designer-${cur.seq <= 4 ? cur.seq : 1}`);
      yield* tokenBurst([id], 900, signal);
      yield { type: "status", stage: "repair", message: `Repair round ${round}: ${firstErr(cur.r)}` };
      await sleep(300, signal);
      yield th(id, round === 1
        ? "Undumped 0th order leaves the plate (stray light). Add a dump on L1.t.t.0 and pull the iris 8 mm toward the AOM for margin."
        : "F2 coupling has margin; trim λ/2 by 2.5° to push more power into the AOM arm, and give the reference fold more room.");
      await sleep(400, signal);
      yield llm(id, 6800, 1450, 2700, 7900);
      const d = repairOf(cur.d, round);
      const r = traceDesign(d);
      yield tool(id, "trace", `${r.trace.segments.length} segments  ${r.trace.branches.length} branches`, 3);
      yield tool(id, "verify", verifySummary(r), 2);
      const s = ++seq;
      yield { type: "iteration", agent_id: id, seq: s, label: `repair ${round}`, design: d, trace: r.trace, report: r.report, parent_seq: cur.seq, diff: diffDesigns(cur.d, d) };
      yield ag(id, "repair", "done", `Repair ${round}`, null, { elapsed_ms: 9200 });
      cur = { d, score: r.report.score, r, seq: s };
      await sleep(500, signal);
    }
    if (emitMatch) {
      yield ag("matcher", "matcher", "running", "Figure matcher", null);
      const rows: MatchRow[] = (cur.d.elements ?? []).map((e) => ({ figure_label: e.label || e.id, figure_type: e.type, design_id: e.id, status: "matched" as const }));
      rows.push({ figure_label: "λ/4 plate (fig. label QWP)", figure_type: "quarter_wave_plate", design_id: null, status: "missing" });
      const matched = rows.filter((r) => r.status === "matched").length;
      yield tool("matcher", "match", `${matched}/${rows.length} figure components matched`, 1);
      yield { type: "match", rows, summary: { matched, in_figure: rows.length } };
      yield ag("matcher", "matcher", "done", "Figure matcher", null, { elapsed_ms: 400 });
      await sleep(300, signal);
    }
    yield { type: "iteration", agent_id: "verifier", seq: ++seq, label: "final", design: cur.d, trace: cur.r.trace, report: cur.r.report, parent_seq: cur.seq, diff: [] };
    yield { type: "status", stage: "done", message: `Selected design (score ${cur.score.toFixed(0)})` };
    yield { type: "final", design: cur.d, report: cur.r.report, trace: cur.r.trace };
  } catch (e) {
    if ((e as Error).name !== "AbortError") yield { type: "error", message: String(e) };
  }
}
