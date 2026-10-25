import { useEffect, useState } from "react";
import { Copy, Download, LoaderCircle, X } from "lucide-react";
import { useStore } from "../store";
import { exportPyOpticL } from "../api";

export default function ExportModal() {
  const open = useStore((s) => s.exportOpen);
  const setOpen = useStore((s) => s.setExportOpen);
  const design = useStore((s) => s.design);
  const [code, setCode] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!open || !design) return;
    setCode(null); setErr(null);
    exportPyOpticL(design).then(setCode, (e) => setErr(String(e)));
  }, [open, design]);
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, setOpen]);
  if (!open || !design) return null;
  const fname = `${design.name.replace(/\W+/g, "_")}_pyopticl.py`;
  return (
    <div className="modal-back" onClick={() => setOpen(false)}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="PyOpticL export">
        <div className="modal-head">
          <h3>Export · PyOpticL</h3>
          <span className="mono muted" style={{ fontSize: 12 }}>{fname}</span>
          <span className="spacer" />
          <button className="btn small" disabled={!code} onClick={() => { navigator.clipboard.writeText(code ?? ""); setCopied(true); setTimeout(() => setCopied(false), 1200); }}>
            <Copy size={13} /> {copied ? "Copied" : "Copy"}
          </button>
          <button className="btn small" disabled={!code} onClick={() => {
            const a = document.createElement("a");
            a.href = URL.createObjectURL(new Blob([code ?? ""], { type: "text/x-python" }));
            a.download = fname; a.click(); URL.revokeObjectURL(a.href);
          }}>
            <Download size={13} /> Download .py
          </button>
          <button className="icon-btn" onClick={() => setOpen(false)} aria-label="Close"><X size={15} /></button>
        </div>
        <div className="modal-body">
          {err ? <pre style={{ color: "var(--err)" }}>{err}</pre> : code == null ? <pre className="muted"><LoaderCircle size={13} className="spin" /> generating…</pre> : <pre>{code}</pre>}
        </div>
      </div>
    </div>
  );
}
