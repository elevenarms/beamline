import { useEffect, useMemo } from "react";
import { Box, ChevronDown, Columns2, ChevronUp, Maximize2, Orbit, RectangleHorizontal, RectangleVertical, Square, X } from "lucide-react";
import { useStore } from "../store";
import { domRefs, useView, type Preset } from "./viewStore";
import { bandName } from "../lib/color";
import { useWlColor } from "../lib/theme";
import { beamRadius, powerOpacity } from "../lib/beam";
import { mhz, mm, mW, nm } from "../lib/format";

const PRESETS: { id: Preset; label: string; key: string; Icon: typeof Square }[] = [
  { id: "top", label: "Top (plan)", key: "1", Icon: Square },
  { id: "iso", label: "Isometric", key: "2", Icon: Box },
  { id: "front", label: "Front (along +y)", key: "3", Icon: RectangleHorizontal },
  { id: "side", label: "Side (along −x)", key: "4", Icon: RectangleVertical },
  { id: "free", label: "Perspective / free orbit", key: "P", Icon: Orbit },
];

export function ViewToolbar() {
  const { preset, projection, setPreset, toggleProjection, fit } = useView();
  const figureUrl = useStore((s) => s.agent.figureUrl);
  const compare = useStore((s) => s.compare);
  const setCompare = useStore((s) => s.setCompare);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === "1") setPreset("top");
      else if (k === "2") setPreset("iso");
      else if (k === "3") setPreset("front");
      else if (k === "4") setPreset("side");
      else if (k === "0") fit();
      else if (k === "p") toggleProjection();
      else if (k === "escape") useStore.getState().select(null);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setPreset, toggleProjection, fit]);
  return (
    <div className="view-toolbar" role="toolbar" aria-label="View">
      {PRESETS.map(({ id, label, key, Icon }) => {
        const active = id === "free" ? projection === "persp" : preset === id && projection === "ortho";
        return (
          <button key={id} className={`tb-btn${active ? " active" : ""}`} onClick={() => (id === "free" ? (projection === "persp" ? setPreset("iso") : toggleProjection()) : setPreset(id))} data-tip={`${label}  [${key}]`} aria-label={label}>
            <Icon size={15} strokeWidth={1.6} />
            <span>{id === "free" ? "Persp" : id[0].toUpperCase() + id.slice(1)}</span>
          </button>
        );
      })}
      <div className="tb-sep" />
      {figureUrl && (
        <button className={`tb-btn${compare ? " active" : ""}`} onClick={() => setCompare(!compare)} data-tip="Compare with source figure" aria-label="Compare with source figure">
          <Columns2 size={15} strokeWidth={1.6} />
          <span>Compare</span>
        </button>
      )}
      <button className="tb-btn" onClick={fit} data-tip="Fit to design  [0]" aria-label="Fit to design">
        <Maximize2 size={15} strokeWidth={1.6} />
        <span>Fit</span>
      </button>
    </div>
  );
}

export function Legend() {
  const wl = useWlColor();
  const trace = useStore((s) => s.trace);
  const ex = useStore((s) => s.exaggeration);
  const setEx = useStore((s) => s.setExaggeration);
  const wls = useMemo(() => {
    const m = new Map<number, number>();
    for (const s of trace?.segments ?? []) m.set(s.wavelength_nm, Math.max(m.get(s.wavelength_nm) ?? 0, s.power_mw));
    return [...m.keys()].sort((a, b) => a - b);
  }, [trace]);
  const open = useView((v) => v.legendOpen);
  const setOpen = useView((v) => v.setLegendOpen);
  if (!open) {
    return (
      <button className="legend legend-collapsed panel-float" onClick={() => setOpen(true)} aria-label="Show legend">
        {wls.map((w) => <span key={w} className="swatch" style={{ background: wl(w) }} title={nm(w)} />)}
        <span>Legend</span>
        <ChevronUp size={13} />
      </button>
    );
  }
  return (
    <div className="legend panel-float">
      <div className="legend-title row">Legend<span className="spacer" /><button className="icon-btn" onClick={() => setOpen(false)} aria-label="Collapse legend"><ChevronDown size={13} /></button></div>
      <div className="legend-rows">
        {wls.map((w) => (
          <div className="legend-row" key={w}>
            <span className="swatch" style={{ background: wl(w) }} />
            <span className="mono">{nm(w)}</span>
            <span className="muted">{bandName(w)}</span>
          </div>
        ))}
        {wls.length === 0 && <div className="muted">No beams</div>}
      </div>
      <div className="legend-sub">Beam envelope 1/e² radius w(z)</div>
      <label className="legend-slider">
        <span className="mono">×{ex.toFixed(1)}</span>
        <input type="range" min={1} max={10} step={0.5} value={ex} onChange={(e) => setEx(Number(e.target.value))} aria-label="Beam radius exaggeration" />
      </label>
      <div className="legend-sub">Power → opacity (log)</div>
      <div className="legend-power">
        {[0.1, 1, 10].map((p) => (
          <div key={p} className="pw">
            <span className="pw-bar" style={{ opacity: Math.min(1, 0.25 + powerOpacity(p)) }} />
            <span className="mono">{mW(p)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ScaleAndCursor() {
  const cursor = useView((v) => v.cursor);
  const preset = useView((v) => v.preset);
  return (
    <>
      <div className="scalebar">
        <div className="scalebar-bar" ref={(el) => { domRefs.scaleBar = el; }} />
        <span className="mono" ref={(el) => { domRefs.scaleLabel = el; }} />
      </div>
      {preset === "top" && (
        <svg className="axis-ind" width="46" height="46" viewBox="0 0 46 46" aria-label="Table axes: x right, y up">
          <path d="M8 38 H36 M31 34 L36 38 L31 42" fill="none" stroke="currentColor" strokeWidth="1.3" />
          <path d="M8 38 V10 M4 15 L8 10 L12 15" fill="none" stroke="currentColor" strokeWidth="1.3" />
          <text x="39" y="42" fontSize="10">x</text>
          <text x="5" y="7" fontSize="10">y</text>
        </svg>
      )}
      <div className="cursor-readout mono">
        {cursor ? (
          <>
            <span>x {cursor[0].toFixed(1).padStart(6, " ")} mm</span>
            <span>y {cursor[1].toFixed(1).padStart(6, " ")} mm</span>
          </>
        ) : (
          <span className="muted">x — mm&nbsp;&nbsp;y — mm</span>
        )}
      </div>
    </>
  );
}

export function BeamTooltip() {
  const wl = useWlColor();
  const tip = useView((v) => v.tooltip);
  const trace = useStore((s) => s.trace);
  if (!tip || !trace) return null;
  const s = trace.segments.find((x) => x.id === tip.segId);
  if (!s) return null;
  const w = beamRadius(s, tip.z);
  return (
    <div className="beam-tip" style={{ left: tip.sx + 14, top: tip.sy + 14 }}>
      <div className="tip-head">
        <span className="swatch" style={{ background: wl(s.wavelength_nm) }} />
        <span className="mono strong">{s.branch}</span>
        <span className="muted mono">{s.id}</span>
      </div>
      <table className="kv">
        <tbody>
          <tr><td>Power</td><td>{mW(s.power_mw)}</td></tr>
          <tr><td>Polarization</td><td>{s.polarization_label}</td></tr>
          <tr><td>w at z = {tip.z.toFixed(0)} mm</td><td>{mm(w, 3)}</td></tr>
          <tr><td>Waist w₀</td><td>{mm(s.w0_mm, 3)}</td></tr>
          <tr><td>Rayleigh z_R</td><td>{mm(s.rayleigh_mm, 0)}</td></tr>
          <tr><td>Freq. shift</td><td>{mhz(s.freq_shift_mhz)}</td></tr>
          <tr><td>λ</td><td>{nm(s.wavelength_nm)}</td></tr>
        </tbody>
      </table>
    </div>
  );
}

export function FigureThumb() {
  const url = useStore((s) => s.agent.figureUrl);
  const show = useStore((s) => s.showFigure);
  const setShow = useStore((s) => s.setShowFigure);
  if (!url || !show) return null;
  return (
    <div className="figure-thumb panel-float">
      <div className="figure-head">
        <span>Source figure</span>
        <button className="icon-btn" onClick={() => setShow(false)} aria-label="Hide figure"><X size={14} /></button>
      </div>
      <img src={url} alt="Uploaded paper figure" />
    </div>
  );
}
