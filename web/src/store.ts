import { create } from "zustand";
import type { AgentEvent, Design, Element, MatchRow, Source, TraceResult, VerifyReport } from "./types";
import * as api from "./api";
import { useView } from "./scene/viewStore";

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
  loadCandidate: (index: number) => void;
}

let traceTimer: ReturnType<typeof setTimeout> | null = null;
let traceAbort: AbortController | null = null;
let agentAbort: AbortController | null = null;

const emptyAgent: AgentState = {
  running: false, kind: null, startedAt: 0, log: [], candidates: [], active: null, extraction: null, match: null, figureUrl: null,
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
    pushLog({ stage: "start", message: kind === "design" ? "Design run started" : "Reproduce-from-figure run started", level: "info" });
    try {
      for await (const ev of gen) {
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
            if (get().agent.active == null) { get().loadDesign(ev.design, { trace: ev.trace, report: ev.report }); set((s) => ({ agent: { ...s.agent, active: ev.index } })); }
            break;
          case "final":
            set((s) => ({ agent: { ...s.agent, candidates: [...s.agent.candidates, { index: -1, design: ev.design, report: ev.report, trace: ev.trace, final: true }], active: -1 } }));
            get().loadDesign(ev.design, { trace: ev.trace, report: ev.report });
            pushLog({ stage: "final", message: `Loaded final design "${ev.design.name}" (score ${ev.report.score.toFixed(0)})`, level: "ok" });
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
      set((s) => ({ agent: { ...s.agent, running: false } }));
    }
  };

  return {
    design: null, trace: null, report: null, traceMs: null, tracing: false, traceError: null,
    selected: null, hoverSeg: null, view: "2d", exaggeration: 3, mock: api.isMock(), leftTab: "workflow",
    showFigure: true, compare: false, agent: emptyAgent, exportOpen: false,
    setCompare: (v) => set({ compare: v }),
    soloModule: null,
    setSoloModule: (id) => set({ soloModule: id }),

    loadDesign: (d, pre) => {
      if (get().design?.name !== d.name) useView.setState({ legendOpen: (d.elements?.length ?? 0) <= 30 });
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
