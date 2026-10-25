import { useEffect, useRef, useState } from "react";
import { create } from "zustand";
import { ExternalLink, FileText, Maximize2, Minimize2, Minus, X } from "lucide-react";
import { useDemo } from "../demoStore";

export interface PipPaper { arxiv_id: string; title: string; abs_url: string }
type Mode = "normal" | "min" | "max";

export const usePip = create<{ paper: PipPaper | null; mode: Mode; open: (p: PipPaper) => void; close: () => void; setMode: (m: Mode) => void }>((set) => ({
  paper: null,
  mode: "normal",
  open: (p) => set({ paper: p, mode: "normal" }),
  close: () => set({ paper: null }),
  setMode: (m) => set({ mode: m }),
}));

const isArxiv = (p: PipPaper) => /arxiv\.org/.test(p.abs_url) || /^\d{4}\.\d{4,5}(v\d+)?$/.test(p.arxiv_id);

/** floating picture-in-picture paper viewer (same-origin PDF proxy) */
export default function PaperPip() {
  const { paper, mode, close, setMode } = usePip();
  const director = useDemo((d) => d.director);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null); // top-left, px; null = default corner
  const drag = useRef<{ dx: number; dy: number } | null>(null);
  useEffect(() => { setPos(null); }, [paper?.arxiv_id]);
  if (!paper) return null;
  const eff: Mode = director ? "min" : mode;
  const label = `${paper.title}${isArxiv(paper) ? ` · arXiv:${paper.arxiv_id}` : ""}`;
  if (eff === "min") {
    return (
      <button className="pip-pill" onClick={() => setMode("normal")} title={label}>
        <FileText size={13} /> <span>{paper.title}</span>
      </button>
    );
  }
  const W = eff === "max" ? Math.round(window.innerWidth * 0.6) : 360;
  const H = eff === "max" ? Math.round(window.innerHeight * 0.6 * 1.25) : 460;
  const style: React.CSSProperties = pos && eff === "normal"
    ? { left: pos.x, top: pos.y, width: W, height: H }
    : { right: 16, bottom: 40, width: W, height: Math.min(H, window.innerHeight - 100) };
  const onDown = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest("button,a")) return;
    const box = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect();
    drag.current = { dx: e.clientX - box.left, dy: e.clientY - box.top };
    const move = (ev: PointerEvent) => {
      if (!drag.current) return;
      setPos({ x: Math.max(0, Math.min(window.innerWidth - 120, ev.clientX - drag.current.dx)), y: Math.max(0, Math.min(window.innerHeight - 40, ev.clientY - drag.current.dy)) });
    };
    const up = () => { drag.current = null; window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    if (mode !== "normal") setMode("normal");
  };
  return (
    <div className="pip" style={style} role="dialog" aria-label={`Paper: ${paper.title}`}>
      <div className="pip-head" onPointerDown={onDown}>
        <FileText size={13} />
        <span className="pip-title" title={label}>{label}</span>
        <a className="icon-btn" href={paper.abs_url} target="_blank" rel="noreferrer" title="Open on arXiv" aria-label="Open on arXiv"><ExternalLink size={13} /></a>
        <button className="icon-btn" onClick={() => setMode("min")} title="Minimize" aria-label="Minimize"><Minus size={13} /></button>
        <button className="icon-btn" onClick={() => setMode(mode === "max" ? "normal" : "max")} title={mode === "max" ? "Restore" : "Expand"} aria-label="Expand">
          {mode === "max" ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
        </button>
        <button className="icon-btn" onClick={close} title="Close" aria-label="Close"><X size={13} /></button>
      </div>
      {isArxiv(paper) ? (
        <iframe className="pip-frame" src={`/api/papers/pdf/${encodeURIComponent(paper.arxiv_id)}#view=FitH`} title={paper.title} />
      ) : (
        <div className="pip-empty">No PDF for this source. <a href={paper.abs_url} target="_blank" rel="noreferrer">Open the source page</a>.</div>
      )}
    </div>
  );
}
