import { useEffect, useRef, useState } from "react";
import { CircleStop, ImagePlus, LoaderCircle, Play, ScanSearch } from "lucide-react";
import { useStore, type Candidate } from "../store";
import { useWlColor } from "../lib/theme";
import { DEFAULT_BASEPLATE } from "../types";

const EXAMPLE_GOALS = [
  "Rb-87 D2 line: deliver ≥ 8 mW of +110 MHz shifted 780 nm light into a single-mode fiber, with a 5 % pickoff for saturated absorption spectroscopy.",
  "532 nm Mach–Zehnder interferometer on a 14×10 inch breadboard with two output photodiodes.",
  "Combine 461 nm and 689 nm Sr beams on a dichroic into one fiber.",
];

export function Thumb({ c, w = 76, h = 44 }: { c: Candidate; w?: number; h?: number }) {
  const wl = useWlColor();
  const bp = { ...DEFAULT_BASEPLATE, ...(c.design.baseplate ?? {}) };
  const s = Math.min(w / bp.width_mm, h / bp.height_mm);
  const ox = (w - bp.width_mm * s) / 2, oy = (h - bp.height_mm * s) / 2;
  const X = (x: number) => ox + x * s, Y = (y: number) => h - oy - y * s;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden>
      <rect x={X(0)} y={Y(bp.height_mm)} width={bp.width_mm * s} height={bp.height_mm * s} style={{ fill: "var(--line)" }} />
      {c.trace.segments.map((sg) => (
        <line key={sg.id} x1={X(sg.start[0])} y1={Y(sg.start[1])} x2={X(sg.end[0])} y2={Y(sg.end[1])} stroke={wl(sg.wavelength_nm)} strokeWidth={1} />
      ))}
      {c.trace.elements.filter((e) => e.position).map((e) => (
        <rect key={e.id} x={X(e.position![0]) - 1.2} y={Y(e.position![1]) - 1.2} width={2.4} height={2.4} style={{ fill: "var(--text-2)" }} />
      ))}
    </svg>
  );
}

function fmtT(ms: number) {
  return `${(ms / 1000).toFixed(1)} s`;
}

export default function AgentPanel() {
  const agent = useStore((s) => s.agent);
  const runDesign = useStore((s) => s.runDesign);
  const runReproduce = useStore((s) => s.runReproduce);
  const stop = useStore((s) => s.stopAgent);
  const loadCandidate = useStore((s) => s.loadCandidate);
  const [goal, setGoal] = useState(EXAMPLE_GOALS[0]);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [over, setOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!agent.running) return;
    const t = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(t);
  }, [agent.running]);
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [agent.log.length]);

  const pick = (f: File | undefined | null) => {
    if (!f || !f.type.startsWith("image/")) return;
    setFile(f);
    setPreview((old) => { if (old) URL.revokeObjectURL(old); return URL.createObjectURL(f); });
  };

  // durations: time until the next log row
  const rows = agent.log.map((r, i) => ({ ...r, dur: (agent.log[i + 1]?.t ?? (agent.running ? now - agent.startedAt : r.t)) - r.t }));
  const cands = [...agent.candidates].sort((a, b) => (a.final ? 1 : 0) - (b.final ? 1 : 0) || a.index - b.index);

  return (
    <>
      <div className="section">
        <div className="section-title">1 · Goal</div>
        <label className="field-label" htmlFor="goal">Describe the experiment you want</label>
        <textarea id="goal" className="input" rows={4} value={goal} onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && goal.trim()) runDesign(goal.trim()); }} />
        <div className="row mt8">
          <select className="select" style={{ flex: 1, minWidth: 0 }} value="" onChange={(e) => e.target.value && setGoal(e.target.value)} aria-label="Example goals">
            <option value="">Example goals…</option>
            {EXAMPLE_GOALS.map((g) => <option key={g} value={g}>{g.slice(0, 60)}…</option>)}
          </select>
          <button className="btn primary" disabled={agent.running || !goal.trim()} onClick={() => runDesign(goal.trim())}>
            <Play size={14} /> Design
          </button>
        </div>
      </div>

      <div className="section">
        <div className="section-title">or · Reproduce from paper figure</div>
        <div
          className={`dropzone${over ? " over" : ""}`}
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files?.[0]); }}
          role="button"
          tabIndex={0}
        >
          {preview ? <img src={preview} alt="figure preview" /> : <ImagePlus size={22} strokeWidth={1.4} />}
          <div className="dz-text">
            <b>{file ? file.name : "Drop a setup figure (PNG/JPG)"}</b>
            <span className="muted">{file ? `${(file.size / 1024).toFixed(0)} kB · click to replace` : "or click to browse"}</span>
          </div>
          <input ref={fileRef} type="file" accept="image/*" hidden onChange={(e) => pick(e.target.files?.[0])} />
        </div>
        <input className="input mt8" placeholder="Notes (e.g. wavelength, plate size, which beams matter)" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <div className="row end mt8">
          <button className="btn" disabled={!file || agent.running} onClick={() => file && runReproduce(file, notes)}>
            <ScanSearch size={14} /> Reproduce
          </button>
        </div>
      </div>

      <div className="section">
        <div className="section-title">
          2 · Run log
          <span className="right-slot mono">{agent.startedAt ? fmtT((agent.running ? now : agent.startedAt + (agent.log.at(-1)?.t ?? 0)) - agent.startedAt) : ""}</span>
        </div>
        <div className="log" ref={logRef} style={{ maxHeight: 168, overflow: "auto" }}>
          {rows.length === 0 && <div className="log-empty">No run yet. Start a design or a figure reproduction.</div>}
          {rows.map((r, i) => (
            <div key={i} className={`log-row ${r.level}`}>
              <span className="t">{fmtT(r.t)}</span>
              <span className="stage">{r.stage}</span>
              <span className="msg">{r.message}</span>
              <span className="dur">{r.dur > 50 && i < rows.length - 1 ? fmtT(r.dur) : ""}</span>
            </div>
          ))}
        </div>
        {agent.running && (
          <div className="running-line">
            <LoaderCircle size={13} className="spin" /> Running…
            <span className="spacer" />
            <button className="btn small" onClick={stop}><CircleStop size={13} /> Stop</button>
          </div>
        )}
      </div>

      <div className="section">
        <div className="section-title">3 · Candidates <span className="right-slot">{cands.length ? "click to load" : ""}</span></div>
        {cands.length === 0 && <div className="empty-hint">Candidates appear here as the agent verifies them.</div>}
        <div className="cands">
          {cands.map((c) => (
            <button key={c.final ? "final" : c.index} className={`cand${agent.active === (c.final ? -1 : c.index) ? " active" : ""}`} onClick={() => loadCandidate(c.final ? -1 : c.index)}>
              <Thumb c={c} />
              <div style={{ minWidth: 0 }}>
                <div className="c-name">{c.final ? "Final design" : `Candidate ${c.index + 1}`}</div>
                <div className="c-sub">{(c.design.elements ?? []).length} el · {c.trace.segments.length} seg · {(c.report.metrics.delivered_mw ?? 0).toFixed(1)} mW</div>
                <span className={`badge ${c.report.passed ? "pass" : "fail"}`} style={{ marginTop: 3 }}>{c.report.passed ? "PASS" : "FAIL"}</span>
              </div>
              <div className="c-score">{c.report.score.toFixed(0)}<div className="muted" style={{ fontSize: 10.5 }}>score</div></div>
            </button>
          ))}
        </div>
      </div>
    </>
  );
}
