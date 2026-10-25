import { create } from "zustand";
import { DEFAULT_BASEPLATE } from "./types";
import type { AgentEvent, Design, Element, FiberLink, MatchRow, Source, TraceResult, VerifyReport } from "./types";
import * as api from "./api";
import { useView } from "./scene/viewStore";
import { useConsole } from "./consoleStore";

export type Selection = { kind: "element" | "source" | "segment"; id: string } | null;

export interface LogRow {
  t: number; // ms since run start
  at: number; // wall clock
  stage: string;
  message: string;
  level: "info" | "error" | "ok";
}

export interface Candidate {
  index: number;
  design: Design;
  report: VerifyReport;
  trace: TraceResult;
  final?: boolean;
}

interface AgentState {
  running: boolean;
  kind: "design" | "reproduce" | null;
  startedAt: number;
  log: LogRow[];
  candidates: Candidate[];
  active: number | null; // candidate index loaded, -1 = final
  extraction: Record<string, unknown> | null;
  match: { rows: MatchRow[]; summary: { matched: number; in_figure: number } } | null;
  figureUrl: string | null;
  links: FiberLink[];
  failed: Record<string, string>;
}

interface State {
  design: Design | null;
  trace: TraceResult | null;
  report: VerifyReport | null;
  traceMs: number | null;
  tracing: boolean;
  traceError: string | null;
  selected: Selection;
  hoverSeg: string | null;
  view: "2d" | "3d";
  exaggeration: number;
  mock: boolean;
  leftTab: "workflow" | "outline" | "json";
  showFigure: boolean;
  compare: boolean;
  setCompare: (v: boolean) => void;
  soloModule: string | null;
  setSoloModule: (id: string | null) => void;
  agent: AgentState;
  exportOpen: boolean;

  loadDesign: (d: Design, pre?: { trace: TraceResult; report: VerifyReport }) => void;
  /** swap in a design without refitting the camera or clearing the selection (iteration playback) */
  showDesign: (d: Design, pre: { trace: TraceResult; report: VerifyReport }) => void;
  fitNonce: number;
  updateElement: (id: string, patch: Partial<Element>) => void;
  updateSource: (id: string, patch: Partial<Source>) => void;
  replaceDesign: (d: Design) => void;
  select: (s: Selection) => void;
  setHoverSeg: (id: string | null) => void;
  setView: (v: "2d" | "3d") => void;
  setExaggeration: (v: number) => void;
  setLeftTab: (t: "workflow" | "outline" | "json") => void;
  setShowFigure: (v: boolean) => void;
  setExportOpen: (v: boolean) => void;
  runDesign: (goal: string) => Promise<void>;
  runReproduce: (file: File, notes: string) => Promise<void>;
  stopAgent: () => void;
  runRecorded: (file: string, kind: "design" | "reproduce", figure?: string) => Promise<void>;
  loadCandidate: (index: number) => void;
}

const AGENT_LAYOUT = "agent_layout";
const moduleTraces = new Map<string, TraceResult>();
let traceTimer: ReturnType<typeof setTimeout> | null = null;
let traceAbort: AbortController | null = null;
let agentAbort: AbortController | null = null;

const emptyAgent: AgentState = {
  running: false, kind: null, startedAt: 0, log: [], candidates: [], active: null, extraction: null, match: null, figureUrl: null, links: [], failed: {},
};

export const useStore = create<State>((set, get) => {
  const doTrace = async () => {
    const d = get().design;
    if (!d) return;
    traceAbort?.abort();
    const ac = new AbortController();
    traceAbort = ac;
    set({ tracing: true });
    const t0 = performance.now();
    try {
      const r = await api.trace(d, ac.signal);
      if (ac.signal.aborted || get().design !== d) return;
      set({ trace: r.trace, report: r.report, traceMs: performance.now() - t0, tracing: false, traceError: null });
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      set({ tracing: false, traceError: (e as Error).message });
    }
  };
  const scheduleTrace = (ms = 80) => {
    if (traceTimer) clearTimeout(traceTimer);
    traceTimer = setTimeout(doTrace, ms);
  };

  const pushLog = (row: Omit<LogRow, "t" | "at">) =>
    set((s) => ({ agent: { ...s.agent, log: [...s.agent.log, { ...row, at: Date.now(), t: Date.now() - s.agent.startedAt }] } }));

  const consume = async (kind: "design" | "reproduce", gen: AsyncGenerator<AgentEvent>, figureUrl: string | null) => {
    set((s) => ({ agent: { ...emptyAgent, figureUrl: figureUrl ?? (kind === "reproduce" ? s.agent.figureUrl : null), running: true, kind, startedAt: Date.now() }, showFigure: !!figureUrl, compare: !!figureUrl || s.compare && kind === "reproduce" }));
    if (figureUrl) useView.setState({ legendOpen: false });
    pushLog({ stage: "start", message: kind === "design" ? "Design run started" : "Reproduce-from-figure run started", level: "info" });
    useConsole.getState().reset();
    try {
      for await (const ev of gen) {
        useConsole.getState().ingest(ev);
        switch (ev.type) {
          case "status":
            pushLog({ stage: ev.stage, message: ev.message, level: ev.stage === "done" ? "ok" : "info" });
            break;
          case "extraction":
            set((s) => ({ agent: { ...s.agent, extraction: ev.graph } }));
            pushLog({ stage: "extract", message: `Figure parsed: ${summarizeGraph(ev.graph)}`, level: "info" });
            break;
          case "candidate":
            set((s) => ({ agent: { ...s.agent, candidates: [...s.agent.candidates.filter((c) => c.index !== ev.index), { index: ev.index, design: ev.design, report: ev.report, trace: ev.trace }] } }));
            pushLog({ stage: "candidate", message: `Candidate ${ev.index + 1}: score ${ev.report.score.toFixed(0)}, ${ev.report.passed ? "PASS" : "FAIL"}`, level: ev.report.passed ? "ok" : "info" });
            // preview the first candidate so the canvas comes alive during the run
            if (get().agent.active == null && useConsole.getState().iterations.length === 0) { get().loadDesign(ev.design, { trace: ev.trace, report: ev.report }); set((s) => ({ agent: { ...s.agent, active: ev.index } })); }
            break;
          case "final":
            set((s) => ({ agent: { ...s.agent, candidates: [...s.agent.candidates, { index: -1, design: ev.design, report: ev.report, trace: ev.trace, final: true }], active: -1 } }));
            if (useConsole.getState().iterations.length) get().showDesign(ev.design, { trace: ev.trace, report: ev.report });
            else get().loadDesign(ev.design, { trace: ev.trace, report: ev.report });
            pushLog({ stage: "final", message: `Loaded final design "${ev.design.name}" (score ${ev.report.score.toFixed(0)})`, level: "ok" });
            break;
          case "modules": {
            const plate = { ...DEFAULT_BASEPLATE, ...(ev.table ?? {}) };
            moduleTraces.clear();
            set((st) => ({ agent: { ...st.agent, links: ev.links ?? [], failed: {} } }));
            const placeholder: Design = { name: AGENT_LAYOUT, description: ev.title ? `${ev.title} (in progress)` : "Hierarchical design in progress", baseplate: plate, modules: ev.modules ?? [], sources: [], elements: [] };
            useView.setState({ legendOpen: false });
            set((st) => ({ design: placeholder, trace: { segments: [], elements: [], branches: [] }, report: null, selected: null, fitNonce: st.fitNonce + 1 }));
            pushLog({ stage: "plan", message: `Planned ${ev.modules?.length ?? 0} modules on ${plate.width_mm.toFixed(0)} × ${plate.height_mm.toFixed(0)} mm`, level: "info" });
            break;
          }
          case "module_done": {
            const cur = get().design;
            const sub = ev.design;
            const tag = <T extends { group?: string | null }>(x: T): T => ({ ...x, group: x.group ?? ev.module_id });
            const base: Design = cur && (cur.name === AGENT_LAYOUT || (cur.modules ?? []).some((m) => m.id === ev.module_id)) ? cur : { name: AGENT_LAYOUT, baseplate: sub.baseplate, modules: sub.modules ?? [], sources: [], elements: [] };
            const mods = [...(base.modules ?? [])];
            for (const m of sub.modules ?? []) if (!mods.some((x) => x.id === m.id)) mods.push(m);
            const merged: Design = {
              ...base,
              modules: mods,
              sources: [...base.sources.filter((x) => x.group !== ev.module_id), ...sub.sources.map(tag)],
              elements: [...(base.elements ?? []).filter((x) => x.group !== ev.module_id), ...(sub.elements ?? []).map(tag)],
              targets: [...(base.targets ?? []), ...(sub.targets ?? [])],
            };
            set({ design: merged });
            if (ev.trace) {
              // module trace is already in table coordinates: stitch per-module traces instead of re-tracing
              const pre = (id: string) => `${ev.module_id}:${id}`;
              moduleTraces.set(ev.module_id, {
                segments: ev.trace.segments.map((x) => ({ ...x, id: pre(x.id) })),
                elements: ev.trace.elements.map((x) => ({ ...x, hits: x.hits.map((h) => ({ ...h, segment_id: pre(h.segment_id) })) })),
                branches: ev.trace.branches,
              });
              const all = [...moduleTraces.values()];
              set({ trace: { segments: all.flatMap((t) => t.segments), elements: all.flatMap((t) => t.elements), branches: all.flatMap((t) => t.branches) } });
              if (!get().report && ev.report) set({ report: ev.report });
            } else scheduleTrace(0);
            const title = mods.find((m) => m.id === ev.module_id)?.title ?? ev.module_id;
            pushLog({ stage: "module", message: `${title} done${ev.report ? `: score ${ev.report.score.toFixed(0)}, ${ev.report.passed ? "PASS" : "FAIL"}` : ""}`, level: ev.report?.passed === false ? "info" : "ok" });
            break;
          }
          case "module_failed":
            set((s) => ({ agent: { ...s.agent, failed: { ...s.agent.failed, [ev.module_id]: ev.message } } }));
            pushLog({ stage: "module", message: `${ev.module_id} failed: ${ev.message}`, level: "error" });
            break;
          case "match":
            set((s) => ({ agent: { ...s.agent, match: { rows: ev.rows ?? [], summary: ev.summary ?? { matched: 0, in_figure: 0 } } } }));
            pushLog({ stage: "match", message: `Matched ${ev.summary?.matched ?? 0}/${ev.summary?.in_figure ?? 0} figure components`, level: ev.summary && ev.summary.matched === ev.summary.in_figure ? "ok" : "info" });
            break;
          case "error":
            pushLog({ stage: "error", message: ev.message, level: "error" });
            break;
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") pushLog({ stage: "error", message: (e as Error).message, level: "error" });
    } finally {
      useConsole.getState().finish();
      set((s) => ({ agent: { ...s.agent, running: false } }));
    }
  };

  return {
    design: null, trace: null, report: null, traceMs: null, tracing: false, traceError: null,
    selected: null, hoverSeg: null, view: "2d", exaggeration: 3, mock: api.isMock(), leftTab: "workflow",
    showFigure: true, compare: false, agent: emptyAgent, exportOpen: false,
    setCompare: (v) => { if (v) useView.setState({ legendOpen: false }); set({ compare: v }); },
    soloModule: null,
    setSoloModule: (id) => set({ soloModule: id }),

    fitNonce: 0,
    showDesign: (d, pre) => {
      if (traceTimer) clearTimeout(traceTimer);
      traceAbort?.abort();
      set({ design: d, trace: pre.trace, report: pre.report, traceMs: null, traceError: null });
    },
    loadDesign: (d, pre) => {
      set((s) => ({ fitNonce: s.fitNonce + 1 }));
      if (get().design?.name !== d.name) useView.setState({ legendOpen: (d.elements?.length ?? 0) <= 30 && !get().compare });
      set({ design: d, selected: null });
      if (pre) set({ trace: pre.trace, report: pre.report, traceMs: null, traceError: null });
      else scheduleTrace(0);
    },
    replaceDesign: (d) => { set({ design: d }); scheduleTrace(); },
    updateElement: (id, patch) => {
      const d = get().design;
      if (!d) return;
      set({ design: { ...d, elements: (d.elements ?? []).map((e) => (e.id === id ? { ...e, ...patch } : e)) } });
      scheduleTrace();
    },
    updateSource: (id, patch) => {
      const d = get().design;
      if (!d) return;
      set({ design: { ...d, sources: d.sources.map((s) => (s.id === id ? { ...s, ...patch } : s)) } });
      scheduleTrace();
    },
    select: (s) => set({ selected: s }),
    setHoverSeg: (id) => set({ hoverSeg: id }),
    setView: (v) => set({ view: v }),
    setExaggeration: (v) => set({ exaggeration: v }),
    setLeftTab: (t) => set({ leftTab: t }),
    setShowFigure: (v) => set({ showFigure: v }),
    setExportOpen: (v) => set({ exportOpen: v }),

    runDesign: async (goal) => {
      agentAbort?.abort();
      agentAbort = new AbortController();
      await consume("design", api.designStream(goal, 4, agentAbort.signal), null);
    },
    runReproduce: async (file, notes) => {
      agentAbort?.abort();
      agentAbort = new AbortController();
      const url = URL.createObjectURL(file);
      await consume("reproduce", api.reproduceStream(file, notes, agentAbort.signal), url);
    },
    runRecorded: async (file, kind, figure) => {
      agentAbort?.abort();
      agentAbort = new AbortController();
      await consume(kind, api.replayRecorded(file, agentAbort.signal), figure ?? null);
    },
    stopAgent: () => {
      agentAbort?.abort();
      pushLog({ stage: "stop", message: "Run cancelled by user", level: "error" });
      set((s) => ({ agent: { ...s.agent, running: false } }));
    },
    loadCandidate: (index) => {
      const c = get().agent.candidates.find((x) => x.index === index);
      if (!c) return;
      get().loadDesign(c.design, { trace: c.trace, report: c.report });
      set((s) => ({ agent: { ...s.agent, active: index } }));
    },
  };
});

api.onMockChange((m) => useStore.setState({ mock: m }));

function summarizeGraph(g: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(g)) if (Array.isArray(v)) parts.push(`${v.length} ${k}`);
  return parts.join(", ") || "graph received";
}

if (import.meta.env.DEV) (window as unknown as { __beamline: typeof useStore }).__beamline = useStore;
