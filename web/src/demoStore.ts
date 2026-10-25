import { create } from "zustand";
import type { AgentEvent, Design, TraceResult, TuneDone, TuneStart, TuneStep } from "./types";
import { DEFAULT_BASEPLATE } from "./types";
import { useStore } from "./store";
import { useView } from "./scene/viewStore";
import { useConsole } from "./consoleStore";
import * as api from "./api";

// Choreography for the headline demo: figure → fly-in → beams light up → tuning tour.

export const FIG_H = 150; // mm above the beam plane

export interface FigBox { id?: string; label: string; type: string; box: [number, number, number, number] }

export interface TuneState {
  active: boolean;
  order: string[];
  baseline: { objective: number; delivered_mw: number; score: number } | null;
  current: string | null;
  field: string | null;
  value: number | null;
  values: number[]; // values tried on the current knob (slider range)
  history: number[]; // tuner objective per step ("alignment score")
  baseDelivered: number | null; // delivered power before the pass (re-trace)
  coupling: number | null;
  flags: Record<string, number>; // element → relative gain
  summary: { before: number; after: number; cBefore: number | null; cAfter: number | null } | null;
}

const emptyTune: TuneState = { active: false, order: [], baseline: null, current: null, field: null, value: null, values: [], history: [], baseDelivered: null, coupling: null, flags: {}, summary: null };

interface DemoState {
  speed: number;
  director: boolean;
  figure: { url: string; citation: string; aspect: number } | null;
  boxes: FigBox[];
  boxesAt: number | null;
  figFadeAt: number | null;
  flyAt: number | null;
  flyOrder: string[];
  flyStart: Record<string, [number, number]>; // element → table-frame xy on the figure plane
  flyEnd: number | null;
  flying: boolean;
  capturing: boolean;
  growAt: number | null;
  growEnd: number | null;
  tune: TuneState;
  autoAlign: boolean;
  setSpeed: (s: number) => void;
  setDirector: (v: boolean) => void;
  reset: () => void;
  onEvent: (ev: AgentEvent) => void;
  startFly: (d: Design, t: TraceResult) => void;
  lightUp: (delayMs?: number) => void;
  skip: () => void;
  align: () => Promise<void>;
}

const now = () => performance.now();
let tuneQueue: AgentEvent[] = [];
let tuneTimer: ReturnType<typeof setTimeout> | null = null;
let tuneAbort: AbortController | null = null;
let skipping = false;

/** figure-plane rectangle in table coordinates (centred over the plate) */
export function figureRect(aspect: number): { x0: number; y0: number; w: number; h: number } {
  const bp = { ...DEFAULT_BASEPLATE, ...(useStore.getState().design?.baseplate ?? {}) };
  let w = bp.width_mm, h = w * aspect;
  if (h > bp.height_mm * 1.4) { h = bp.height_mm * 1.4; w = h / aspect; }
  return { x0: bp.width_mm / 2 - w / 2, y0: bp.height_mm / 2 - h / 2, w, h };
}

export function boxCenter(b: FigBox, aspect: number): [number, number] {
  const r = figureRect(aspect);
  const [ymin, xmin, ymax, xmax] = b.box;
  return [r.x0 + (((xmin + xmax) / 2) / 1000) * r.w, r.y0 + r.h - (((ymin + ymax) / 2) / 1000) * r.h];
}

export const useDemo = create<DemoState>((set, get) => ({
  speed: 1,
  director: false,
  figure: null,
  boxes: [],
  boxesAt: null,
  figFadeAt: null,
  flyAt: null,
  flyOrder: [],
  flyStart: {},
  flyEnd: null,
  flying: false,
  capturing: false,
  growAt: null,
  growEnd: null,
  tune: emptyTune,
  autoAlign: false,

  setSpeed: (s) => set({ speed: s }),
  setDirector: (v) => set({ director: v }),
  reset: () => {
    tuneQueue = [];
    if (tuneTimer) clearTimeout(tuneTimer);
    tuneAbort?.abort();
    set({ figure: null, boxes: [], boxesAt: null, figFadeAt: null, flyAt: null, flyOrder: [], flyStart: {}, flyEnd: null, flying: false, growAt: null, growEnd: null, tune: emptyTune, autoAlign: false });
  },

  onEvent: (ev) => {
    switch (ev.type) {
      case "figure": {
        set({ figure: { url: ev.url, citation: ev.citation ?? "", aspect: 0.6 }, boxes: [], boxesAt: null, figFadeAt: null, flyAt: null, growAt: null });
        const img = new Image();
        img.onload = () => { const f = get().figure; if (f && f.url === ev.url) set({ figure: { ...f, aspect: img.naturalHeight / Math.max(1, img.naturalWidth) } }); };
        img.src = ev.url;
        // clear the previous layout so the figure floats over an empty table
        {
          const cur = useStore.getState().design;
          useStore.setState({ design: { name: "paper_build", description: ev.citation ?? "", baseplate: cur?.baseplate, sources: [], elements: [] }, trace: { segments: [], elements: [], branches: [] }, report: null, selected: null });
        }
        useView.getState().setPreset("iso");
        break;
      }
      case "extraction": {
        const comps = (ev.graph?.components as { id?: string; label?: string; type?: string; box_2d?: number[] }[] | undefined) ?? [];
        const boxes: FigBox[] = comps
          .filter((c) => Array.isArray(c.box_2d) && c.box_2d.length === 4)
          .map((c) => ({ id: c.id, label: c.label ?? c.id ?? c.type ?? "?", type: c.type ?? "", box: c.box_2d as [number, number, number, number] }));
        if (get().figure) set({ boxes, boxesAt: now() });
        break;
      }
      case "candidate":
      case "iteration":
      case "final":
        // only fly in a design worth showing: the first passing one, else the final
        if (get().figure && get().boxesAt != null && get().flyAt == null && (ev.report?.passed || ev.type === "final")) get().startFly(ev.design, ev.trace);
        break;
      default:
        break;
    }
  },

  startFly: (d, t) => {
    const fig = get().figure;
    if (!fig) return;
    // beam-path order: first time each element is reached along the traced segments
    const order: string[] = [];
    for (const s of t.segments) for (const id of [s.start_element, s.end_element]) if (id && !order.includes(id)) order.push(id);
    for (const e of t.elements) if (!order.includes(e.id)) order.push(e.id);
    // match each element to a figure box: id, then label, then n-th box of the same type
    const boxes = get().boxes;
    const used = new Set<number>();
    const start: Record<string, [number, number]> = {};
    const byType = new Map<string, number[]>();
    boxes.forEach((b, i) => byType.set(b.type, [...(byType.get(b.type) ?? []), i]));
    for (const id of order) {
      const el = d.elements?.find((e) => e.id === id);
      const src = d.sources.find((s) => s.id === id);
      let i = boxes.findIndex((b, k) => !used.has(k) && (b.id === id || (!!el?.label && b.label === el.label)));
      if (i < 0) i = (byType.get(el?.type ?? (src ? "laser" : "")) ?? []).find((k) => !used.has(k)) ?? -1;
      if (i >= 0) { used.add(i); start[id] = boxCenter(boxes[i], fig.aspect); }
      else {
        const r = figureRect(fig.aspect);
        const pos = t.elements.find((e) => e.id === id)?.position ?? src?.position ?? [r.x0 + r.w / 2, r.y0 + r.h / 2];
        start[id] = [pos[0], pos[1]];
      }
    }
    const sp = get().speed;
    const t0 = now() + 250;
    const flyEnd = t0 + (order.length * 75 + 950) / sp;
    set({ flyAt: t0, flyOrder: order, flyStart: start, flyEnd, figFadeAt: flyEnd, flying: true });
    setTimeout(() => set({ flying: false }), flyEnd - now() + 80);
    get().lightUp(flyEnd - now() + 350 / sp);
  },

  lightUp: (delayMs = 0) => {
    const t = now() + delayMs;
    const segs = useStore.getState().trace?.segments ?? [];
    const total = Math.max(300, ...segs.map((s) => s.length_mm)) * 3;
    set({ growAt: t, growEnd: t + total / (GROW_MM_PER_MS * get().speed) + 200 });
    setTimeout(() => {
      if (get().autoAlign) { set({ autoAlign: false }); get().align(); }
    }, Math.max(0, t - now()) + total / (GROW_MM_PER_MS * get().speed) + 900);
  },

  skip: () => {
    set({ flyAt: get().figure ? 0 : null, flyStart: {}, flyEnd: 0, flying: false, growAt: null, growEnd: null, figFadeAt: get().figure ? now() - 10000 : null });
    if (get().tune.active) { skipping = true; pump(); }
  },

  align: async () => {
    const st = useStore.getState();
    const d = st.design;
    if (!d) return;
    tuneAbort?.abort();
    tuneAbort = new AbortController();
    tuneQueue = [];
    skipping = false;
    const reference = d;
    const detuned = await api.detune(d);
    st.replaceDesign(detuned);
    useConsole.getState().ingest({ type: "status", stage: "tune", message: "Bench detuned; starting alignment pass" });
    set({ tune: { ...emptyTune, active: true } });
    await new Promise((r) => setTimeout(r, 600));
    try {
      for await (const ev of api.tuneStream(detuned, reference, tuneAbort.signal)) {
        tuneQueue.push(ev);
        if (!tuneTimer) pump();
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") useConsole.getState().ingest({ type: "error", message: String(e) });
    }
  },
}));

export const GROW_MM_PER_MS = 0.32;

function couplingOf(t: TraceResult | null): number | null {
  const fc = t?.elements.find((e) => e.type === "fiber_coupler" && e.coupling_efficiency != null);
  return fc?.coupling_efficiency ?? null;
}

/** tune player: paces queued tune events so each knob move is visible */
function pump() {
  tuneTimer = null;
  const ev = tuneQueue.shift();
  if (!ev) return;
  const D = useDemo;
  const sp = D.getState().speed;
  const tune = D.getState().tune;
  const con = useConsole.getState();
  let wait = 0;
  switch (ev.type) {
    case "tune_start": {
      const e = ev as TuneStart;
      D.setState({ tune: { ...tune, active: true, order: e.order, baseline: e.baseline, baseDelivered: useStore.getState().report?.metrics.delivered_mw ?? e.baseline.delivered_mw, coupling: couplingOf(useStore.getState().trace) } });
      con.ingest({ type: "tool", agent_id: "tuner", name: "tune", summary: `start  ${e.order.length} knobs  objective ${e.objective}  baseline ${e.baseline.delivered_mw.toFixed(2)} mW`, elapsed_ms: 0 });
      wait = 400;
      break;
    }
    case "tune_step": {
      const e = ev as TuneStep;
      const switching = tune.current !== e.element_id;
      if (switching && !skipping) {
        const p = useStore.getState().trace?.elements.find((x) => x.id === e.element_id)?.position;
        if (p) useView.getState().focus(p[0], p[1], 45);
      }
      useStore.getState().updateElement(e.element_id, e.patch);
      D.setState({
        tune: {
          ...tune, current: e.element_id, field: e.field, value: e.value,
          values: switching ? [e.value] : [...tune.values, e.value],
          history: [...tune.history, e.objective], coupling: e.metrics.coupling ?? tune.coupling,
        },
      });
      con.ingest({ type: "tool", agent_id: "tuner", name: "tune", summary: `${e.element_id} ${e.field} ${e.value.toFixed(3)} → ${e.objective.toFixed(3)} mW${e.best_so_far ? "  *best" : ""}`, elapsed_ms: 0 });
      wait = switching ? 650 : 170;
      break;
    }
    case "tune_done": {
      const e = ev as TuneDone;
      D.setState({ tune: { ...tune, flags: { ...tune.flags, [e.element_id]: e.gain } } });
      con.ingest({ type: "tool", agent_id: "tuner", name: "tune", summary: `done ${e.element_id} ${e.field} ${e.from.toFixed(2)} → ${e.to.toFixed(2)}  gain ${(e.gain * 100).toFixed(1)} %`, elapsed_ms: 0 });
      wait = 380;
      break;
    }
    case "final": {
      const before = tune.baseDelivered ?? tune.baseline?.delivered_mw ?? 0;
      const after = ev.report.metrics.delivered_mw ?? 0;
      useStore.getState().showDesign(ev.design, { trace: ev.trace, report: ev.report });
      D.setState({ tune: { ...tune, active: false, current: null, summary: { before, after, cBefore: firstCoupling, cAfter: couplingOf(ev.trace) } } });
      con.ingest({ type: "final", design: ev.design, trace: ev.trace, report: ev.report });
      useView.getState().fit();
      skipping = false;
      break;
    }
    case "error":
      con.ingest(ev);
      break;
    default:
      break;
  }
  if (ev.type === "tune_start") firstCoupling = couplingOf(useStore.getState().trace);
  if (tuneQueue.length) tuneTimer = setTimeout(pump, skipping ? 0 : wait / sp);
  else if (ev.type !== "final") tuneTimer = setTimeout(pump, 120); // wait for more events
}
let firstCoupling: number | null = null;
