import { memo, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot, Boxes, Building2, ChevronLeft, ChevronRight, ClipboardList, Copy, GitCompare, Merge, Pause, PencilRuler, Play, ScanEye,
  Search, ShieldCheck, Sparkles, Wand2, Wrench, X,
} from "lucide-react";
import { useConsole, rowsAsText, type AgentInfo, type LogKind, type LogRow } from "../consoleStore";
import { changeText } from "../lib/diff";

const ROLE_ICON: Record<string, typeof Bot> = {
  planner: ClipboardList, designer: PencilRuler, verifier: ShieldCheck, repair: Wrench, vision: ScanEye, merge: Merge,
  synth: Sparkles, architect: Building2, module: Boxes, matcher: GitCompare, autofix: Wand2,
};
const KINDS: LogKind[] = ["agent", "llm", "thought", "tool", "iteration", "status", "error"];
const DOM_CAP = 500;

const kfmt = (n: number) => (n >= 10000 ? `${(n / 1000).toFixed(0)}k` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
const sfmt = (ms: number) => (ms >= 60000 ? `${Math.floor(ms / 60000)}m${String(Math.floor((ms % 60000) / 1000)).padStart(2, "0")}s` : `${(ms / 1000).toFixed(1)} s`);

function useTick(active: boolean, ms = 250) {
  const [, set] = useState(0);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => set((x) => x + 1), ms);
    return () => clearInterval(t);
  }, [active, ms]);
}

// ───────── iteration scrubber ─────────
function Scrubber() {
  const its = useConsole((s) => s.iterations);
  const current = useConsole((s) => s.current);
  const playing = useConsole((s) => s.playing);
  const { showIteration, step, play, stop } = useConsole.getState();
  const dragging = useRef(false);
  const trackRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = trackRef.current?.querySelector(".it-node.cur");
    el?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [current]);
  if (!its.length) return <div className="scrub empty muted">Iterations appear here as agents propose and repair designs.</div>;
  return (
    <div className="scrub">
      <button className="btn small" onClick={() => (playing ? stop() : play())} title="Replay the tuning history (1 iteration/s)">
        {playing ? <Pause size={13} /> : <Play size={13} />} {playing ? "Pause" : "Replay"}
      </button>
      <button className="icon-btn" onClick={() => step(-1)} aria-label="Previous iteration" title="Previous [←]"><ChevronLeft size={15} /></button>
      <div className="scrub-track" ref={trackRef} onPointerUp={() => (dragging.current = false)} onPointerLeave={() => (dragging.current = false)}>
        <div className="scrub-line" />
        {its.map((it, i) => (
          <button
            key={i}
            className={`it-node${i === current ? " cur" : ""}${it.report.passed ? " pass" : " fail"}${/autofix/i.test(it.label) ? " autofix" : ""}`}
            onPointerDown={(e) => { dragging.current = true; (e.target as HTMLElement).releasePointerCapture?.(e.pointerId); showIteration(i, true); }}
            onPointerEnter={() => { if (dragging.current && current !== i) showIteration(i, false); }}
            title={`#${it.seq} ${it.label} · score ${it.report.score.toFixed(0)} · ${it.report.passed ? "PASS" : "FAIL"} · ${it.diff.length} changes`}
          >
            <span className="dot" />
            <span className="it-label">{it.label} · {it.report.score.toFixed(0)}</span>
          </button>
        ))}
      </div>
      <button className="icon-btn" onClick={() => step(1)} aria-label="Next iteration" title="Next [→]"><ChevronRight size={15} /></button>
    </div>
  );
}

// ───────── roster ─────────
function AgentRow({ a, depth, now }: { a: AgentInfo; depth: number; now: number }) {
  const filter = useConsole((s) => s.filterAgent);
  const setFilter = useConsole((s) => s.setFilterAgent);
  const Icon = ROLE_ICON[a.role] ?? Bot;
  const el = a.state === "running" && a.startedAt != null ? now - a.startedAt : a.elapsedMs ?? (a.endedAt != null && a.startedAt != null ? a.endedAt - a.startedAt : null);
  return (
    <button className={`agent-row${filter === a.id ? " sel" : ""}`} style={{ paddingLeft: 8 + depth * 14 }} onClick={() => setFilter(a.id)} title={a.message ?? a.title}>
      <span className={`state-dot ${a.state}`} aria-label={a.state} />
      <Icon size={13} strokeWidth={1.7} className="role-ic" />
      <span className="ag-main">
        <span className="ag-title">{a.title}</span>
        <span className="ag-sub mono">{[a.model, a.thinking].filter(Boolean).join(" · ") || a.role}</span>
      </span>
      <span className="ag-num mono">
        <span>{el != null ? sfmt(el) : "—"}</span>
        <span className="muted">{a.calls ? `${kfmt(a.tin)}/${kfmt(a.tout)}/${kfmt(a.tthought)}` : ""}</span>
      </span>
    </button>
  );
}

function Roster() {
  const agents = useConsole((s) => s.agents);
  const startedAt = useConsole((s) => s.startedAt);
  const list = Object.values(agents).sort((a, b) => a.order - b.order);
  const anyRunning = list.some((a) => a.state === "running");
  useTick(anyRunning, 500);
  const now = Date.now() - startedAt;
  const ids = new Set(list.map((a) => a.id));
  const kids = new Map<string | null, AgentInfo[]>();
  for (const a of list) {
    const p = a.parent && ids.has(a.parent) ? a.parent : null;
    kids.set(p, [...(kids.get(p) ?? []), a]);
  }
  const out: { a: AgentInfo; d: number }[] = [];
  const walk = (p: string | null, d: number) => { for (const a of kids.get(p) ?? []) { out.push({ a, d }); walk(a.id, d + 1); } };
  walk(null, 0);
  return (
    <div className="roster">
      <div className="roster-head"><span>Agent</span><span className="mono">time · tok in/out/thought</span></div>
      {out.length === 0 && <div className="empty-hint" style={{ padding: 8 }}>No agents yet.</div>}
      {out.map(({ a, d }) => <AgentRow key={a.id} a={a} depth={d} now={now} />)}
    </div>
  );
}

// ───────── log ─────────
const Row = memo(function Row({ r }: { r: LogRow }) {
  const [open, setOpen] = useState(false);
  const show = useConsole.getState().showIteration;
  const current = useConsole((s) => s.current);
  const time = `+${(r.t / 1000).toFixed(1)}`;
  if (r.kind === "thought") {
    const long = r.text.length > 180;
    return (
      <div className="lrow thought" onClick={() => long && setOpen(!open)}>
        <span className="lt">{time}</span><span className="la">{r.agent ?? ""}</span><span className="lk">thought</span>
        <span className="lm">{open || !long ? r.text : `${r.text.slice(0, 180)}…`}{long && <span className="more">{open ? " less" : " more"}</span>}</span>
      </div>
    );
  }
  return (
    <div className={`lrow ${r.kind}${r.iter != null && r.iter === current ? " cur" : ""}`}>
      <span className="lt">{time}</span><span className="la">{r.agent ?? "run"}</span><span className="lk">{r.kind}</span>
      <span className="lm">
        {/^autofix/.test(r.text) || / autofix /.test(r.text) ? <Wand2 size={12} className="tool-ic" aria-label="autofix" /> : null}
        {r.text}
        {r.iter != null && <button className="btn small view-btn" onClick={() => show(r.iter!, true)}>view</button>}
        {r.changes && r.changes.length > 0 && (
          <span className="changes">
            {(open ? r.changes : r.changes.slice(0, 6)).map((c, i) => <span key={i} className={`chg ${c.op}`}>{changeText(c)}</span>)}
            {r.changes.length > 6 && <button className="link" onClick={() => setOpen(!open)}>{open ? "fewer" : `+${r.changes.length - 6} more`}</button>}
          </span>
        )}
      </span>
    </div>
  );
});

function Log() {
  const rows = useConsole((s) => s.rows);
  const agents = useConsole((s) => s.agents);
  const filterAgent = useConsole((s) => s.filterAgent);
  const kinds = useConsole((s) => s.kinds);
  const search = useConsole((s) => s.search);
  const [cap, setCap] = useState(DOM_CAP);
  const [hover, setHover] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    let sub: Set<string> | null = null;
    if (filterAgent) {
      // the selected agent plus its descendants
      sub = new Set([filterAgent]);
      let grew = true;
      while (grew) {
        grew = false;
        for (const a of Object.values(agents)) if (a.parent && sub.has(a.parent) && !sub.has(a.id)) { sub.add(a.id); grew = true; }
      }
    }
    const q = search.trim().toLowerCase();
    return rows.filter((r) =>
      (!sub || (r.agent != null && sub.has(r.agent))) &&
      (!kinds || kinds.has(r.kind) || (kinds.has("status") && ["candidate", "final", "match", "module"].includes(r.kind))) &&
      (!q || `${r.agent ?? ""} ${r.kind} ${r.text}`.toLowerCase().includes(q)));
  }, [rows, agents, filterAgent, kinds, search]);
  const visible = filtered.length > cap ? filtered.slice(-cap) : filtered;

  useEffect(() => {
    if (!hover && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [visible.length, visible.at(-1)?.text, hover]);

  return (
    <div className="log-pane">
      <LogToolbar rows={filtered} />
      <div className="log-scroll mono" ref={ref} onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
        {filtered.length > cap && (
          <button className="btn small load-earlier" onClick={() => setCap(cap + DOM_CAP)}>Load earlier ({filtered.length - cap} hidden)</button>
        )}
        {visible.map((r) => <Row key={r.i} r={r} />)}
        {filtered.length === 0 && <div className="empty-hint" style={{ padding: 8 }}>No log rows{rows.length ? " match the filter" : " yet"}.</div>}
      </div>
      {hover && <div className="paused-hint">autoscroll paused</div>}
    </div>
  );
}

function LogToolbar({ rows }: { rows: LogRow[] }) {
  const kinds = useConsole((s) => s.kinds);
  const toggle = useConsole((s) => s.toggleKind);
  const search = useConsole((s) => s.search);
  const setSearch = useConsole((s) => s.setSearch);
  const filterAgent = useConsole((s) => s.filterAgent);
  const setFilterAgent = useConsole((s) => s.setFilterAgent);
  const [copied, setCopied] = useState(false);
  return (
    <div className="log-tools">
      <button className={`chip${!kinds ? " active" : ""}`} onClick={() => toggle("all")}>all</button>
      {KINDS.map((k) => <button key={k} className={`chip${kinds?.has(k) ? " active" : ""}`} onClick={() => toggle(k)}>{k}</button>)}
      {filterAgent && <button className="chip active" onClick={() => setFilterAgent(filterAgent)} title="Clear agent filter">{filterAgent} <X size={11} /></button>}
      <span className="spacer" />
      <div className="search small">
        <Search size={12} />
        <input className="input" placeholder="Search log" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search log" />
      </div>
      <button className="btn small" onClick={() => { navigator.clipboard.writeText(rowsAsText(rows)); setCopied(true); setTimeout(() => setCopied(false), 1200); }} title="Copy the filtered log as text">
        <Copy size={12} /> {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

function Summary() {
  const totals = useConsole((s) => s.totals);
  const agents = useConsole((s) => s.agents);
  const startedAt = useConsole((s) => s.startedAt);
  const endedAt = useConsole((s) => s.endedAt);
  const rows = useConsole((s) => s.rows.length);
  const list = Object.values(agents);
  const running = list.filter((a) => a.state === "running").length;
  const done = list.filter((a) => a.state === "done").length;
  useTick(running > 0 && endedAt == null, 500);
  const wall = rows ? (endedAt ?? Date.now() - startedAt) : 0;
  return (
    <div className="con-summary mono">
      <span>LLM calls <b>{totals.calls}</b></span>
      <span>tokens in <b>{kfmt(totals.tin)}</b> out <b>{kfmt(totals.tout)}</b> thought <b>{kfmt(totals.tthought)}</b></span>
      <span>wall <b>{sfmt(wall)}</b></span>
      <span>agents <b className={running ? "run" : ""}>{running}</b> running · <b>{done}</b>/{list.length} done</span>
    </div>
  );
}

export default function Console() {
  const open = useConsole((s) => s.open);
  const height = useConsole((s) => s.height);
  const setHeight = useConsole((s) => s.setHeight);
  const setOpen = useConsole((s) => s.setOpen);
  if (!open) return null;
  const startDrag = (e: React.PointerEvent) => {
    const y0 = e.clientY, h0 = height;
    const move = (ev: PointerEvent) => setHeight(h0 - (ev.clientY - y0));
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  return (
    <section className="console" style={{ height }} aria-label="Agent console">
      <div className="con-resize" onPointerDown={startDrag} role="separator" aria-orientation="horizontal" aria-label="Resize console" />
      <div className="con-head">
        <span className="section-title" style={{ margin: 0 }}>Agent console</span>
        <Summary />
        <span className="spacer" />
        <button className="icon-btn" onClick={() => setOpen(false)} aria-label="Close console" title="Close [`]"><X size={14} /></button>
      </div>
      <Scrubber />
      <div className="con-body">
        <Roster />
        <Log />
      </div>
    </section>
  );
}
