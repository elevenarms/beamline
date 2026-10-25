import { create } from "zustand";
import type { AgentEvent, Change, Design, TraceResult, VerifyReport } from "./types";
import { diffDesigns, changeText } from "./lib/diff";
import { pushTokens, resetTokens } from "./tokenStore";
import { useStore } from "./store";
import { useView } from "./scene/viewStore";

export type LogKind = "status" | "agent" | "llm" | "thought" | "tool" | "iteration" | "candidate" | "final" | "error" | "match" | "module";

export interface LogRow {
  i: number;
  t: number; // ms since run start
  agent: string | null;
  kind: LogKind;
  text: string;
  iter?: number; // index into iterations
  changes?: Change[];
}

export interface AgentInfo {
  id: string;
  role: string;
  title: string;
  parent: string | null;
  state: "queued" | "running" | "done" | "error" | "cancelled";
  model: string | null;
  thinking: string | null;
  startedAt: number | null; // ms since run start
  endedAt: number | null;
  elapsedMs: number | null;
  message: string | null;
  calls: number;
  tin: number;
  tout: number;
  tthought: number;
  order: number;
}

export interface Iteration {
  seq: number;
  label: string;
  agent: string;
  design: Design;
  trace: TraceResult;
  report: VerifyReport;
  parentSeq: number | null;
  diff: Change[];
  t: number;
}

interface ConsoleState {
  open: boolean;
  height: number;
  startedAt: number;
  endedAt: number | null;
  rows: LogRow[];
  agents: Record<string, AgentInfo>;
  iterations: Iteration[];
  current: number | null;
  playing: boolean;
  filterAgent: string | null;
  kinds: Set<LogKind> | null; // null = all
  search: string;
  view: "log" | "streams";
  setView: (v: "log" | "streams") => void;
  totals: { calls: number; tin: number; tout: number; tthought: number };
  reset: () => void;
  finish: () => void;
  ingest: (ev: AgentEvent | { type: "status"; stage: string; message: string }) => void;
  setOpen: (v: boolean) => void;
  setHeight: (h: number) => void;
  setFilterAgent: (a: string | null) => void;
  toggleKind: (k: LogKind | "all") => void;
  setSearch: (s: string) => void;
  showIteration: (index: number, animate?: boolean) => void;
  step: (d: number) => void;
  play: () => void;
  stop: () => void;
}

let playTimer: ReturnType<typeof setTimeout> | null = null;
const MAX_ROWS = 5000;

export const useConsole = create<ConsoleState>((set, get) => {
  const now = () => Date.now() - get().startedAt;
  const push = (row: Omit<LogRow, "i" | "t">) =>
    set((s) => {
      const rows = s.rows.length >= MAX_ROWS ? s.rows.slice(-MAX_ROWS + 1) : s.rows.slice();
      rows.push({ ...row, i: (s.rows.at(-1)?.i ?? -1) + 1, t: now() });
      return { rows };
    });
  const upsertAgent = (id: string, patch: Partial<AgentInfo>) =>
    set((s) => {
      const prev = s.agents[id];
      const base: AgentInfo = prev ?? {
        id, role: "agent", title: id, parent: null, state: "queued", model: null, thinking: null, startedAt: null, endedAt: null,
        elapsedMs: null, message: null, calls: 0, tin: 0, tout: 0, tthought: 0, order: Object.keys(s.agents).length,
      };
      return { agents: { ...s.agents, [id]: { ...base, ...patch } } };
    });

  return {
    open: false,
    height: 300,
    startedAt: Date.now(),
    endedAt: null,
    rows: [],
    agents: {},
    iterations: [],
    current: null,
    playing: false,
    filterAgent: null,
    kinds: null,
    search: "",
    view: "log",
    setView: (v) => set({ view: v }),
    totals: { calls: 0, tin: 0, tout: 0, tthought: 0 },

    reset: () => {
      get().stop();
      resetTokens();
      set({ startedAt: Date.now(), endedAt: null, rows: [], agents: {}, iterations: [], current: null, filterAgent: null, totals: { calls: 0, tin: 0, tout: 0, tthought: 0 }, open: true, view: "streams" });
      // a short canvas can't afford the expanded legend while the console is open
      if (window.innerHeight < 1100) useView.setState({ legendOpen: false });
    },
    finish: () => set({ endedAt: now(), view: "log" }),

    ingest: (ev) => {
      switch (ev.type) {
        case "agent": {
          const t = now();
          const prev = get().agents[ev.agent_id];
          upsertAgent(ev.agent_id, {
            role: ev.role, title: ev.title || ev.agent_id, parent: ev.parent ?? null, state: ev.state,
            model: ev.model ?? prev?.model ?? null, thinking: ev.thinking_level ?? prev?.thinking ?? null,
            startedAt: ev.state === "running" && prev?.startedAt == null ? t : prev?.startedAt ?? null,
            endedAt: ev.state === "done" || ev.state === "error" || ev.state === "cancelled" ? t : null,
            elapsedMs: ev.elapsed_ms ?? prev?.elapsedMs ?? null, message: ev.message ?? prev?.message ?? null,
          });
          if (ev.state !== "queued") push({ agent: ev.agent_id, kind: "agent", text: `${ev.state}${ev.message ? ` · ${ev.message}` : ""}${ev.elapsed_ms != null && ev.state !== "running" ? `  (${(ev.elapsed_ms / 1000).toFixed(1)} s)` : ""}` });
          break;
        }
        case "llm_call": {
          const a = get().agents[ev.agent_id];
          upsertAgent(ev.agent_id, {
            calls: (a?.calls ?? 0) + 1, tin: (a?.tin ?? 0) + (ev.prompt_tokens ?? 0), tout: (a?.tout ?? 0) + (ev.output_tokens ?? 0),
            tthought: (a?.tthought ?? 0) + (ev.thought_tokens ?? 0), model: ev.model ?? a?.model ?? null, thinking: ev.thinking_level ?? a?.thinking ?? null,
          });
          set((s) => ({ totals: { calls: s.totals.calls + 1, tin: s.totals.tin + (ev.prompt_tokens ?? 0), tout: s.totals.tout + (ev.output_tokens ?? 0), tthought: s.totals.tthought + (ev.thought_tokens ?? 0) } }));
          push({
            agent: ev.agent_id, kind: "llm",
            text: `${ev.model} [${ev.thinking_level}]  in ${ev.prompt_tokens}  out ${ev.output_tokens}  thought ${ev.thought_tokens}  ${(ev.latency_ms / 1000).toFixed(2)} s${ev.ttft_ms != null ? `  ttft ${(ev.ttft_ms / 1000).toFixed(2)} s` : ""}  ${ev.finish_reason}`,
          });
          break;
        }
        case "thought": {
          // merge consecutive chunks from the same agent into one collapsible row
          const rows = get().rows;
          const last = rows.at(-1);
          if (last && last.kind === "thought" && last.agent === ev.agent_id && last.text.length < 4000) {
            set({ rows: [...rows.slice(0, -1), { ...last, text: `${last.text} ${ev.text}`.trim() }] });
          } else push({ agent: ev.agent_id, kind: "thought", text: ev.text });
          break;
        }
        case "tool":
          push({ agent: ev.agent_id, kind: "tool", text: `${ev.name.padEnd(7)} ${ev.summary}  ${ev.elapsed_ms != null ? `${ev.elapsed_ms.toFixed(0)} ms` : ""}` });
          break;
        case "iteration": {
          const its = get().iterations;
          const parent = ev.parent_seq != null ? its.find((x) => x.seq === ev.parent_seq) : undefined;
          const diff = ev.diff && ev.diff.length ? ev.diff : diffDesigns(parent?.design, ev.design);
          const it: Iteration = { seq: ev.seq, label: ev.label, agent: ev.agent_id, design: ev.design, trace: ev.trace, report: ev.report, parentSeq: ev.parent_seq ?? null, diff, t: now() };
          set({ iterations: [...its, it] });
          const idx = get().iterations.length - 1;
          push({ agent: ev.agent_id, kind: "iteration", text: `#${ev.seq} ${ev.label}  score ${ev.report.score.toFixed(0)}  ${ev.report.passed ? "PASS" : "FAIL"}  ${diff.length} change${diff.length === 1 ? "" : "s"}`, iter: idx, changes: diff });
          if (!get().playing) get().showIteration(idx, true);
          break;
        }
        case "status":
          push({ agent: (ev as { module_id?: string }).module_id ? `module:${(ev as { module_id?: string }).module_id}` : null, kind: "status", text: `${ev.stage.padEnd(7)} ${ev.message}` });
          break;
        case "candidate":
          push({ agent: null, kind: "candidate", text: `candidate ${ev.index + 1}  score ${ev.report.score.toFixed(0)}  ${ev.report.passed ? "PASS" : "FAIL"}` });
          break;
        case "final": {
          // make the final design the last scrubber node (and cancel any pending iteration tween)
          const its = get().iterations;
          const same = its.find((x) => x.design.name === ev.design.name && x.report.score === ev.report.score);
          const fin: Iteration = {
            seq: (its.at(-1)?.seq ?? 0) + 1, label: "final", agent: "run", design: ev.design, trace: ev.trace, report: ev.report,
            parentSeq: same?.seq ?? null, diff: same ? diffDesigns(same.design, ev.design) : [], t: now(),
          };
          if (!(its.at(-1)?.label === "final" && its.at(-1)?.design.name === ev.design.name)) set({ iterations: [...its, fin] });
          set({ current: get().iterations.length - 1 });
          push({ agent: null, kind: "final", text: `final "${ev.design.name}"  score ${ev.report.score.toFixed(0)}  ${ev.report.passed ? "PASS" : "FAIL"}`, iter: get().iterations.length - 1 });
          break;
        }
        case "error":
          push({ agent: null, kind: "error", text: ev.message });
          break;
        case "match":
          push({ agent: "matcher", kind: "match", text: `matched ${ev.summary?.matched ?? 0}/${ev.summary?.in_figure ?? 0} figure components` });
          break;
        case "module_done":
          push({ agent: `module:${ev.module_id}`, kind: "module", text: `module ${ev.module_id} done${ev.report ? `  score ${ev.report.score.toFixed(0)}` : ""}` });
          break;
        case "modules":
          push({ agent: "architect", kind: "module", text: `planned ${ev.modules?.length ?? 0} modules${ev.links?.length ? `, ${ev.links.length} fiber links` : ""}${ev.title ? ` · ${ev.title}` : ""}` });
          break;
        case "tokens":
          if (!get().agents[ev.agent_id]) upsertAgent(ev.agent_id, { state: "running", startedAt: now() });
          pushTokens(ev);
          break;
        case "figure":
          upsertAgent("fetch", { role: "vision", title: "Figure fetch", state: "done" });
          push({ agent: "fetch", kind: "tool", text: `figure  ${ev.url}${ev.citation ? `  · ${ev.citation}` : ""}` });
          break;
        case "module_failed":
          push({ agent: `module:${ev.module_id}`, kind: "error", text: `module ${ev.module_id} failed: ${ev.message}` });
          break;
        default:
          break;
      }
    },

    setOpen: (v) => set({ open: v }),
    setHeight: (h) => set({ height: Math.max(160, Math.min(window.innerHeight * 0.7, h)) }),
    setFilterAgent: (a) => set((s) => ({ filterAgent: s.filterAgent === a ? null : a })),
    toggleKind: (k) =>
      set((s) => {
        if (k === "all") return { kinds: null };
        const n = new Set(s.kinds ?? []);
        if (n.has(k)) n.delete(k);
        else n.add(k);
        return { kinds: n.size ? n : null };
      }),
    setSearch: (q) => set({ search: q }),

    showIteration: (index, animate = true) => {
      const raw = get().iterations[index];
      if (!raw) return;
      const curMods = useStore.getState().design?.modules;
      const it = !raw.design.modules?.length && curMods?.length ? { ...raw, design: { ...raw.design, modules: curMods } } : raw;
      set({ current: index });
      const main = useStore.getState();
      const prevTrace = main.trace;
      const changed = new Set(it.diff.map((c) => c.element_id));
      if (animate && prevTrace) {
        // tween parts first (positions come from the new trace), re-trace beams at the end
        useView.getState().startTween(changed, 520);
        main.showDesign(it.design, { trace: { ...it.trace, segments: prevTrace.segments }, report: it.report });
        setTimeout(() => {
          if (get().current === index) useStore.getState().showDesign(it.design, { trace: it.trace, report: it.report });
        }, 520);
      } else {
        main.showDesign(it.design, { trace: it.trace, report: it.report });
      }
    },
    step: (d) => {
      const n = get().iterations.length;
      if (!n) return;
      const cur = get().current ?? n - 1;
      get().showIteration(Math.max(0, Math.min(n - 1, cur + d)), true);
    },
    play: () => {
      const n = get().iterations.length;
      if (!n) return;
      get().stop();
      set({ playing: true });
      let i = 0;
      const tick = () => {
        if (!get().playing) return;
        get().showIteration(i, true);
        i += 1;
        if (i < get().iterations.length) playTimer = setTimeout(tick, 1000);
        else set({ playing: false });
      };
      tick();
    },
    stop: () => {
      if (playTimer) clearTimeout(playTimer);
      playTimer = null;
      set({ playing: false });
    },
  };
});

/** plain-text export of the visible log (copy-as-text) */
export function rowsAsText(rows: LogRow[]): string {
  return rows
    .map((r) => {
      const head = `+${(r.t / 1000).toFixed(1).padStart(6)}s  ${(r.agent ?? "run").padEnd(14)} ${r.kind.padEnd(9)} ${r.text}`;
      return r.changes?.length ? `${head}\n${r.changes.map((c) => `${" ".repeat(34)}${changeText(c)}`).join("\n")}` : head;
    })
    .join("\n");
}
