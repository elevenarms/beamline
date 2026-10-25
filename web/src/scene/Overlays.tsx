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

const LOGIC_RE = /(logic|nand|adder|all-optical)/i;
const WAVEPLATES = new Set(["half_wave_plate", "quarter_wave_plate"]);

/** Logic I/O strip for optical-calculator designs: inputs (sources or waveplates) as switches, detectors as lamps. */
export function LogicStrip() {
  const design = useStore((s) => s.design);
  const trace = useStore((s) => s.trace);
  const updateSource = useStore((s) => s.updateSource);
  const updateElement = useStore((s) => s.updateElement);
  const select = useStore((s) => s.select);
  if (!design) return null;
  const spec = design.logic ?? null;
  if (!spec && !LOGIC_RE.test(`${design.name} ${design.description ?? ""}`)) return null;
  const els = design.elements ?? [];
  const findSrc = (k: string) => design.sources.find((s) => s.id === k) ?? design.sources.find((s) => s.label === k);
  const findEl = (k: string) => els.find((e) => e.id === k) ?? els.find((e) => e.label === k);

  type In = { key: string; name: string; on: boolean; toggle: () => void };
  const short = (id: string, label?: string | null) => (label && label.length <= 8 ? label : id);
  // fallback (no design.logic): input bits are the sources if there are several, plus waveplates labelled as input bits
  const bitPlates = els.filter((e) => WAVEPLATES.has(e.type) && /\b(input|bit)\b/i.test(e.label ?? "")).map((e) => e.id);
  const inputKeys = spec ? spec.inputs : [...(design.sources.length > 1 ? design.sources.map((s) => s.id) : []), ...bitPlates];
  const inputs: In[] = (inputKeys.length ? inputKeys : design.sources.map((s) => s.id)).flatMap((k): In[] => {
    const s = findSrc(k);
    if (s) {
      const on = s.enabled !== false;
      return [{ key: s.id, name: spec ? k : short(s.id, s.label), on, toggle: () => updateSource(s.id, { enabled: !on }) }];
    }
    const e = findEl(k);
    if (e && WAVEPLATES.has(e.type)) {
      const on = Math.abs((e.fast_axis_deg ?? 0) - 45) < 1;
      return [{ key: e.id, name: spec ? k : short(e.id, e.label), on, toggle: () => updateElement(e.id, { fast_axis_deg: on ? 0 : 45 }) }];
    }
    return [];
  });
  const peById = new Map((trace?.elements ?? []).map((p) => [p.id, p]));
  const pds = (trace?.elements ?? []).filter((e) => e.type === "photodiode");
  const isRef = (id: string) => /\bref/i.test(`${id} ${els.find((x) => x.id === id)?.label ?? ""}`);
  const refPd = spec ? undefined : pds.find((p) => isRef(p.id));
  const maxP = Math.max(1e-9, ...design.sources.map((s) => s.power_mw ?? 10));
  // threshold: spec value, else a reference detector's reading, else 20 % of the largest source
  const threshold = spec ? spec.threshold_mw : refPd ? (refPd.power_out_mw ?? 0) : 0.2 * maxP;
  const outIds = spec
    ? spec.outputs.map((k) => ({ name: k, id: findEl(k)?.id ?? k }))
    : pds.filter((p) => p !== refPd).map((e) => ({ name: short(e.id, els.find((x) => x.id === e.id)?.label), id: e.id }));
  const outs = outIds.map((o) => {
    const p = peById.get(o.id)?.power_out_mw ?? 0;
    return { ...o, p, lit: p > threshold };
  });
  const truth = `${inputs.map((i) => `${i.name}=${i.on ? 1 : 0}`).join(" ")} → ${outs.map((o) => `${o.name}=${o.lit ? 1 : 0}`).join(" ")}`;
  return (
    <div className="logic-strip panel-float" role="group" aria-label="Logic inputs and outputs">
      <span className="ls-title">In</span>
      {inputs.map((i) => (
        <button key={i.key} className={`ls-in${i.on ? " on" : ""}`} role="switch" aria-checked={i.on} onClick={i.toggle} title={`${i.key}: click to switch ${i.on ? "off" : "on"}`}>
          <span className="ls-name">{i.name}</span>
          <span className="ls-bit mono">{i.on ? 1 : 0}</span>
        </button>
      ))}
      <span className="ls-sep" />
      <span className="ls-title">Out</span>
      {outs.map((o) => (
        <button key={o.id} className={`ls-out${o.lit ? " lit" : ""}`} onClick={() => select({ kind: "element", id: o.id })} title={`${o.id}: ${o.p.toFixed(3)} mW (threshold ${threshold.toFixed(3)} mW)`}>
          <span className="lamp" />
          <span className="ls-name">{o.name}</span>
          <span className="ls-bit mono">{o.lit ? 1 : 0}</span>
          <span className="mono muted ls-mw">{mW(o.p)}</span>
        </button>
      ))}
      {outs.length === 0 && <span className="muted">no detectors</span>}
      <span className="ls-truth mono" title={`threshold ${mW(threshold)}`}>{truth}</span>
    </div>
  );
}
