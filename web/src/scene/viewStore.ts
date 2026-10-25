import { create } from "zustand";

export type Preset = "top" | "iso" | "front" | "side" | "free";
export type Projection = "ortho" | "persp";

// [azimuth, polar] for camera-controls (Y-up world; table +y = world −Z)
export const PRESET_ANGLES: Record<Exclude<Preset, "free">, [number, number]> = {
  top: [0, 1e-3],
  iso: [Math.PI / 4, Math.acos(1 / Math.sqrt(3))],
  front: [0, Math.PI / 2],
  side: [Math.PI / 2, Math.PI / 2],
};

export type ViewRequest =
  | { kind: "preset"; n: number }
  | { kind: "fit"; n: number }
  | { kind: "focus"; n: number; x: number; y: number; r: number }
  | { kind: "focusBox"; n: number; x: number; y: number; w: number; h: number }
  | { kind: "projection"; n: number };

interface ViewState {
  preset: Preset;
  projection: Projection;
  req: ViewRequest;
  cursor: [number, number] | null;
  /** plan-view zoom is high enough to show per-element labels */
  labelsZoomOk: boolean;
  legendOpen: boolean;
  tweenUntil: number;
  tweenMs: number;
  highlight: Set<string>;
  highlightUntil: number;
  startTween: (ids: Set<string>, ms: number) => void;
  setLegendOpen: (v: boolean) => void;
  tooltip: { segId: string; z: number; sx: number; sy: number } | null;
  setPreset: (p: Preset) => void;
  toggleProjection: () => void;
  fit: () => void;
  focus: (x: number, y: number, r: number) => void;
  focusBox: (x: number, y: number, w: number, h: number) => void;
  setCursor: (c: [number, number] | null) => void;
  setTooltip: (t: ViewState["tooltip"]) => void;
}

let n = 0;
export const useView = create<ViewState>((set, get) => ({
  preset: "top",
  projection: "ortho",
  req: { kind: "fit", n: 0 },
  cursor: null,
  labelsZoomOk: true,
  legendOpen: true,
  tweenUntil: 0,
  tweenMs: 500,
  highlight: new Set(),
  highlightUntil: 0,
  startTween: (ids, ms) => {
    const t = performance.now();
    set({ tweenUntil: t + 60, tweenMs: ms, highlight: ids, highlightUntil: t + 2000 });
    setTimeout(() => { if (performance.now() >= useView.getState().highlightUntil - 5) set({ highlight: new Set() }); }, 2010);
  },
  setLegendOpen: (v) => set({ legendOpen: v }),
  tooltip: null,
  setPreset: (p) =>
    set({ preset: p, projection: p === "free" ? "persp" : "ortho", req: { kind: "preset", n: ++n } }),
  toggleProjection: () => {
    const persp = get().projection === "ortho";
    set({ projection: persp ? "persp" : "ortho", preset: persp ? "free" : get().preset === "free" ? "iso" : get().preset, req: { kind: "projection", n: ++n } });
  },
  fit: () => set({ req: { kind: "fit", n: ++n } }),
  focus: (x, y, r) => set({ req: { kind: "focus", n: ++n, x, y, r } }),
  focusBox: (x, y, w, h) => set({ req: { kind: "focusBox", n: ++n, x, y, w, h } }),
  setCursor: (c) => set({ cursor: c }),
  setTooltip: (t) => set({ tooltip: t }),
}));

/** DOM nodes the in-canvas frame loop writes to directly (scale bar), avoiding React re-renders */
export const domRefs: { scaleBar: HTMLDivElement | null; scaleLabel: HTMLSpanElement | null } = { scaleBar: null, scaleLabel: null };

if (import.meta.env.DEV) (window as unknown as { __view: typeof useView }).__view = useView;
