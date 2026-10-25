import { create } from "zustand";

// Live token streams per agent. Text goes into per-agent ring buffers (module-level, not React state);
// subscribers re-render at most once per animation frame via `v`.

export interface Chunk { kind: "output" | "thought"; text: string }
export interface Stream {
  id: string;
  chunks: Chunk[];
  len: number;
  total: number; // chars ever received
  tokens: number; // n_tokens_so_far (latest)
  tps: number;
  tpsHist: number[];
  lastAt: number;
  calls: Set<string>;
}

const MAX = 2048;
export const streams = new Map<string, Stream>();
let raf = 0;

export const useTokens = create<{ v: number }>(() => ({ v: 0 }));

function bump() {
  if (raf) return;
  raf = requestAnimationFrame(() => {
    raf = 0;
    useTokens.setState((s) => ({ v: s.v + 1 }));
  });
}

export function pushTokens(ev: { agent_id: string; call_id?: string; kind?: string; text: string; n_tokens_so_far?: number; tps?: number }) {
  let s = streams.get(ev.agent_id);
  if (!s) {
    s = { id: ev.agent_id, chunks: [], len: 0, total: 0, tokens: 0, tps: 0, tpsHist: [], lastAt: 0, calls: new Set() };
    streams.set(ev.agent_id, s);
  }
  const kind = ev.kind === "thought" ? "thought" : "output";
  const last = s.chunks.at(-1);
  if (last && last.kind === kind) last.text += ev.text;
  else s.chunks.push({ kind, text: ev.text });
  s.len += ev.text.length;
  s.total += ev.text.length;
  // trim the ring buffer from the front
  while (s.len > MAX && s.chunks.length) {
    const c = s.chunks[0];
    const over = s.len - MAX;
    if (c.text.length <= over) { s.chunks.shift(); s.len -= c.text.length; }
    else { c.text = c.text.slice(over); s.len -= over; }
  }
  if (ev.call_id) s.calls.add(ev.call_id);
  if (ev.n_tokens_so_far != null) s.tokens = ev.n_tokens_so_far;
  if (ev.tps != null) { s.tps = ev.tps; s.tpsHist.push(ev.tps); if (s.tpsHist.length > 40) s.tpsHist.shift(); }
  s.lastAt = performance.now();
  bump();
}

export function resetTokens() {
  streams.clear();
  bump();
}

/** tail of an agent's stream, as chunks totalling at most n chars */
export function tail(s: Stream, n: number): Chunk[] {
  const out: Chunk[] = [];
  let left = n;
  for (let i = s.chunks.length - 1; i >= 0 && left > 0; i--) {
    const c = s.chunks[i];
    const t = c.text.length > left ? c.text.slice(-left) : c.text;
    out.unshift({ kind: c.kind, text: t });
    left -= t.length;
  }
  return out;
}

/** live tok/s: decays to zero when an agent stops streaming */
export function liveTps(s: Stream): number {
  const age = performance.now() - s.lastAt;
  return age > 1500 ? 0 : s.tps;
}

// ───────── agent colours: stable, distinct, colour-blind-aware ordering ─────────
// Okabe–Ito-derived hues, ordered so neighbours differ strongly; light/dark variants keep contrast on panels.
const LIGHT = ["#0b6fb8", "#c26100", "#0a8a5f", "#b8336a", "#6a4fb3", "#1b8fa8", "#8a7400", "#a3471f", "#3d7d1f", "#7a5a8c"];
const DARK = ["#5aaef0", "#ffa94d", "#3ddc97", "#ff7eb0", "#b39cff", "#4fd2e8", "#e6cc4a", "#ff8a5c", "#8fd65a", "#d0a8e8"];

export function agentColorIndex(order: number): number {
  return ((order % LIGHT.length) + LIGHT.length) % LIGHT.length;
}
export function agentColor(order: number, dark: boolean): string {
  return (dark ? DARK : LIGHT)[agentColorIndex(order)];
}
