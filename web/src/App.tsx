import { useEffect, useState } from "react";
import { Braces, FileCode2, ListTree, LoaderCircle, Moon, Sun, Workflow } from "lucide-react";
import { useTheme } from "./lib/theme";
import "./styles.css";
import { useStore } from "./store";
import * as api from "./api";
import type { ExampleInfo } from "./types";
import Viewer from "./scene/Viewer";
import { BeamTooltip, FigureThumb, Legend, ScaleAndCursor, ViewToolbar } from "./scene/Overlays";
import AgentPanel from "./panels/AgentPanel";
import Inspector from "./panels/Inspector";
import VerifyPanel, { SCORE_TIP, scoreClass } from "./panels/VerifyPanel";
import JsonPanel from "./panels/JsonPanel";
import OutlinePanel from "./panels/OutlinePanel";
import ComparePane from "./panels/ComparePane";
import ExportModal from "./panels/ExportModal";
import { mW } from "./lib/format";

function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 20 20" aria-hidden>
      <rect x="0.5" y="0.5" width="19" height="19" rx="3" style={{ fill: "var(--inverse)" }} />
      <path d="M3 14 L10 7 L17 7" stroke="#e23b2e" strokeWidth="1.6" fill="none" />
      <line x1="8" y1="5" x2="12" y2="9" style={{ stroke: "var(--on-inverse)" }} strokeWidth="1.4" />
    </svg>
  );
}

function exampleValue(examples: ExampleInfo[], name: string | undefined) {
  if (!name) return "";
  const hit = examples.find((x) => x.name === name || x.name === `mock:${name}`);
  if (hit) return hit.name;
  return "__custom";
}

function TopBar({ examples, onPick }: { examples: ExampleInfo[]; onPick: (n: string) => void }) {
  const design = useStore((s) => s.design);
  const mock = useStore((s) => s.mock);
  const setExportOpen = useStore((s) => s.setExportOpen);
  return (
    <header className="topbar">
      <div className="brand"><BrandMark /> Beamline <small>optical layout design &amp; verification</small></div>
      <div className="sep" />
      <div className="design-name">
        <b>{design?.name ?? "—"}</b>
        <span title={design?.description}>{design?.description || " "}</span>
      </div>
      <div className="spacer" />
      <select className="select" value={exampleValue(examples, design?.name)} onChange={(e) => onPick(e.target.value)} aria-label="Load example">
        <option value="" disabled>Load example…</option>
        <option value="__custom" disabled>Custom / agent result</option>
        {examples.map((x) => <option key={x.name} value={x.name}>{x.title || x.name}</option>)}
      </select>
      <span className={`pill${mock ? " warn" : ""}`} title={mock ? "Backend unreachable or ?mock=1: using the in-browser tracer and mock agent" : "Connected to the Beamline backend"}>
        <span className="dot" /> {mock ? "Offline mock" : "Backend"}
      </span>
      <button className="btn" onClick={() => setExportOpen(true)} disabled={!design}><FileCode2 size={14} /> Export PyOpticL</button>
      <ThemeToggle />
    </header>
  );
}

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  return (
    <button className="btn icon-only" onClick={toggle} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"} title={dark ? "Light theme" : "High-contrast dark theme"}>
      {dark ? <Sun size={15} /> : <Moon size={15} />}
    </button>
  );
}

function StatusBar() {
  const trace = useStore((s) => s.trace);
  const report = useStore((s) => s.report);
  const ms = useStore((s) => s.traceMs);
  const tracing = useStore((s) => s.tracing);
  const mock = useStore((s) => s.mock);
  return (
    <footer className="statusbar">
      <span className="item">Trace <b>{ms == null ? "—" : `${ms.toFixed(0)} ms`}</b>{tracing && <LoaderCircle size={11} className="spin" />}</span>
      <span className="item">Elements <b>{trace?.elements.length ?? 0}</b></span>
      <span className="item">Segments <b>{trace?.segments.length ?? 0}</b></span>
      <span className="item">Branches <b>{trace?.branches.length ?? 0}</b></span>
      <span className="item">Delivered <b>{mW(report?.metrics.delivered_mw)}</b></span>
      <span className="item" title={SCORE_TIP}>Score <b className={report ? scoreClass(report.score) : ""}>{report ? report.score.toFixed(0) : "—"}</b></span>
      {report && <span className={report.passed ? "pass" : "fail"}>{report.passed ? "PASS" : "FAIL"}</span>}
      <span className="spacer" />
      <span className="item muted">{mock ? "in-browser tracer" : "backend tracer"} · 1 Top · 2 Iso · 3 Front · 4 Side · P persp · 0 fit</span>
    </footer>
  );
}

export default function App() {
  const design = useStore((s) => s.design);
  const loadDesign = useStore((s) => s.loadDesign);
  const leftTab = useStore((s) => s.leftTab);
  const setLeftTab = useStore((s) => s.setLeftTab);
  const traceError = useStore((s) => s.traceError);
  const [examples, setExamples] = useState<ExampleInfo[]>([]);
  const compare = useStore((s) => s.compare);
  const figureUrl = useStore((s) => s.agent.figureUrl);
  const showCompare = compare && !!figureUrl;
  const [paneW, setPaneW] = useState(340);
  const startDrag = (e: React.PointerEvent) => {
    const x0 = e.clientX, w0 = paneW;
    const move = (ev: PointerEvent) => setPaneW(Math.max(240, Math.min(window.innerWidth * 0.5, w0 + ev.clientX - x0)));
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };


  const pick = async (name: string) => {

    try {
      loadDesign(await api.getExample(name));
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    api.listExamples().then((ex) => {
      setExamples(ex);
      if (!useStore.getState().design) {
        const first = ex.find((x) => !x.name.startsWith("mock:")) ?? ex[0];
        if (first) pick(first.name);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="app">
      <TopBar examples={examples} onPick={pick} />
      <aside className="side left">
        <div className="tabs" role="tablist">
          <button className={`tab${leftTab === "workflow" ? " active" : ""}`} onClick={() => setLeftTab("workflow")}><Workflow size={14} /> Workflow</button>
          <button className={`tab${leftTab === "outline" ? " active" : ""}`} onClick={() => setLeftTab("outline")}><ListTree size={14} /> Outline</button>
          <button className={`tab${leftTab === "json" ? " active" : ""}`} onClick={() => setLeftTab("json")}><Braces size={14} /> JSON</button>
        </div>
        <div className="scroll">{leftTab === "workflow" ? <AgentPanel /> : leftTab === "outline" ? <OutlinePanel /> : <JsonPanel />}</div>
      </aside>
      <main className="center">
        {/* always mounted so the canvas never re-parents (avoids WebGL/Html portal teardown) */}
        <div className="fig-pane-wrap" style={{ width: paneW, display: showCompare ? undefined : "none" }}>{showCompare && <ComparePane />}</div>
        <div className="split-handle" role="separator" aria-orientation="vertical" aria-label="Resize comparison" onPointerDown={startDrag} style={{ display: showCompare ? undefined : "none" }} />
        <div className="viewport">
          <Viewer />
          <ViewToolbar />
          <Legend />
          <ScaleAndCursor />
          {!showCompare && <FigureThumb />}
          {!design && <div className="canvas-empty">Loading…</div>}
          {traceError && <div className="trace-err">Trace failed: {traceError}</div>}
        </div>
      </main>
      <aside className="side right">
        <div className="scroll">
          <Inspector />
          <VerifyPanel />
        </div>
      </aside>
      <StatusBar />
      <BeamTooltip />
      <ExportModal />
    </div>
  );
}
