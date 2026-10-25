import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, CircleX, Crosshair, Eye, EyeOff, Search, TriangleAlert } from "lucide-react";
import { useStore } from "../store";
import { useView } from "../scene/viewStore";
import { SHORT } from "../lib/beam";
import type { Design, VerifyReport } from "../types";

export interface ModuleCounts { error: number; warning: number }

/** Map every check to a module id via its element's / segment's source group. */
export function checkModuleIndex(design: Design | null, trace: ReturnType<typeof useStore.getState>["trace"]) {
  const elGroup = new Map<string, string | null>();
  for (const e of design?.elements ?? []) elGroup.set(e.id, e.group ?? null);
  for (const s of design?.sources ?? []) elGroup.set(s.id, s.group ?? null);
  const segGroup = new Map<string, string | null>();
  for (const s of trace?.segments ?? []) segGroup.set(s.id, elGroup.get(s.source_id) ?? null);
  return (c: VerifyReport["checks"][number]) => (c.element_id ? elGroup.get(c.element_id) : c.segment_id ? segGroup.get(c.segment_id) : null) ?? null;
}

export default function OutlinePanel() {
  const design = useStore((s) => s.design);
  const trace = useStore((s) => s.trace);
  const report = useStore((s) => s.report);
  const selected = useStore((s) => s.selected);
  const select = useStore((s) => s.select);
  const solo = useStore((s) => s.soloModule);
  const setSolo = useStore((s) => s.setSoloModule);
  const focus = useView((v) => v.focus);
  const focusBox = useView((v) => v.focusBox);
  const [q, setQ] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const posById = useMemo(() => new Map((trace?.elements ?? []).map((p) => [p.id, p.position])), [trace]);
  const elSev = useMemo(() => {
    const m = new Map<string, "error" | "warning">();
    for (const c of report?.checks ?? []) {
      if (!c.element_id || c.severity === "info") continue;
      if (c.severity === "error" || !m.has(c.element_id)) m.set(c.element_id, c.severity);
    }
    return m;
  }, [report]);
  const modCounts = useMemo(() => {
    const idx = checkModuleIndex(design, trace);
    const m = new Map<string, ModuleCounts>();
    for (const c of report?.checks ?? []) {
      if (c.severity === "info") continue;
      const g = idx(c) ?? "__none";
      const v = m.get(g) ?? { error: 0, warning: 0 };
      v[c.severity] += 1;
      m.set(g, v);
    }
    return m;
  }, [design, trace, report]);

  if (!design) return <div className="section empty-hint">No design loaded.</div>;

  const ql = q.trim().toLowerCase();
  const rows = [
    ...design.sources.map((s) => ({ id: s.id, kind: "source" as const, type: "source", label: s.label ?? "", group: s.group ?? null })),
    ...(design.elements ?? []).map((e) => ({ id: e.id, kind: "element" as const, type: e.type, label: e.label ?? "", group: e.group ?? null })),
  ].filter((r) => !ql || `${r.id} ${r.label} ${r.type} ${SHORT[r.type] ?? ""}`.toLowerCase().includes(ql));
  const modules = [...(design.modules ?? []).map((m) => ({ id: m.id, title: m.title || m.id, region: m.region as [number, number, number, number] | null }))];
  const known = new Set(modules.map((m) => m.id));
  if (rows.some((r) => !r.group || !known.has(r.group))) modules.push({ id: "__none", title: modules.length ? "Ungrouped" : "All components", region: null });

  return (
    <div className="outline">
      <div className="section" style={{ paddingBottom: 8 }}>
        <div className="search">
          <Search size={13} />
          <input className="input" placeholder="Filter by id, type or label" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter components" />
        </div>
        {solo && (
          <div className="row mt8" style={{ fontSize: 12 }}>
            <span className="muted">Solo: <b className="mono">{solo}</b> (others dimmed)</span>
            <span className="spacer" />
            <button className="btn small" onClick={() => setSolo(null)}>Show all</button>
          </div>
        )}
      </div>
      {modules.map((m) => {
        const items = rows.filter((r) => (m.id === "__none" ? !r.group || !known.has(r.group) : r.group === m.id));
        if (ql && items.length === 0) return null;
        const open = !collapsed[m.id] || !!ql;
        const cnt = modCounts.get(m.id);
        return (
          <div key={m.id} className={`tree-mod${solo && solo !== m.id ? " dimmed" : ""}`}>
            <div className="tree-head">
              <button className="icon-btn" onClick={() => setCollapsed((c) => ({ ...c, [m.id]: open }))} aria-label={open ? "Collapse" : "Expand"}>
                {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>
              <button className="tree-title" onClick={() => m.region && focusBox(...m.region)} title="Zoom to module">
                {m.title}
              </button>
              <span className="tree-count mono">{items.length}</span>
              {cnt?.error ? <span className="tree-sev sev-error"><CircleX size={12} />{cnt.error}</span> : null}
              {cnt?.warning ? <span className="tree-sev sev-warning"><TriangleAlert size={12} />{cnt.warning}</span> : null}
              {m.region && (
                <>
                  <button className="icon-btn" onClick={() => focusBox(...m.region!)} aria-label="Zoom to module" title="Zoom to module"><Crosshair size={13} /></button>
                  <button className={`icon-btn${solo === m.id ? " on" : ""}`} onClick={() => setSolo(solo === m.id ? null : m.id)} aria-label="Solo module" title={solo === m.id ? "Show all modules" : "Solo (dim others)"}>
                    {solo === m.id ? <EyeOff size={13} /> : <Eye size={13} />}
                  </button>
                </>
              )}
            </div>
            {open && (
              <div className="tree-items">
                {items.map((r) => {
                  const sev = elSev.get(r.id);
                  const isSel = selected?.id === r.id;
                  return (
                    <button
                      key={r.id}
                      className={`tree-item${isSel ? " sel" : ""}`}
                      onClick={() => select({ kind: r.kind, id: r.id })}
                      onDoubleClick={() => {
                        const p = r.kind === "source" ? design.sources.find((s) => s.id === r.id)?.position : posById.get(r.id);
                        if (p) focus(p[0], p[1], 20);
                      }}
                      title="Click to select, double-click to zoom"
                    >
                      <span className="mono ti-id">{r.id}</span>
                      <span className="ti-type">{r.kind === "source" ? "Source" : SHORT[r.type] ?? r.type}</span>
                      {sev === "error" && <CircleX size={12} className="sev-error" />}
                      {sev === "warning" && <TriangleAlert size={12} className="sev-warning" />}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
