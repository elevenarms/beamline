import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Bounds, Edges } from "@react-three/drei";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { Download, ExternalLink, LoaderCircle, Package, Printer, ShoppingCart, X } from "lucide-react";
import { useStore } from "../store";
import { useView } from "../scene/viewStore";
import { useConsole } from "../consoleStore";
import { usePalette } from "../lib/theme";
import * as api from "../api";
import type { Bom, BomRow, PrintedPart } from "../types";

const usd = (v: number | null | undefined) => (v == null ? "—" : `$${v.toLocaleString("en-US", { minimumFractionDigits: v < 100 ? 2 : 0, maximumFractionDigits: 2 })}`);

/** offline stand-in geometry: a plate tile with keyed pin-hole pairs */
function mockTileGeometry(w: number, h: number, t: number, sites: number): THREE.BufferGeometry {
  const s = new THREE.Shape();
  s.moveTo(0, 0); s.lineTo(w, 0); s.lineTo(w, h); s.lineTo(0, h); s.lineTo(0, 0);
  const g = 25.4;
  for (let x = g / 2; x < w; x += g) for (let y = g / 2; y < h; y += g) {
    const p = new THREE.Path(); p.absarc(x, y, 3.3, 0, Math.PI * 2, true); s.holes.push(p);
  }
  for (let i = 0; i < Math.min(sites, 12); i++) {
    const x = g + ((i * 53) % Math.max(1, w - 2 * g)), y = g + ((i * 37) % Math.max(1, h - 2 * g));
    for (const dx of [-6, 6]) { const p = new THREE.Path(); p.absarc(x + dx, y + 12.7, 1.1, 0, Math.PI * 2, true); s.holes.push(p); }
  }
  const geo = new THREE.ExtrudeGeometry(s, { depth: t, bevelEnabled: false, curveSegments: 16 });
  geo.rotateX(-Math.PI / 2);
  geo.center();
  return geo;
}

function Turntable({ geo }: { geo: THREE.BufferGeometry }) {
  const ref = useRef<THREE.Group>(null);
  const P = usePalette();
  useFrame((_, dt) => { if (ref.current) ref.current.rotation.y += dt * 0.25; });
  return (
    <group ref={ref}>
      <mesh geometry={geo}>
        <meshStandardMaterial color={P.darkBg ? "#8a939e" : "#c9cdd2"} roughness={0.75} metalness={0.05} />
        <Edges threshold={30} color={P.edge} />
      </mesh>
    </group>
  );
}

function StlPreview({ url, fallback }: { url: string | null; fallback: () => THREE.BufferGeometry }) {
  const [geo, setGeo] = useState<THREE.BufferGeometry | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let dead = false;
    setGeo(null); setErr(null);
    if (!url) { setGeo(fallback()); return; }
    new STLLoader().load(url, (g) => {
      if (dead) return;
      g.computeVertexNormals();
      // STL is Z-up; show it lying flat in a Y-up scene
      g.rotateX(-Math.PI / 2);
      g.center();
      setGeo(g);
    }, undefined, (e) => !dead && setErr(String((e as ErrorEvent)?.message ?? e)));
    return () => { dead = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);
  if (err) return <div className="stl-wait err">{err}</div>;
  if (!geo) return <div className="stl-wait"><LoaderCircle size={14} className="spin" /> loading STL…</div>;
  return (
    <Canvas camera={{ position: [180, 160, 220], fov: 30, near: 1, far: 5000 }} dpr={[1, 2]}>
      <ambientLight intensity={0.9} />
      <directionalLight position={[200, 400, 200]} intensity={1.6} />
      <directionalLight position={[-300, 150, -200]} intensity={0.5} />
      <Suspense fallback={null}>
        <Bounds fit clip observe margin={1.15}>
          <Turntable geo={geo} />
        </Bounds>
      </Suspense>
    </Canvas>
  );
}

function PartsTable({ rows, title }: { rows: BomRow[]; title: string }) {
  const hl = (ids: string[]) => useView.setState({ highlight: new Set(ids), highlightUntil: performance.now() + 1e9 });
  return (
    <>
      <tr className="bom-sec"><td colSpan={6}>{title}</td></tr>
      {rows.map((r) => (
        <tr key={title + r.part_number} onMouseEnter={() => r.element_ids.length && hl(r.element_ids)} onMouseLeave={() => useView.setState({ highlight: new Set() })}>
          <td className="mono">{r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.part_number} <ExternalLink size={10} /></a> : r.part_number}</td>
          <td><div>{r.description}</div>{r.element_ids.length > 0 && <div className="bom-els mono">{r.element_ids.join(" · ")}</div>}</td>
          <td>{r.vendor || "—"}</td>
          <td className="n">{r.qty}</td>
          <td className="n" title={r.price_note}>{usd(r.unit_price_usd)}</td>
          <td className="n">{r.unit_price_usd == null ? "—" : usd(r.unit_price_usd * r.qty)}</td>
        </tr>
      ))}
    </>
  );
}

export default function BuildKit({ open, onClose }: { open: boolean; onClose: () => void }) {
  const design = useStore((s) => s.design);
  const [tab, setTab] = useState<"parts" | "print">("parts");
  const [bom, setBom] = useState<Bom | null>(null);
  const [mock, setMock] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState(0);
  const [dl, setDl] = useState(false);

  useEffect(() => {
    if (!open || !design) return;
    setBom(null); setErr(null); setSel(0);
    const t0 = performance.now();
    api.bom(design).then(({ bom: b, mock: m }) => {
      setBom(b); setMock(m);
      useConsole.getState().ingest({ type: "tool", agent_id: "bom", name: "bom", summary: `${b.totals.purchased_parts} purchased · ${b.totals.hardware_parts} hardware · ${b.totals.printed_parts} printed · est ${usd(b.totals.est_cost_usd)} · ${b.totals.est_print_h} h print${m ? " (offline estimate)" : ""}`, elapsed_ms: performance.now() - t0 });
    }, (e) => setErr((e as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, design?.name]);
  useEffect(() => () => useView.setState({ highlight: new Set() }), []);

  const part: PrintedPart | undefined = bom?.printed[sel];
  const stlUrl = part && bom?.stl_urls ? bom.stl_urls[part.name] ?? bom.stl_urls[part.file] ?? null : null;
  const fallback = useMemo(() => () => {
    const p = bom?.plate;
    const tiles = Math.max(1, bom?.printed.length ?? 1);
    return mockTileGeometry((p?.width_mm ?? 300) / Math.min(tiles, 2), (p?.height_mm ?? 150) / Math.max(1, Math.ceil(tiles / 2)), p?.thickness_mm ?? 12.7, p?.element_sites ?? 8);
  }, [bom]);

  if (!open || !design) return null;
  const download = async () => {
    if (!bom) return;
    setDl(true);
    try {
      const { blob, name } = await api.buildKit(design, bom);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } finally { setDl(false); }
  };
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal kit-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Build kit">
        <div className="modal-head">
          <Package size={15} />
          <h3>Build kit</h3>
          <span className="muted mono" style={{ fontSize: 12 }}>{design.name}</span>
          <div className="tabs kit-tabs">
            <button className={`tab${tab === "parts" ? " active" : ""}`} onClick={() => setTab("parts")}><ShoppingCart size={13} /> Parts</button>
            <button className={`tab${tab === "print" ? " active" : ""}`} onClick={() => setTab("print")}><Printer size={13} /> 3D print</button>
          </div>
          <span className="spacer" />
          <button className="btn primary" onClick={download} disabled={!bom || dl}>{dl ? <LoaderCircle size={13} className="spin" /> : <Download size={13} />} {mock ? "Download BOM (.csv)" : "Download build kit (.zip)"}</button>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={15} /></button>
        </div>
        <div className="kit-body">
          {err && <div className="json-err" style={{ padding: 12 }}>{err}</div>}
          {!bom && !err && <div className="stl-wait"><LoaderCircle size={14} className="spin" /> generating BOM…</div>}
          {bom && tab === "parts" && (
            <div className="kit-parts">
              <table className="bom">
                <thead><tr><th>Part</th><th>Description</th><th>Vendor</th><th className="n">Qty</th><th className="n">Unit</th><th className="n">Line total</th></tr></thead>
                <tbody>
                  <PartsTable rows={bom.purchased} title={`Optics & mounts · ${bom.totals.purchased_parts}`} />
                  <PartsTable rows={bom.hardware} title={`Hardware · ${bom.totals.hardware_parts}`} />
                </tbody>
                <tfoot>
                  <tr><td colSpan={5}>Estimated total (excluding lasers)</td><td className="n mono strong">{usd(bom.totals.est_cost_usd)}</td></tr>
                </tfoot>
              </table>
              <div className="kit-note">Prices are estimates. {bom.totals.price_note}. Hover a row to highlight its elements on the table.</div>
            </div>
          )}
          {bom && tab === "print" && (
            <div className="kit-print">
              <div className="kit-print-list">
                {bom.printed.map((p, i) => (
                  <button key={p.name} className={`print-row${i === sel ? " sel" : ""}`} onClick={() => setSel(i)}>
                    <div className="mono strong">{p.name}</div>
                    <div className="print-stats mono"><span>{p.volume_cm3} cm³</span><span>{p.est_print_h} h</span><span>{p.est_filament_g} g</span></div>
                    <div className="muted" style={{ fontSize: 11.5 }}>{p.notes}</div>
                  </button>
                ))}
                <div className="kit-note">Total {bom.totals.est_print_h} h · {bom.totals.est_filament_g} g filament{bom.plate ? ` · ${bom.plate.element_sites} keyed sites, ${bom.plate.pin_holes} pin holes` : ""}{mock ? " · preview geometry is an offline approximation" : ""}</div>
              </div>
              <div className="stl-view">{part && <StlPreview key={part.name} url={stlUrl} fallback={fallback} />}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
