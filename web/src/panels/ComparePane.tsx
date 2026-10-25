import { CircleCheck, CircleMinus, CirclePlus, X } from "lucide-react";
import { useStore } from "../store";
import { SHORT } from "../lib/beam";

/** Source figure + what the vision step extracted + the figure↔design component match table. */
export default function ComparePane() {
  const url = useStore((s) => s.agent.figureUrl);
  const extraction = useStore((s) => s.agent.extraction);
  const match = useStore((s) => s.agent.match);
  const select = useStore((s) => s.select);
  const setCompare = useStore((s) => s.setCompare);
  if (!url) return null;
  const counts = extraction ? Object.entries(extraction).filter(([, v]) => Array.isArray(v) && (v as unknown[]).some((x) => typeof x === "object" && x !== null)).map(([k, v]) => [k, (v as unknown[]).length] as const) : [];
  const ok = match && match.summary.matched === match.summary.in_figure;
  return (
    <div className="fig-pane">
      <div className="fig-pane-head">
        <span className="section-title" style={{ margin: 0 }}>Source figure</span>
        <span className="spacer" />
        <button className="icon-btn" onClick={() => setCompare(false)} aria-label="Close comparison" title="Close comparison"><X size={14} /></button>
      </div>
      <div className="fig-img"><img src={url} alt="Uploaded paper figure" /></div>
      <div className="fig-body">
        {counts.length > 0 && (
          <div className="extract-counts">
            <span className="muted">Extracted</span>
            {counts.map(([k, n]) => <span key={k} className="pill"><b className="mono">{n}</b>&nbsp;{k}</span>)}
          </div>
        )}
        {match ? (
          <>
            <div className={`match-head ${ok ? "ok" : "partial"}`}>
              Matched <b className="mono">{match.summary.matched}/{match.summary.in_figure}</b> components
            </div>
            <table className="match">
              <thead><tr><th /><th>Figure label</th><th>Type</th><th>Design id</th></tr></thead>
              <tbody>
                {match.rows.map((r, i) => (
                  <tr key={i} className={r.design_id ? "clickable" : ""} onClick={() => r.design_id && select({ kind: "element", id: r.design_id })}>
                    <td>
                      {r.status === "matched" ? <CircleCheck size={13} className="sev-ok" aria-label="matched" /> : r.status === "missing" ? <CircleMinus size={13} className="sev-error" aria-label="missing from design" /> : <CirclePlus size={13} className="sev-warning" aria-label="extra in design" />}
                    </td>
                    <td title={r.figure_label}>{r.figure_label}</td>
                    <td className="muted">{SHORT[r.figure_type] ?? r.figure_type}</td>
                    <td className="mono" title={r.design_id ?? ""}>{r.design_id ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <div className="empty-hint">The component match table appears when the agent compares the figure with its design.</div>
        )}
      </div>
    </div>
  );
}
