import { useEffect, useRef, useState } from "react";
import { create } from "zustand";
import { Download, ExternalLink, FileText, Maximize2, Minimize2, Minus, X } from "lucide-react";
import { useDemo } from "../demoStore";

export interface PipPaper { arxiv_id: string; title: string; abs_url: string }
type Mode = "normal" | "min" | "max";

interface PipState {
  paper: PipPaper | null; mode: Mode; tab: "paper" | "doc"; docUrl: string | null; docName: string;
  open: (p: PipPaper) => void; close: () => void; setMode: (m: Mode) => void; setTab: (t: "paper" | "doc") => void; showDoc: (url: string, name: string) => void;
}
export const usePip = create<PipState>((set) => ({
  paper: null,
  mode: "normal",
  tab: "paper",
  docUrl: null,
  docName: "",
  open: (p) => set({ paper: p, mode: "normal", tab: "paper" }),
  close: () => set({ paper: null, docUrl: null }),
  setMode: (m) => set({ mode: m }),
  setTab: (t) => set({ tab: t }),
  showDoc: (url, name) => set({ docUrl: url, docName: name, tab: "doc", mode: "max" }),
}));

const isArxiv = (p: PipPaper) => /arxiv\.org/.test(p.abs_url) || /^\d{4}\.\d{4,5}(v\d+)?$/.test(p.arxiv_id);

/** floating picture-in-picture paper viewer (same-origin PDF proxy) */
export default function PaperPip() {
  const { paper, mode, close, setMode, tab, setTab, docUrl, docName } = usePip();
  const director = useDemo((d) => d.director);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null); // top-left, px; null = default corner
  const drag = useRef<{ dx: number; dy: number } | null>(null);
  useEffect(() => { setPos(null); }, [paper?.arxiv_id]);
  if (!paper && !docUrl) return null;
  const eff: Mode = director && tab !== "doc" ? "min" : mode;
  const showDocTab = tab === "doc" && !!docUrl || !paper;
  const label = paper ? `${paper.title}${isArxiv(paper) && !paper.title.includes(paper.arxiv_id) ? ` · arXiv:${paper.arxiv_id}` : ""}` : `Build document · ${docName}`;
  if (eff === "min") {
    return (
      <button className="pip-pill" onClick={() => setMode("normal")} title={label}>
        <FileText size={13} /> <span>{paper?.title ?? label}</span>
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
    <div className="pip" style={style} role="dialog" aria-label={label}>
      <div className="pip-head" onPointerDown={onDown}>
        <FileText size={13} />
        {docUrl && paper ? (
          <span className="pip-tabs">
            <button className={`pip-tab${!showDocTab ? " active" : ""}`} onClick={() => setTab("paper")}>Paper</button>
            <button className={`pip-tab${showDocTab ? " active" : ""}`} onClick={() => setTab("doc")}>Build document</button>
          </span>
        ) : null}
        <span className="pip-title" title={label}>{showDocTab ? `Build document · ${docName}` : label}</span>
        {showDocTab && docUrl && <a className="btn small" href={docUrl} download={`${docName || "beamline"}_build.pdf`} title="Download PDF"><Download size={12} /> PDF</a>}
        {paper && <a className="icon-btn" href={paper.abs_url} target="_blank" rel="noreferrer" title="Open on arXiv" aria-label="Open on arXiv"><ExternalLink size={13} /></a>}
        <button className="icon-btn" onClick={() => setMode("min")} title="Minimize" aria-label="Minimize"><Minus size={13} /></button>
        <button className="icon-btn" onClick={() => setMode(mode === "max" ? "normal" : "max")} title={mode === "max" ? "Restore" : "Expand"} aria-label="Expand">
          {mode === "max" ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
        </button>
        <button className="icon-btn" onClick={close} title="Close" aria-label="Close"><X size={13} /></button>
      </div>
      {showDocTab && docUrl ? (
        <iframe className="pip-frame" src={docUrl} title="Build document" />
      ) : paper && isArxiv(paper) ? (
        <iframe className="pip-frame" src={`/api/papers/pdf/${encodeURIComponent(paper.arxiv_id)}#view=FitH`} title={paper.title} />
      ) : paper ? (
        <div className="pip-empty">No PDF for this source. <a href={paper.abs_url} target="_blank" rel="noreferrer">Open the source page</a>.</div>
      ) : null}
    </div>
  );
}
