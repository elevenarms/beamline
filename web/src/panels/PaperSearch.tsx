import { useState } from "react";
import { ExternalLink, FileText, Hammer, LoaderCircle, Search, X } from "lucide-react";
import { usePip } from "./PaperPip";
import { useStore } from "../store";
import * as api from "../api";
import type { Paper, PaperFigure } from "../types";

export default function PaperSearch() {
  const running = useStore((s) => s.agent.running);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [papers, setPapers] = useState<Paper[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pick, setPick] = useState<{ paper: Paper; fig: PaperFigure } | null>(null);

  const search = async () => {
    if (!q.trim()) return;
    setBusy(true); setErr(null);
    try {
      const res = await api.searchPapers(q.trim(), 6);
      setPapers(res.map((p) => ({ ...p, figures: [...p.figures].sort((a, b) => b.setup_score - a.setup_score) })));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const build = () => {
    if (!pick) return;
    const { paper, fig } = pick;
    const citation = `${paper.authors.slice(0, 3).join(", ")}${paper.authors.length > 3 ? " et al." : ""}, "${paper.title}"${paper.year ? ` (${paper.year})` : ""}${paper.arxiv_id && !paper.abs_url.includes("wikimedia") ? `, arXiv:${paper.arxiv_id}` : ""}`;
    setPick(null);
    usePip.getState().open({ arxiv_id: paper.arxiv_id, title: paper.title, abs_url: paper.abs_url });
    useStore.getState().runReproduceUrl(fig.url, fig.caption, citation, paper.license);
  };

  return (
    <div className="section find-paper">
      <div className="section-title">1 · Find a paper</div>
      <label className="field-label" htmlFor="paper-q">Search arXiv for an optical setup figure to build</label>
      <div className="row">
        <div className="search" style={{ flex: 1 }}>
          <Search size={13} />
          <input id="paper-q" className="input" autoFocus value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} placeholder="Search papers…" aria-label="Search papers" />
        </div>
        <button className="btn" onClick={search} disabled={busy}>{busy ? <LoaderCircle size={13} className="spin" /> : <Search size={13} />} Search</button>
      </div>
      {err && <div className="json-err mt8">{err}</div>}
      {papers && papers.length === 0 && <div className="empty-hint mt8">No papers found.</div>}
      {papers && papers.length > 0 && (
        <div className="papers">
          {papers.map((p) => (
            <div key={p.arxiv_id} className="paper">
              <div className="paper-title" title={p.title}>{p.title}</div>
              <div className="paper-meta">
                <span className="paper-authors" title={p.authors.join(", ")}>{p.authors.slice(0, 3).join(", ")}{p.authors.length > 3 ? " et al." : ""}</span>
                {p.year && <span className="mono">{p.year}</span>}
                {p.license && <span className="lic">{p.license}</span>}
                <button className="btn small" onClick={() => usePip.getState().open({ arxiv_id: p.arxiv_id, title: p.title, abs_url: p.abs_url })} title="View paper"><FileText size={12} /> View paper</button>
                <a href={p.abs_url} target="_blank" rel="noreferrer" className="icon-btn" aria-label="Open source page" title="Open source page"><ExternalLink size={12} /></a>
              </div>
              {p.figures.length > 0 && (
                <div className="fig-strip">
                  {p.figures.slice(0, 4).map((f) => (
                    <button key={f.id} className="fig-thumb" onClick={() => setPick({ paper: p, fig: f })} title={f.caption}>
                      <img src={f.url} alt={f.caption.slice(0, 80)} loading="lazy" />
                      <span className="mono">{f.setup_score.toFixed(2)}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {pick && (
        <div className="modal-back" onClick={() => setPick(null)}>
          <div className="modal fig-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Figure preview">
            <div className="modal-head">
              <h3 title={pick.paper.title}>{pick.paper.title}</h3>
              <span className="spacer" />
              <button className="btn primary" onClick={build} disabled={running}><Hammer size={14} /> Build this setup</button>
              <button className="icon-btn" onClick={() => setPick(null)} aria-label="Close"><X size={15} /></button>
            </div>
            <div className="modal-body fig-modal-body">
              <img src={pick.fig.url} alt={pick.fig.caption.slice(0, 80)} />
              <p className="fig-caption">{pick.fig.caption}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
