// Minimal live viewer used until the full App.tsx lands: example picker, view presets, Gaussian beams.
import { useEffect, useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { CameraControls, OrthographicCamera } from "@react-three/drei";
import * as THREE from "three";
import { useStore } from "./store";
import * as api from "./api";
import { Part } from "./scene/parts";
import { envelope, powerOpacity } from "./lib/beam";
import { wavelengthToColor } from "./lib/color";
import type { Design, ExampleInfo, Segment } from "./types";

type View = "top" | "iso" | "front";

// Table frame (x right, y up) → three.js world (X right, Y up out of table, Z = -y).
const toWorld = (x: number, y: number, h = 0) => new THREE.Vector3(x, h, -y);

function Beam({ s, ex }: { s: Segment; ex: number }) {
  const geom = useMemo(() => {
    const pts = envelope(s, ex, 0.25).map(([x, y]) => new THREE.Vector2(x, y));
    return new THREE.ShapeGeometry(new THREE.Shape(pts));
  }, [s, ex]);
  const color = wavelengthToColor(s.wavelength_nm);
  const core = useMemo(
    () => new THREE.BufferGeometry().setFromPoints([toWorld(...s.start, 0.05), toWorld(...s.end, 0.05)]),
    [s],
  );
  return (
    <group>
      <mesh geometry={geom} rotation={[-Math.PI / 2, 0, 0]}>
        <meshBasicMaterial color={color} transparent opacity={powerOpacity(s.power_mw)} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
      <lineSegments geometry={core}>
        <lineBasicMaterial color={color} />
      </lineSegments>
    </group>
  );
}

function Scene({ design, view }: { design: Design; view: View }) {
  const trace = useStore((s) => s.trace);
  const bp = design.baseplate ?? { width_mm: 300, height_mm: 150, thickness_mm: 25.4, optical_height_mm: 12.7, grid_mm: 25.4 };
  const oh = bp.optical_height_mm;
  const cx = bp.width_mm / 2, cy = bp.height_mm / 2;
  const [controls, setControls] = useState<CameraControls | null>(null);

  useEffect(() => {
    if (!controls) return;
    const d = Math.max(bp.width_mm, bp.height_mm) * 2;
    const target = toWorld(cx, cy);
    const eye =
      view === "top" ? toWorld(cx, cy - 0.001, d)
      : view === "front" ? toWorld(cx, cy - d, oh)
      : toWorld(cx + d * 0.6, cy - d * 0.6, d * 0.6);
    controls.setLookAt(eye.x, eye.y, eye.z, target.x, target.y, target.z, true);
  }, [controls, view, bp.width_mm, bp.height_mm, cx, cy, oh]);

  const holes = useMemo(() => {
    const pts: THREE.Vector3[] = [];
    for (let x = bp.grid_mm / 2; x < bp.width_mm; x += bp.grid_mm)
      for (let y = bp.grid_mm / 2; y < bp.height_mm; y += bp.grid_mm) pts.push(toWorld(x, y, -oh + 0.1));
    return pts;
  }, [bp.grid_mm, bp.width_mm, bp.height_mm, oh]);

  return (
    <>
      <OrthographicCamera makeDefault position={[cx, 600, -cy]} zoom={2.2} near={-5000} far={5000} />
      <CameraControls ref={setControls} makeDefault />
      <ambientLight intensity={0.9} />
      <directionalLight position={[200, 400, 300]} intensity={1.4} />
      <mesh position={toWorld(cx, cy, -oh - bp.thickness_mm / 2)}>
        <boxGeometry args={[bp.width_mm, bp.thickness_mm, bp.height_mm]} />
        <meshStandardMaterial color="#d9dce0" roughness={0.85} />
      </mesh>
      {holes.map((p, i) => (
        <mesh key={i} position={p} rotation={[-Math.PI / 2, 0, 0]}>
          <circleGeometry args={[1.6, 12]} />
          <meshBasicMaterial color="#9aa0a7" />
        </mesh>
      ))}
      {trace?.segments.map((s) => <Beam key={s.id} s={s} ex={3} />)}
      {trace?.elements.filter((e) => e.placed && e.position).map((e) => (
        <group key={e.id} position={toWorld(e.position![0], e.position![1])} rotation={[0, THREE.MathUtils.degToRad(e.angle_deg ?? 0), 0]}>
          <Part type={e.type} oh={oh} />
        </group>
      ))}
      {design.sources.map((s) => (
        <group key={s.id} position={toWorld(...s.position)} rotation={[0, THREE.MathUtils.degToRad(s.direction_deg), 0]}>
          <Part type="source" oh={oh} />
        </group>
      ))}
    </>
  );
}

export default function Preview() {
  const { design, report, traceMs, loadDesign } = useStore();
  const [examples, setExamples] = useState<ExampleInfo[]>([]);
  const [view, setView] = useState<View>("iso");

  useEffect(() => {
    api.listExamples().then(async (list) => {
      setExamples(list);
      if (list.length) loadDesign(await api.getExample(list[0].name));
    });
  }, [loadDesign]);

  const btn = (v: View, label: string) => (
    <button onClick={() => setView(v)} style={{ ...ui.btn, ...(view === v ? ui.btnOn : {}) }}>{label}</button>
  );

  return (
    <div style={ui.root}>
      <header style={ui.bar}>
        <strong style={{ letterSpacing: 0.3 }}>Beamline</strong>
        <span style={ui.muted}>preview build</span>
        <select style={ui.select} onChange={async (e) => loadDesign(await api.getExample(e.target.value))}>
          {examples.map((x) => <option key={x.name} value={x.name}>{x.title}</option>)}
        </select>
        <span style={{ flex: 1 }} />
        {btn("top", "Top")}{btn("iso", "Isometric")}{btn("front", "Front")}
      </header>
      <div style={{ flex: 1, position: "relative" }}>
        {design && (
          <Canvas style={{ background: "#f4f5f7" }}>
            <Scene design={design} view={view} />
          </Canvas>
        )}
      </div>
      <footer style={ui.status}>
        <span>{design?.name ?? "—"}</span>
        <span>{report ? `${report.passed ? "PASS" : "FAIL"} · score ${report.score.toFixed(1)}` : ""}</span>
        <span>{report ? `${report.checks.filter((c) => c.severity !== "info").length} checks` : ""}</span>
        <span>{traceMs != null ? `trace ${traceMs.toFixed(1)} ms` : ""}</span>
        <span style={{ flex: 1 }} />
        <span>{api.isMock() ? "MOCK DATA" : "live backend"}</span>
      </footer>
    </div>
  );
}

const ui: Record<string, React.CSSProperties> = {
  root: { position: "fixed", inset: 0, display: "flex", flexDirection: "column", fontFamily: "'IBM Plex Sans', sans-serif", color: "#1d2024", background: "#fff" },
  bar: { display: "flex", alignItems: "center", gap: 12, padding: "8px 16px", borderBottom: "1px solid #e1e4e8", fontSize: 14 },
  muted: { color: "#6b7280", fontSize: 12 },
  select: { font: "inherit", fontSize: 13, padding: "4px 8px", border: "1px solid #d0d4da", borderRadius: 3, background: "#fff" },
  btn: { font: "inherit", fontSize: 13, padding: "4px 10px", border: "1px solid #d0d4da", borderRadius: 3, background: "#fff", cursor: "pointer" },
  btnOn: { background: "#1d2024", color: "#fff", borderColor: "#1d2024" },
  status: { display: "flex", gap: 24, padding: "6px 16px", borderTop: "1px solid #e1e4e8", fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: "#4b5563" },
};
