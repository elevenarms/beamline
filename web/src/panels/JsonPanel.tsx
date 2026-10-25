import { useEffect, useState } from "react";
import { useStore } from "../store";
import type { Design } from "../types";

export default function JsonPanel() {
  const design = useStore((s) => s.design);
  const replace = useStore((s) => s.replaceDesign);
  const [txt, setTxt] = useState("");
  const [dirty, setDirty] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!dirty) setTxt(design ? JSON.stringify(design, null, 2) : "");
  }, [design, dirty]);
  const apply = () => {
    try {
      const d = JSON.parse(txt) as Design;
      if (!d || !Array.isArray(d.sources)) throw new Error("Design needs a sources array");
      replace(d);
      setDirty(false);
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <div className="json-wrap">
      <textarea className="json-area" spellCheck={false} value={txt} aria-label="Design JSON"
        onChange={(e) => { setTxt(e.target.value); setDirty(true); }}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) apply(); }} />
      {err && <div className="json-err">{err}</div>}
      <div className="row end">
        <span className="muted" style={{ marginRight: "auto", fontSize: 12 }}>{dirty ? "Edited · ⌘↵ to apply" : "In sync with canvas"}</span>
        <button className="btn small" disabled={!dirty} onClick={() => { setDirty(false); setErr(null); }}>Revert</button>
        <button className="btn small primary" disabled={!dirty} onClick={apply}>Apply &amp; trace</button>
      </div>
    </div>
  );
}
