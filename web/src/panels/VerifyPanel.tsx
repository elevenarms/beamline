import { useMemo, useState } from "react";
import { CircleCheck, CircleX, Info, LoaderCircle, TriangleAlert } from "lucide-react";
import { useConsole } from "../consoleStore";
import { useDemo } from "../demoStore";
import { useStore } from "../store";
import type { Check } from "../types";
import { mW, pct } from "../lib/format";
import { checkModuleIndex } from "./OutlinePanel";

function SevIcon({ s }: { s: Check["severity"] }) {
  if (s === "error") return <CircleX size={14} className="sev-error" aria-label="error" />;
  if (s === "warning") return <TriangleAlert size={14} className="sev-warning" aria-label="warning" />;
  return <Info size={14} className="sev-info" aria-label="info" />;
}

function valueVsLimit(c: Check): string {
  if (c.value == null) return "";
  const msg = c.message.toLowerCase();
  const isPct = /clip|coupling|overlap|efficien|fraction|%/.test(c.id + " " + msg) && c.value <= 1 && (c.limit == null || c.limit <= 1);
  const isMw = !isPct && /stray|power|mw/.test(c.id + " " + msg);
  const isMm = !isPct && !isMw && /collision|distance|apart|offset| mm/.test(c.id + " " + msg);
  const f = (v: number) => (isPct ? pct(v, 1) : isMw ? mW(v) : isMm ? `${v.toFixed(1)} mm` : v.toPrecision(3));
  return c.limit != null ? `${f(c.value)} / ${f(c.limit)}` : f(c.value);
}

/** "cooling_422.dist.M2b" → "M2b"; mock "A_M1" with group A → "M1" */
export function shortId(id: string, group: string | null | undefined): string {
  let s = id;
  if (group && (s.startsWith(group + ".") || s.startsWith(group + "_"))) s = s.slice(group.length + 1);
  const i = s.lastIndexOf(".");
  return i >= 0 && i < s.length - 1 ? s.slice(i + 1) : s;
}

export const scoreClass = (v: number) => (v >= 90 ? "score-good" : v >= 70 ? "score-mid" : "score-bad");
export const SCORE_TIP = "Score 0–100 ranks candidate designs: it rewards delivered power and penalizes errors, warnings and stray light. PASS/FAIL is the gate (no errors and all targets met); a passing design can still score low if it has many warnings.";

const ORDER = { error: 0, warning: 1, info: 2 } as const;
type Filter = "all" | "error" | "warning" | "info";

export default function VerifyPanel() {
  const report = useStore((s) => s.report);
  const design = useStore((s) => s.design);
  const trace = useStore((s) => s.trace);
  const selected = useStore((s) => s.selected);
  const select = useStore((s) => s.select);
  const [filter, setFilter] = useState<Filter>("all");

  const groups = useMemo(() => {
    if (!report) return [];
    const idx = checkModuleIndex(design, trace);
    const titles = new Map((design?.modules ?? []).map((m) => [m.id, m.title || m.id]));
    const m = new Map<string, Check[]>();
    for (const c of report.checks) {
      if (filter !== "all" && c.severity !== filter) continue;
      const g = idx(c) ?? "";
      m.set(g, [...(m.get(g) ?? []), c]);
    }
    const order = [...(design?.modules ?? []).map((x) => x.id), ""];
    return [...m.entries()]
      .sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]))
      .map(([g, checks]) => ({ g, title: g ? titles.get(g) ?? g : (design?.modules?.length ? "Global" : ""), checks: checks.sort((a, b) => ORDER[a.severity] - ORDER[b.severity]) }));
  }, [report, design, trace, filter]);

  const running = useStore((s) => s.agent.running);
  const tuning = useDemo((d) => d.tune.active);
  const tunePhase = useDemo((d) => d.tune.phase);
  const nVerified = useConsole((s) => s.iterations.length);
  const finalSeen = useConsole((s) => s.rows.some((r) => r.kind === "final"));
  if (tuning) {
    return (
      <div className="section">
        <div className="section-title">Verify report</div>
        <div className="verify-head pending">
          <LoaderCircle size={20} className="spin" />
          <div>
            <div className="vh-title">Aligning…</div>
            <div className="vh-sub">{tunePhase === "detune" ? "as-built misalignment" : "alignment pass in progress"} · delivered <b className="mono">{(report?.metrics.delivered_mw ?? 0).toFixed(2)} mW</b></div>
          </div>
          <div />
        </div>
      </div>
    );
  }
  if (running && !finalSeen && !(nVerified > 0 && report?.passed)) {
    return (
      <div className="section">
        <div className="section-title">Verify report</div>
        <div className="verify-head pending">
          <LoaderCircle size={20} className="spin" />
          <div>
            <div className="vh-title">Run in progress</div>
            <div className="vh-sub">candidates verifying… <b className="mono">{nVerified}</b> verified so far</div>
          </div>
          <div />
        </div>
      </div>
    );
  }
  if (!report) return null;
  const nErr = report.checks.filter((c) => c.severity === "error").length;
  const nWarn = report.checks.filter((c) => c.severity === "warning").length;
  const nInfo = report.checks.length - nErr - nWarn;
  const m = report.metrics;
  const elGroup = new Map<string, string | null>((design?.elements ?? []).map((e) => [e.id, e.group ?? null]));

  return (
    <div className="section">
      <div className="section-title">Verify report</div>
      <div className={`verify-head ${report.passed ? "pass" : "fail"}`}>
        {report.passed ? <CircleCheck size={22} className="sev-ok" /> : <CircleX size={22} className="sev-error" />}
        <div>
          <div className="vh-title">{report.passed ? "PASS" : "FAIL"}</div>
          <div className="vh-sub">{nErr} error{nErr === 1 ? "" : "s"} · {nWarn} warning{nWarn === 1 ? "" : "s"} · {report.checks.length} checks</div>
        </div>
        <div className={`vh-score ${scoreClass(report.score)}`} title={SCORE_TIP}>{report.score.toFixed(0)}<small>score / 100</small></div>
      </div>
      <div className="chips" role="radiogroup" aria-label="Severity filter">
        {([["all", `All ${report.checks.length}`], ["error", `Errors ${nErr}`], ["warning", `Warnings ${nWarn}`], ["info", `Info ${nInfo}`]] as [Filter, string][]).map(([f, l]) => (
          <button key={f} className={`chip${filter === f ? " active" : ""}`} onClick={() => setFilter(f)} role="radio" aria-checked={filter === f}>{l}</button>
        ))}
      </div>
      <table className="checks">
        <thead>
          <tr><th className="sev" /><th>Check</th><th>Element</th><th className="n">Value / limit</th></tr>
        </thead>
        {groups.map(({ g, title, checks }) => (
          <tbody key={g || "_"}>
            {title && (
              <tr className="grp">
                <td colSpan={4}>
                  <span>{title}</span>
                  <span className="grp-counts mono">
                    {checks.filter((c) => c.severity === "error").length > 0 && <span className="sev-error">{checks.filter((c) => c.severity === "error").length} err</span>}
                    {checks.filter((c) => c.severity === "warning").length > 0 && <span className="sev-warning">{checks.filter((c) => c.severity === "warning").length} warn</span>}
                    <span className="muted">{checks.length}</span>
                  </span>
                </td>
              </tr>
            )}
            {checks.map((c, i) => {
              const target = c.element_id ? { kind: "element" as const, id: c.element_id } : c.segment_id ? { kind: "segment" as const, id: c.segment_id } : null;
              const isSel = !!target && selected?.id === target.id;
              const full = c.element_id ?? c.segment_id ?? "";
              const grp = c.element_id ? elGroup.get(c.element_id) : g || null;
              return (
                <tr key={i} className={`${target ? "clickable" : ""}${isSel ? " sel" : ""}`} onClick={() => target && select(target)}>
                  <td className="sev"><SevIcon s={c.severity} /></td>
                  <td><div className="chk-id">{c.id}</div><div className="chk-msg" title={c.message}>{c.message}</div></td>
                  <td className="el-cell" title={full}>
                    {full ? <span className="mono">{c.element_id ? shortId(full, grp) : full}</span> : "—"}
                  </td>
                  <td className="n">{valueVsLimit(c)}</td>
                </tr>
              );
            })}
          </tbody>
        ))}
      </table>
      {groups.length === 0 && <div className="empty-hint mt8">No checks match this filter.</div>}
      <div className="metrics">
        {"input_mw" in m && <div className="metric"><div className="k">Input</div><div className="v">{mW(m.input_mw)}</div></div>}
        {"delivered_mw" in m && <div className="metric"><div className="k">Delivered</div><div className="v">{mW(m.delivered_mw)}</div></div>}
        {"stray_mw" in m && <div className="metric"><div className="k">Stray</div><div className="v">{mW(m.stray_mw)}</div></div>}
        {"input_mw" in m && "delivered_mw" in m && <div className="metric"><div className="k">Efficiency</div><div className="v">{pct(m.input_mw ? m.delivered_mw / m.input_mw : 0, 1)}</div></div>}
      </div>
    </div>
  );
}
