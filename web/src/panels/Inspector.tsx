import { useEffect, useState } from "react";
import { MousePointerClick } from "lucide-react";
import { useStore } from "../store";
import type { Element, ElementType, Segment, Source } from "../types";
import { SHORT, beamRadius } from "../lib/beam";
import { useWlColor } from "../lib/theme";
import { deg, mhz, mm, mW, nm, pct } from "../lib/format";

type NumKey = Exclude<{ [K in keyof Element]-?: Element[K] extends number | null | undefined ? K : never }[keyof Element], undefined>;

function NumField({ value, onChange, unit, step = 1, placeholder, min, max }: {
  value: number | null | undefined; onChange: (v: number | null) => void; unit?: string; step?: number; placeholder?: string; min?: number; max?: number;
}) {
  const [txt, setTxt] = useState(value == null ? "" : String(value));
  const [focus, setFocus] = useState(false);
  useEffect(() => { if (!focus) setTxt(value == null ? "" : String(+value.toFixed(4))); }, [value, focus]);
  return (
    <div className="numfield">
      <input
        type="number" step={step} min={min} max={max} value={txt} placeholder={placeholder ?? "auto"}
        onFocus={() => setFocus(true)} onBlur={() => setFocus(false)}
        onChange={(e) => {
          setTxt(e.target.value);
          if (e.target.value.trim() === "") onChange(null);
          else { const v = Number(e.target.value); if (Number.isFinite(v)) onChange(v); }
        }}
      />
      <span className="unit">{unit ?? ""}</span>
    </div>
  );
}

function SliderRow({ label, value, min, max, step, onChange, unit, fallback }: {
  label: string; value: number | null | undefined; min: number; max: number; step: number; onChange: (v: number | null) => void; unit: string; fallback?: number;
}) {
  const v = value ?? fallback ?? min;
  return (
    <>
      <tr>
        <td>{label}</td>
        <td><NumField value={value} onChange={onChange} unit={unit} step={step} /></td>
      </tr>
      <tr className="slider-row">
        <td colSpan={2}><input type="range" min={min} max={max} step={step} value={v} onChange={(e) => onChange(Number(e.target.value))} aria-label={label} /></td>
      </tr>
    </>
  );
}

const PARAMS: Partial<Record<ElementType, { key: NumKey; label: string; unit: string; step: number; min?: number; max?: number; slider?: [number, number] }[]>> = {
  lens: [{ key: "focal_length_mm", label: "Focal length f", unit: "mm", step: 5, slider: [-300, 500] }],
  half_wave_plate: [{ key: "fast_axis_deg", label: "Fast axis", unit: "°", step: 0.5, slider: [-90, 90] }],
  quarter_wave_plate: [{ key: "fast_axis_deg", label: "Fast axis", unit: "°", step: 0.5, slider: [-90, 90] }],
  beamsplitter: [{ key: "split_ratio", label: "Reflected fraction R", unit: "", step: 0.01, min: 0, max: 1, slider: [0, 1] }],
  sampler: [{ key: "split_ratio", label: "Reflected fraction R", unit: "", step: 0.01, min: 0, max: 1, slider: [0, 0.3] }],
  dichroic: [{ key: "cutoff_nm", label: "Cutoff λc", unit: "nm", step: 1 }],
  aom: [
    { key: "aom_frequency_mhz", label: "RF frequency", unit: "MHz", step: 1, slider: [40, 250] },
    { key: "aom_efficiency", label: "Diffraction eff.", unit: "", step: 0.01, min: 0, max: 1, slider: [0, 1] },
    { key: "acoustic_velocity_m_s", label: "Acoustic velocity", unit: "m/s", step: 10 },
  ],
  iris: [{ key: "aperture_mm", label: "Aperture Ø", unit: "mm", step: 0.1, min: 0, slider: [0.2, 12] }],
  fiber_coupler: [
    { key: "focal_length_mm", label: "Collimator f", unit: "mm", step: 0.1 },
    { key: "fiber_mfd_um", label: "Mode-field Ø", unit: "µm", step: 0.1 },
  ],
  vapor_cell: [{ key: "transmission", label: "Transmission", unit: "", step: 0.01, min: 0, max: 1, slider: [0, 1] }],
  isolator: [{ key: "transmission", label: "Transmission", unit: "", step: 0.01, min: 0, max: 1, slider: [0, 1] }],
  soa: [
    { key: "small_signal_gain_db", label: "Small-signal gain G₀", unit: "dB", step: 0.5, slider: [0, 30] },
    { key: "saturation_power_mw", label: "Saturation power", unit: "mW", step: 0.5, slider: [0.5, 50] },
  ],
  sfg_crystal: [{ key: "nl_efficiency_per_w", label: "NL efficiency η", unit: "1/W", step: 0.1, slider: [0, 10] }],
  saturable_absorber: [
    { key: "transmission", label: "Small-signal T₀", unit: "", step: 0.01, min: 0, max: 1, slider: [0, 1] },
    { key: "saturation_power_mw", label: "Saturation power", unit: "mW", step: 0.5, slider: [0.5, 50] },
  ],
};

function ElementInspector({ el }: { el: Element }) {
  const trace = useStore((s) => s.trace);
  const update = useStore((s) => s.updateElement);
  const pe = trace?.elements.find((p) => p.id === el.id);
  const inc = trace?.segments.find((s) => s.end_element === el.id);
  const set = (patch: Partial<Element>) => update(el.id, patch);
  const branches = trace?.branches ?? [];
  const params = PARAMS[el.type] ?? [];
  const hit = pe?.hits[0];
  const isMirror = el.type === "mirror";

  return (
    <>
      <div className="section">
        <div className="insp-head"><b>{el.id}</b><span>{SHORT[el.type] ?? el.type}</span></div>
        <div className="insp-sub">{[el.label, el.part_number].filter(Boolean).join(" · ") || el.type}</div>
        {pe?.error && <div className="insp-err">{pe.error}</div>}
        <div className="section-title">Placement</div>
        <table className="props">
          <tbody>
            {el.at ? (
              <>
                <tr><td>x</td><td><NumField value={el.at[0]} onChange={(v) => set({ at: [v ?? 0, el.at![1]] })} unit="mm" /></td></tr>
                <tr><td>y</td><td><NumField value={el.at[1]} onChange={(v) => set({ at: [el.at![0], v ?? 0] })} unit="mm" /></td></tr>
              </>
            ) : (
              <>
                <tr>
                  <td>On beam</td>
                  <td className="v">
                    <div className="numfield">
                      <select value={el.beam ?? ""} onChange={(e) => set({ beam: e.target.value })}>
                        {[...new Set([el.beam ?? "", ...branches])].map((b) => <option key={b} value={b}>{b}</option>)}
                      </select>
                      <span className="unit" />
                    </div>
                  </td>
                </tr>
                <SliderRow label="Distance" value={el.distance_mm} min={0} max={Math.max(300, (el.distance_mm ?? 0) * 1.6)} step={0.5} unit="mm" onChange={(v) => set({ distance_mm: v ?? 0 })} />
              </>
            )}
            {isMirror && el.angle_deg == null ? (
              <SliderRow label="Out direction" value={el.out_direction_deg} min={0} max={360} step={0.5} unit="°" onChange={(v) => set({ out_direction_deg: v })} />
            ) : (
              <SliderRow label={isMirror ? "Normal angle" : "Axis angle"} value={el.angle_deg} fallback={pe?.angle_deg ?? 0} min={0} max={360} step={0.5} unit="°" onChange={(v) => set({ angle_deg: v })} />
            )}
            {pe?.position && <tr><td>Position</td><td className="v">{pe.position[0].toFixed(1)}, {pe.position[1].toFixed(1)} mm</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="section">
        <div className="section-title">Parameters</div>
        <table className="props">
          <tbody>
            {params.map((p) =>
              p.slider ? (
                <SliderRow key={p.key} label={p.label} value={el[p.key] as number | null | undefined} min={p.slider[0]} max={p.slider[1]} step={p.step} unit={p.unit} onChange={(v) => set({ [p.key]: v } as Partial<Element>)} />
              ) : (
                <tr key={p.key}><td>{p.label}</td><td><NumField value={el[p.key] as number | null | undefined} onChange={(v) => set({ [p.key]: v } as Partial<Element>)} unit={p.unit} step={p.step} min={p.min} max={p.max} /></td></tr>
              ),
            )}
            {el.type === "aom" && (
              <tr><td>Order</td><td className="v"><div className="numfield">
                <select value={el.aom_order ?? 1} onChange={(e) => set({ aom_order: Number(e.target.value) as 1 | -1 })}>
                  <option value={1}>+1</option><option value={-1}>−1</option>
                </select><span className="unit" /></div></td></tr>
            )}
            {el.type === "dichroic" && (
              <tr><td>Reflects</td><td className="v"><div className="numfield">
                <select value={el.reflect ?? "below"} onChange={(e) => set({ reflect: e.target.value as "below" | "above" })}>
                  <option value="below">below λc</option><option value="above">above λc</option>
                </select><span className="unit" /></div></td></tr>
            )}
            {el.type !== "iris" && (
              <tr><td>Clear aperture Ø</td><td><NumField value={el.aperture_mm} onChange={(v) => set({ aperture_mm: v })} unit="mm" step={0.5} /></td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="section">
        <div className="section-title">Beam at element</div>
        {!hit ? <div className="empty-hint">Not illuminated.</div> : (
          <table className="props">
            <tbody>
              <tr><td>Incoming branch</td><td className="v">{inc?.branch ?? "—"}</td></tr>
              <tr><td>Power in</td><td className="v">{mW(hit.power_in_mw)}</td></tr>
              <tr><td>Beam radius w</td><td className="v">{mm(hit.w_mm, 3)}</td></tr>
              <tr><td>Clip loss</td><td className="v">{pct(hit.clip_loss, 2)}</td></tr>
              <tr><td>Centre offset</td><td className="v">{mm(hit.offset_mm, 2)}</td></tr>
              <tr><td>Polarization</td><td className="v">{inc?.polarization_label ?? "—"}</td></tr>
              {inc && <tr><td>Freq. shift</td><td className="v">{mhz(inc.freq_shift_mhz)}</td></tr>}
              {pe?.coupling_efficiency != null && <tr><td>Coupling η</td><td className="v strong">{pct(pe.coupling_efficiency, 1)}</td></tr>}
              {pe?.power_out_mw != null && <tr><td>Power delivered</td><td className="v strong">{mW(pe.power_out_mw)}</td></tr>}
              {pe && pe.hits.length > 1 && <tr><td>Hits</td><td className="v">{pe.hits.length}</td></tr>}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function SourceInspector({ src }: { src: Source }) {
  const update = useStore((s) => s.updateSource);
  const set = (p: Partial<Source>) => update(src.id, p);
  return (
    <div className="section">
      <div className="insp-head"><b>{src.id}</b><span>Source</span></div>
      <div className="insp-sub">{[src.label, src.part_number].filter(Boolean).join(" · ") || "laser"}</div>
      <table className="props">
        <tbody>
          <tr>
            <td>Output</td>
            <td className="v">
              <button className={`switch${src.enabled === false ? "" : " on"}`} role="switch" aria-checked={src.enabled !== false} onClick={() => set({ enabled: src.enabled === false })}>
                <span className="mono">{src.enabled === false ? "0" : "1"}</span>{src.enabled === false ? "OFF" : "ON"}
              </button>
            </td>
          </tr>
          <tr><td>x</td><td><NumField value={src.position[0]} onChange={(v) => set({ position: [v ?? 0, src.position[1]] })} unit="mm" /></td></tr>
          <tr><td>y</td><td><NumField value={src.position[1]} onChange={(v) => set({ position: [src.position[0], v ?? 0] })} unit="mm" /></td></tr>
          <SliderRow label="Direction" value={src.direction_deg} min={0} max={360} step={0.5} unit="°" onChange={(v) => set({ direction_deg: v ?? 0 })} />
          <tr><td>Wavelength</td><td><NumField value={src.wavelength_nm} onChange={(v) => set({ wavelength_nm: v ?? 780 })} unit="nm" /></td></tr>
          <SliderRow label="Power" value={src.power_mw} fallback={10} min={0} max={Math.max(100, (src.power_mw ?? 10) * 2)} step={0.5} unit="mW" onChange={(v) => set({ power_mw: v ?? 10 })} />
          <tr><td>Waist w₀</td><td><NumField value={src.waist_mm} onChange={(v) => set({ waist_mm: v ?? 0.5 })} unit="mm" step={0.05} /></td></tr>
          <tr><td>Waist offset</td><td><NumField value={src.waist_offset_mm} onChange={(v) => set({ waist_offset_mm: v ?? 0 })} unit="mm" /></td></tr>
          <tr><td>Polarization</td><td className="v"><div className="numfield">
            <select value={typeof src.polarization === "number" ? "num" : src.polarization ?? "H"} onChange={(e) => set({ polarization: e.target.value === "num" ? 0 : (e.target.value as Source["polarization"]) })}>
              {["H", "V", "D", "A", "R", "L"].map((p) => <option key={p}>{p}</option>)}
              <option value="num">linear θ</option>
            </select><span className="unit" /></div></td></tr>
          {typeof src.polarization === "number" && (
            <SliderRow label="Linear angle" value={src.polarization} min={-90} max={90} step={0.5} unit="°" onChange={(v) => set({ polarization: v ?? 0 })} />
          )}
        </tbody>
      </table>
    </div>
  );
}

function SegmentInspector({ s }: { s: Segment }) {
  const wl = useWlColor();
  return (
    <div className="section">
      <div className="insp-head">
        <span className="swatch" style={{ background: wl(s.wavelength_nm), width: 22 }} />
        <b>{s.branch}</b><span className="mono muted">{s.id}</span>
      </div>
      <div className="insp-sub">{s.start_element ?? "—"} → {s.end_element ?? (s.end_reason === "escaped" ? "escapes table" : s.end_reason)}</div>
      <table className="props">
        <tbody>
          <tr><td>Wavelength</td><td className="v">{nm(s.wavelength_nm)}</td></tr>
          <tr><td>Power</td><td className="v">{mW(s.power_mw)}</td></tr>
          <tr><td>Polarization</td><td className="v">{s.polarization_label}</td></tr>
          <tr><td>Length</td><td className="v">{mm(s.length_mm, 1)}</td></tr>
          <tr><td>Direction</td><td className="v">{deg(s.direction_deg, 2)}</td></tr>
          <tr><td>w start / end</td><td className="v">{s.w_start_mm.toFixed(3)} / {s.w_end_mm.toFixed(3)} mm</td></tr>
          <tr><td>Waist w₀</td><td className="v">{mm(s.w0_mm, 3)}</td></tr>
          <tr><td>Waist at z</td><td className="v">{mm(s.waist_z_mm, 1)}</td></tr>
          <tr><td>Rayleigh z_R</td><td className="v">{mm(s.rayleigh_mm, 1)}</td></tr>
          <tr><td>w at midpoint</td><td className="v">{mm(beamRadius(s, s.length_mm / 2), 3)}</td></tr>
          <tr><td>Freq. shift</td><td className="v">{mhz(s.freq_shift_mhz)}</td></tr>
          <tr><td>End</td><td className="v">{s.end_reason}</td></tr>
        </tbody>
      </table>
    </div>
  );
}

export default function Inspector() {
  const sel = useStore((s) => s.selected);
  const design = useStore((s) => s.design);
  const trace = useStore((s) => s.trace);
  if (!sel || !design) {
    return (
      <div className="section">
        <div className="section-title">Inspector</div>
        <div className="empty-hint" style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <MousePointerClick size={14} /> Click a component or beam to inspect. Double-click to zoom.
        </div>
      </div>
    );
  }
  if (sel.kind === "element") {
    const el = design.elements?.find((e) => e.id === sel.id);
    return el ? <ElementInspector key={el.id} el={el} /> : null;
  }
  if (sel.kind === "source") {
    const src = design.sources.find((s) => s.id === sel.id);
    return src ? <SourceInspector key={src.id} src={src} /> : null;
  }
  const seg = trace?.segments.find((s) => s.id === sel.id);
  return seg ? <SegmentInspector s={seg} /> : null;
}
