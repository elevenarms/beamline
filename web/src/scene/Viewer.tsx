import { memo, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { CameraControls, GizmoHelper, GizmoViewcube, Html, Line, OrthographicCamera, PerspectiveCamera } from "@react-three/drei";
import CameraControlsImpl from "camera-controls";
import { useStore } from "../store";
import { PRESET_ANGLES, domRefs, useView } from "./viewStore";
import { Part, partCenterX, partRadius } from "./parts";
import { beamRadius, powerOpacity, zAlong } from "../lib/beam";
import { wavelengthToColor } from "../lib/color";
import { usePalette } from "../lib/theme";
import type { Baseplate, Design, Element, PlacedElement, Segment, TraceResult, Vec2 } from "../types";
import { DEFAULT_BASEPLATE, TERMINATING } from "../types";

const D2R = Math.PI / 180;
const MIN_R = 0.3;
const toW = (x: number, y: number, h = 0): [number, number, number] => [x, h, -y];

// ───────────────────────── baseplate ─────────────────────────

function Plate({ bp }: { bp: Baseplate }) {
  const P = usePalette();
  const { width_mm: W, height_mm: H, thickness_mm: T, optical_height_mm: oh, grid_mm: g } = bp;
  const top = -oh;
  const holes = useMemo(() => {
    const pts: [number, number][] = [];
    for (let x = g / 2; x < W; x += g) for (let y = g / 2; y < H; y += g) pts.push([x, y]);
    return pts;
  }, [W, H, g]);
  const holeRef = useRef<THREE.InstancedMesh>(null);
  useEffect(() => {
    const m = holeRef.current;
    if (!m) return;
    const o = new THREE.Object3D();
    holes.forEach(([x, y], i) => {
      o.position.set(x, top + 0.06, -y);
      o.rotation.set(-Math.PI / 2, 0, 0);
      o.updateMatrix();
      m.setMatrixAt(i, o.matrix);
    });
    m.instanceMatrix.needsUpdate = true;
  }, [holes, top]);
  const gridGeom = useMemo(() => {
    const v: number[] = [];
    for (let x = 0; x <= W + 1e-6; x += g) v.push(x, top + 0.04, 0, x, top + 0.04, -H);
    for (let y = 0; y <= H + 1e-6; y += g) v.push(0, top + 0.04, -y, W, top + 0.04, -y);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(v, 3));
    return geo;
  }, [W, H, g, top]);
  const ticks = useMemo(() => {
    const step = Math.max(W, H) > 1000 ? 100 : Math.max(W, H) > 400 ? 50 : 25;
    // skip ticks that would collide with the axis titles or each other at the origin
    const xs: number[] = [];
    for (let x = 0; x <= W - step * 0.55; x += step) xs.push(x);
    const ys: number[] = [];
    for (let y = step; y <= H - step * 0.55; y += step) ys.push(y);
    return { xs, ys };
  }, [W, H]);
  const plan = useView((v) => v.preset === "top" && v.projection === "ortho");
  return (
    <group>
      <mesh position={[W / 2, top - T / 2, -H / 2]} receiveShadow>
        <boxGeometry args={[W, T, H]} />
        <meshStandardMaterial color={P.plate} roughness={0.85} metalness={0.05} />
      </mesh>
      <lineSegments geometry={gridGeom}>
        <lineBasicMaterial color={P.grid} />
      </lineSegments>
      <instancedMesh ref={holeRef} args={[undefined, undefined, holes.length]} key={holes.length}>
        <circleGeometry args={[1.65, 16]} />
        <meshBasicMaterial color={P.hole} />
      </instancedMesh>
      <Line points={[toW(0, 0, top + 0.1), toW(W, 0, top + 0.1), toW(W, H, top + 0.1), toW(0, H, top + 0.1), toW(0, 0, top + 0.1)]} color={P.outline} lineWidth={1} />
      {/* tick labels stay mounted (hidden outside plan view) to avoid Html root churn */}
      {ticks.xs.map((x) => (
        <Html key={`x${x}`} position={toW(x, -5, top)} center zIndexRange={[5, 0]} className="tick" style={{ visibility: plan ? "visible" : "hidden" }}>{x.toFixed(0)}</Html>
      ))}
      {ticks.ys.map((y) => (
        <Html key={`y${y}`} position={toW(-5, y, top)} center zIndexRange={[5, 0]} className="tick tick-y" style={{ visibility: plan ? "visible" : "hidden" }}>{y.toFixed(0)}</Html>
      ))}
      <Html position={toW(W + 4, -5, top)} center zIndexRange={[5, 0]} className="tick tick-unit" style={{ visibility: plan ? "visible" : "hidden" }}>x mm</Html>
      <Html position={toW(-5, H + 4, top)} center zIndexRange={[5, 0]} className="tick tick-unit" style={{ visibility: plan ? "visible" : "hidden" }}>y mm</Html>
    </group>
  );
}

// ───────────────────────── beams ─────────────────────────

function tubeGeometry(s: Segment, ex: number, n = 24, m = 18) {
  const L = Math.max(s.length_mm, 1e-3);
  const pos: number[] = [];
  const idx: number[] = [];
  for (let i = 0; i <= n; i++) {
    const z = (L * i) / n;
    const r = Math.max(beamRadius(s, z) * ex, MIN_R);
    for (let j = 0; j <= m; j++) {
      const a = (j / m) * Math.PI * 2;
      pos.push(z, r * Math.cos(a), r * Math.sin(a));
    }
  }
  for (let i = 0; i < n; i++)
    for (let j = 0; j < m; j++) {
      const a = i * (m + 1) + j, b = a + m + 1;
      idx.push(a, b, a + 1, b, b + 1, a + 1);
    }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

const segKey = (s: Segment) => `${s.start[0]},${s.start[1]},${s.end[0]},${s.end[1]},${s.w0_mm},${s.waist_z_mm},${s.rayleigh_mm}`;

/** One beam envelope. Geometry is rebuilt only when the segment's geometry actually changes. */
const Beam = memo(function Beam({ s, ex, active, dim }: { s: Segment; ex: number; active: boolean; dim: boolean }) {
  const key = segKey(s);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const geo = useMemo(() => tubeGeometry(s, ex), [key, ex]);
  useEffect(() => () => geo.dispose(), [geo]);
  const P = usePalette();
  const color = useMemo(() => wavelengthToColor(s.wavelength_nm, P.darkBg), [s.wavelength_nm, P.darkBg]);
  const ang = Math.atan2(s.end[1] - s.start[1], s.end[0] - s.start[0]);
  const op = powerOpacity(s.power_mw);
  const onMove = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    const p: Vec2 = [e.point.x, -e.point.z];
    const v = useView.getState();
    v.setCursor(p);
    v.setTooltip({ segId: s.id, z: zAlong(s, p), sx: e.nativeEvent.clientX, sy: e.nativeEvent.clientY });
    if (useStore.getState().hoverSeg !== s.id) useStore.getState().setHoverSeg(s.id);
  };
  return (
    <group position={toW(s.start[0], s.start[1])} rotation={[0, ang, 0]}>
      <mesh
        geometry={geo}
        renderOrder={2}
        onPointerMove={onMove}
        onPointerOut={() => { useView.getState().setTooltip(null); useStore.getState().setHoverSeg(null); }}
        onClick={(e) => { e.stopPropagation(); useStore.getState().select({ kind: "segment", id: s.id }); }}
      >
        <meshBasicMaterial color={color} transparent opacity={Math.min(0.9, (dim ? 0.1 : active ? 0.6 : 0.42) * (0.45 + op) * P.beamOpacity)} depthWrite={false} side={THREE.DoubleSide} />
      </mesh>
      {active && (
        <>
          <Line points={[[0, 0, 0], [s.length_mm, 0, 0]]} color={P.beamCore ?? color} lineWidth={2.4} renderOrder={4} />
          <Line points={[[0, 0, 0], [s.length_mm, 0, 0]]} color={P.sel} lineWidth={0.8} dashed dashSize={2} gapSize={2} renderOrder={5} />
        </>
      )}
    </group>
  );
});

/** All beam centre lines in a single draw call (vertex-coloured line segments). */
function CoreLines({ segs, dimSet }: { segs: Segment[]; dimSet: Set<string> | null }) {
  const P = usePalette();
  const geo = useMemo(() => {
    const pos = new Float32Array(segs.length * 6);
    const col = new Float32Array(segs.length * 6);
    const c = new THREE.Color();
    segs.forEach((s, i) => {
      pos.set([s.start[0], 0, -s.start[1], s.end[0], 0, -s.end[1]], i * 6);
      c.set(P.beamCore ?? wavelengthToColor(s.wavelength_nm, P.darkBg));
      if (dimSet && dimSet.has(s.id)) c.lerp(new THREE.Color(P.plate), 0.75);
      col.set([c.r, c.g, c.b, c.r, c.g, c.b], i * 6);
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    return g;
  }, [segs, dimSet, P]);
  useEffect(() => () => geo.dispose(), [geo]);
  return (
    <lineSegments geometry={geo} renderOrder={3} raycast={() => null}>
      <lineBasicMaterial vertexColors transparent opacity={P.beamCore ? 0.85 : 0.95} depthWrite={false} />
    </lineSegments>
  );
}

// ───────────────────────── elements ─────────────────────────

interface Item {
  id: string;
  kind: "element" | "source";
  type: Element["type"] | "source";
  pos: Vec2;
  angle: number;
  el?: Element;
  pe?: PlacedElement;
  group: string | null;
}

function buildItems(design: Design, trace: TraceResult | null): Item[] {
  const items: Item[] = [];
  for (const s of design.sources) items.push({ id: s.id, kind: "source", type: "source", pos: s.position, angle: s.direction_deg, group: s.group ?? null });
  if (!trace) return items;
  const byId = new Map((design.elements ?? []).map((e) => [e.id, e]));
  const incoming = new Map<string, Segment>();
  for (const sg of trace.segments) if (sg.end_element && !incoming.has(sg.end_element)) incoming.set(sg.end_element, sg);
  for (const pe of trace.elements) {
    if (!pe.position) continue;
    let angle = pe.angle_deg ?? 0;
    if (TERMINATING.has(pe.type)) {
      const inc = incoming.get(pe.id);
      if (inc) angle = Math.atan2(inc.end[1] - inc.start[1], inc.end[0] - inc.start[0]) / D2R;
    }
    const el = byId.get(pe.id);
    items.push({ id: pe.id, kind: "element", type: pe.type, pos: pe.position, angle, el, pe, group: el?.group ?? null });
  }
  return items;
}

function itemCenter(it: Item): Vec2 {
  const cx = partCenterX(it.type);
  return [it.pos[0] + Math.cos(it.angle * D2R) * cx, it.pos[1] + Math.sin(it.angle * D2R) * cx];
}

function distPointSeg(p: Vec2, a: Vec2, b: Vec2) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const L2 = dx * dx + dy * dy || 1;
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2));
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}

/** greedy leader-label placement: 12 candidate directions, avoid beams, parts and other labels */
type LabelPos = { at: Vec2; from: Vec2; cost: number };
function placeLabels(items: Item[], segs: Segment[]): Map<string, LabelPos> {
  const out = new Map<string, LabelPos>();
  const placed: Vec2[] = [];
  const centers = items.map(itemCenter);
  items.forEach((it, i) => {
    const c = centers[i];
    const r = partRadius(it.type);
    let best: { at: Vec2; from: Vec2; cost: number } | null = null;
    for (let k = 0; k < 12; k++) {
      const a = (k / 12) * Math.PI * 2 + Math.PI / 2;
      const d = r + 11;
      const at: Vec2 = [c[0] + Math.cos(a) * d, c[1] + Math.sin(a) * d];
      let cost = k === 0 ? 0 : 0.5; // prefer "above"
      for (const s of segs) {
        // cheap bounding-box reject before the exact distance
        if (at[0] < Math.min(s.start[0], s.end[0]) - 9 || at[0] > Math.max(s.start[0], s.end[0]) + 9 || at[1] < Math.min(s.start[1], s.end[1]) - 9 || at[1] > Math.max(s.start[1], s.end[1]) + 9) continue;
        const dd = distPointSeg(at, s.start, s.end);
        if (dd < 9) cost += (9 - dd) * 2;
      }
      centers.forEach((o, j) => {
        if (j === i || Math.abs(o[0] - at[0]) > 60 || Math.abs(o[1] - at[1]) > 60) return;
        const dd = Math.hypot(at[0] - o[0], at[1] - o[1]) - partRadius(items[j].type);
        if (dd < 8) cost += (8 - dd) * 3;
      });
      for (const p of placed) {
        const dd = Math.hypot(at[0] - p[0], (at[1] - p[1]) * 1.8);
        if (dd < 18) cost += (18 - dd) * 4;
      }
      if (!best || cost < best.cost) best = { at, from: [c[0] + Math.cos(a) * (r - 2), c[1] + Math.sin(a) * (r - 2)], cost };
    }
    out.set(it.id, { at: best!.at, from: best!.from, cost: best!.cost });
    placed.push(best!.at);
  });
  return out;
}

function ringPoints(c: Vec2, r: number, h: number): [number, number, number][] {
  const pts: [number, number, number][] = [];
  for (let i = 0; i <= 64; i++) {
    const a = (i / 64) * Math.PI * 2;
    pts.push(toW(c[0] + Math.cos(a) * r, c[1] + Math.sin(a) * r, h));
  }
  return pts;
}

type NodeProps = { it: Item; oh: number; selected: boolean; warn: "error" | "warning" | null; label?: LabelPos; labelsOn: boolean; dim: boolean };
const sameNode = (a: NodeProps, b: NodeProps) =>
  a.oh === b.oh && a.selected === b.selected && a.warn === b.warn && a.labelsOn === b.labelsOn && a.dim === b.dim &&
  a.it.id === b.it.id && a.it.type === b.it.type && a.it.angle === b.it.angle && a.it.pos[0] === b.it.pos[0] && a.it.pos[1] === b.it.pos[1] &&
  a.it.el?.aperture_mm === b.it.el?.aperture_mm && a.it.el?.focal_length_mm === b.it.el?.focal_length_mm && a.it.pe?.error === b.it.pe?.error &&
  a.label?.at[0] === b.label?.at[0] && a.label?.at[1] === b.label?.at[1] && a.label?.cost === b.label?.cost;

const LABEL_MAX_COST = 30;
const ElementNode = memo(function ElementNode({ it, oh, selected, warn, label: labelPos, labelsOn, dim }: NodeProps) {
  const select = useStore((s) => s.select);
  const focus = useView((v) => v.focus);
  const [hover, setHover] = useState(false);
  // decluttering: labels show when zoomed in and not overlapping, or always on hover / selection
  const label = labelPos && (selected || hover || (labelsOn && !dim && labelPos.cost < LABEL_MAX_COST)) ? labelPos : undefined;
  const c = itemCenter(it);
  const r = partRadius(it.type);
  const unplacedErr = it.pe?.error;
  const plan = useView((v) => v.preset === "top" && v.projection === "ortho");
  const P = usePalette();
  const lift = it.type === "source" ? 10 : 0;
  return (
    <group>
      <group
        position={toW(it.pos[0], it.pos[1])}
        rotation={[0, it.angle * D2R, 0]}
        onClick={(e) => { e.stopPropagation(); select({ kind: it.kind, id: it.id }); }}
        onDoubleClick={(e) => { e.stopPropagation(); focus(c[0], c[1], r); }}
        onPointerOver={(e) => { e.stopPropagation(); setHover(true); document.body.style.cursor = "pointer"; }}
        onPointerOut={() => { setHover(false); document.body.style.cursor = ""; }}
      >
        <Part type={it.type} oh={oh} sel={selected} hi={hover && !selected} dim={dim && !selected} aperture={it.el?.aperture_mm ?? undefined} focal={it.el?.focal_length_mm ?? undefined} />
      </group>
      {(selected || warn) && (
        <Line points={ringPoints(c, r + 4, -oh + 0.3)} color={selected ? P.sel : warn === "error" ? P.err : P.warn} lineWidth={selected ? 1.8 : 1.2} dashed={!selected} dashSize={3} gapSize={2} />
      )}
      {label && (
        <>
          {plan ? (
            <Line points={[toW(label.from[0], label.from[1], 0.5), toW(label.at[0], label.at[1], 0.5)]} color={P.leader} lineWidth={0.8} />
          ) : (
            <Line points={[toW(c[0], c[1], 16), toW(c[0], c[1], 30 + lift)]} color={P.leader} lineWidth={0.8} />
          )}
          <Html position={plan ? toW(label.at[0], label.at[1], 0.5) : toW(c[0], c[1], 34 + lift)} center zIndexRange={[10, 0]}>
            <div
              className={`elabel${selected ? " sel" : ""}${warn ? ` ${warn}` : ""}${unplacedErr ? " unplaced" : ""}`}
              onClick={() => select({ kind: it.kind, id: it.id })}
              onDoubleClick={() => focus(c[0], c[1], r)}
            >
              {it.id}
            </div>
          </Html>
        </>
      )}
    </group>
  );
}, sameNode);

// ───────────────────────── camera rig ─────────────────────────

function fitBox(bp: Baseplate, trace: TraceResult | null, sources: Design["sources"] = []): THREE.Box3 {
  // note: toW flips y → z, so build the box from points (min/max normalised)
  const b = new THREE.Box3().setFromPoints([new THREE.Vector3(...toW(0, 0, -bp.optical_height_mm - bp.thickness_mm)), new THREE.Vector3(...toW(bp.width_mm, bp.height_mm, 30))]);
  // beams that leave the plate are included only up to a small margin, so Fit keeps the plate centred
  const cl = (x: number, y: number, m = 25) => toW(Math.min(Math.max(x, -m), bp.width_mm + m), Math.min(Math.max(y, -m), bp.height_mm + m));
  for (const s of trace?.segments ?? []) {
    b.expandByPoint(new THREE.Vector3(...cl(s.start[0], s.start[1])));
    b.expandByPoint(new THREE.Vector3(...cl(s.end[0], s.end[1])));
  }
  for (const src of sources) {
    const a = src.direction_deg * D2R;
    b.expandByPoint(new THREE.Vector3(...cl(src.position[0] - Math.cos(a) * 62, src.position[1] - Math.sin(a) * 62, 70)));
  }
  b.expandByVector(new THREE.Vector3(10, 2, 10));
  return b;
}


/** Frame a box at the given orientation without camera-controls' fitToBox (which snaps the angles to 90°). */
const viewSize = { w: 1000, h: 800 };
/** current orientation; the plan view is locked to its preset (avoids azimuth noise near the pole) */
function curAngles(ctl: CameraControlsImpl): [number, number] {
  const v = useView.getState();
  if (v.projection === "ortho" && v.preset === "top") return PRESET_ANGLES.top;
  return [ctl.azimuthAngle, ctl.polarAngle];
}
function fitView(ctl: CameraControlsImpl, box: THREE.Box3, az: number, polar: number, animate: boolean) {
  const cam = ctl.camera as THREE.OrthographicCamera | THREE.PerspectiveCamera;
  // keep the design clear of the overlays: toolbar (top), view cube (top-right), legend (bottom-left)
  const legend = useView.getState().legendOpen;
  const wide = viewSize.w > 900;
  const inset = { top: 58, bottom: legend && !wide ? 250 : 44, left: legend && wide ? 232 : 24, right: 24 };
  const W = Math.max(viewSize.w - inset.left - inset.right, 120), H = Math.max(viewSize.h - inset.top - inset.bottom, 120);
  const o = new THREE.Vector3(Math.sin(polar) * Math.sin(az), Math.cos(polar), Math.sin(polar) * Math.cos(az)).normalize();
  const r = new THREE.Vector3(Math.cos(az), 0, -Math.sin(az));
  const u = new THREE.Vector3().crossVectors(o, r).normalize();
  const c = box.getCenter(new THREE.Vector3());
  let maxR = 0, maxU = 0, maxD = 0;
  const p = new THREE.Vector3();
  for (let i = 0; i < 8; i++) {
    p.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z).sub(c);
    maxR = Math.max(maxR, Math.abs(p.dot(r)));
    maxU = Math.max(maxU, Math.abs(p.dot(u)));
    maxD = Math.max(maxD, Math.abs(p.dot(o)));
  }
  ctl.rotateTo(az, polar, animate);
  if ((cam as THREE.OrthographicCamera).isOrthographicCamera) {
    const zoom = Math.min(W / (2 * maxR), H / (2 * maxU));
    // shift the target so the box centre lands in the middle of the free area, not the canvas
    const dx = (inset.left - inset.right) / 2 / zoom, dy = (inset.top - inset.bottom) / 2 / zoom;
    const t = c.clone().addScaledVector(r, -dx).addScaledVector(u, dy);
    ctl.moveTo(t.x, t.y, t.z, animate); // moveTo keeps the spherical angles
    ctl.dollyTo(3000, false);
    ctl.zoomTo(zoom, animate);
  } else {
    ctl.moveTo(c.x, c.y, c.z, animate);
    const pc = cam as THREE.PerspectiveCamera;
    const tn = Math.tan((pc.fov * Math.PI) / 360);
    const d = Math.max(maxU / tn, maxR / (tn * (W / H))) + maxD;
    ctl.dollyTo(d, animate);
  }
}

const savedPose = { az: PRESET_ANGLES.top[0], polar: PRESET_ANGLES.top[1], target: new THREE.Vector3(), has: false };

function CameraRig({ bp, trace, designKey, sources }: { bp: Baseplate; trace: TraceResult | null; designKey: string; sources: Design["sources"] }) {
  const srcRef = useRef(sources);
  srcRef.current = sources;
  const size = useThree((st) => st.size);
  viewSize.w = size.width;
  viewSize.h = size.height;
  const { projection, preset, req } = useView();
  const [ctl, setCtl] = useState<CameraControlsImpl | null>(null);
  const traceRef = useRef(trace);
  traceRef.current = trace;
  const bpRef = useRef(bp);
  bpRef.current = bp;
  const lastKey = useRef<string | null>(null);
  const lastReq = useRef(-1);

  // mouse mapping: plan view pans with the left button; other views orbit
  useEffect(() => {
    if (!ctl) return;
    const A = CameraControlsImpl.ACTION;
    ctl.mouseButtons.left = preset === "top" ? A.TRUCK : A.ROTATE;
    ctl.mouseButtons.right = A.TRUCK;
    ctl.mouseButtons.wheel = projection === "ortho" ? A.ZOOM : A.DOLLY;
    ctl.touches.one = preset === "top" ? A.TOUCH_TRUCK : A.TOUCH_ROTATE;
    ctl.dollyToCursor = true;
    ctl.smoothTime = 0.12;
    ctl.draggingSmoothTime = 0.06;
    ctl.minZoom = 0.2;
    ctl.maxZoom = 60;
    // plan view is locked: exactly top-down, +x right, +y up — no orbiting
    const lock = preset === "top" && projection === "ortho";
    ctl.minPolarAngle = lock ? PRESET_ANGLES.top[1] : 0;
    ctl.maxPolarAngle = lock ? PRESET_ANGLES.top[1] : Math.PI;
    ctl.minAzimuthAngle = lock ? 0 : -Infinity;
    ctl.maxAzimuthAngle = lock ? 0 : Infinity;
  }, [ctl, preset, projection]);

  // remember orientation so a projection switch keeps the view
  useEffect(() => {
    if (!ctl) return;
    const save = () => {
      savedPose.az = ctl.azimuthAngle;
      savedPose.polar = ctl.polarAngle;
      ctl.getTarget(savedPose.target);
      savedPose.has = true;
    };
    ctl.addEventListener("update", save);
    return () => ctl.removeEventListener("update", save);
  }, [ctl]);

  // new camera instance (projection switch or first mount): restore pose instantly
  useEffect(() => {
    if (!ctl) return;
    const box = fitBox(bpRef.current, traceRef.current, srcRef.current);
    if (savedPose.has && useView.getState().preset !== "top") fitView(ctl, box, savedPose.az, savedPose.polar, false);
    else fitView(ctl, box, ...PRESET_ANGLES.top, false);
  }, [ctl]);

  // view requests (presets, fit, focus)
  useEffect(() => {
    if (!ctl || req.n === lastReq.current) return;
    lastReq.current = req.n;
    const box = fitBox(bpRef.current, traceRef.current, srcRef.current);
    if (req.kind === "preset" && preset !== "free") {
      fitView(ctl, box, ...PRESET_ANGLES[preset], true);
    } else if (req.kind === "fit") {
      fitView(ctl, box, ...curAngles(ctl), true);
    } else if (req.kind === "focusBox") {
      const b = new THREE.Box3(new THREE.Vector3(...toW(req.x - 10, req.y - 10, -bpRef.current.optical_height_mm)), new THREE.Vector3(...toW(req.x + req.w + 10, req.y + req.h + 10, 20)));
      // toW flips y → normalise min/max
      const bb = new THREE.Box3().setFromPoints([b.min, b.max]);
      fitView(ctl, bb, ...curAngles(ctl), true);
    } else if (req.kind === "focus") {
      const c = new THREE.Vector3(...toW(req.x, req.y));
      const rr = req.r * 2.2;
      fitView(ctl, new THREE.Box3(c.clone().addScalar(-rr), c.clone().addScalar(rr)), ...curAngles(ctl), true);
    }
  }, [ctl, req, preset]);

  // refit when the viewport is resized substantially (e.g. the comparison split opens)
  const lastSize = useRef({ w: size.width, h: size.height });
  useEffect(() => {
    if (!ctl) return;
    const d = Math.abs(size.width - lastSize.current.w) + Math.abs(size.height - lastSize.current.h);
    if (d < 40) return;
    lastSize.current = { w: size.width, h: size.height };
    const t = setTimeout(() => fitView(ctl, fitBox(bpRef.current, traceRef.current, srcRef.current), ...curAngles(ctl), true), 120);
    return () => clearTimeout(t);
  }, [ctl, size.width, size.height]);

  // refit only when a NEW design is loaded (not on re-trace / edits)
  useEffect(() => {
    if (!ctl || !trace) return;
    if (lastKey.current === designKey) return;
    const first = lastKey.current == null;
    lastKey.current = designKey;
    fitView(ctl, fitBox(bpRef.current, trace, srcRef.current), ...curAngles(ctl), !first);
  }, [ctl, designKey, trace]);

  return (
    <>
      {projection === "ortho" ? (
        <OrthographicCamera key="o" makeDefault position={[150, 2500, 100]} zoom={2} near={1} far={20000} />
      ) : (
        <PerspectiveCamera key="p" makeDefault position={[150, 400, 400]} fov={35} near={1} far={20000} />
      )}
      <CameraControls key={projection} ref={setCtl} makeDefault />
      <ScaleBarWriter />
    </>
  );
}

const NICE = [1, 2, 5, 10, 20, 25, 50, 100, 200, 500];
function ScaleBarWriter() {
  const camera = useThree((s) => s.camera);
  const last = useRef("");
  useFrame(() => {
    const bar = domRefs.scaleBar, lbl = domRefs.scaleLabel;
    if (!bar || !lbl) return;
    if (!(camera as THREE.OrthographicCamera).isOrthographicCamera) {
      if (last.current !== "hide") { bar.parentElement!.style.visibility = "hidden"; last.current = "hide"; }
      return;
    }
    const pxPerMm = (camera as THREE.OrthographicCamera).zoom;
    const ok = pxPerMm >= 1.45;
    if (useView.getState().labelsZoomOk !== ok) useView.setState({ labelsZoomOk: ok });
    const want = 110 / pxPerMm;
    const L = NICE.find((v) => v >= want * 0.6) ?? 500;
    const key = `${L}|${pxPerMm.toFixed(3)}`;
    if (key === last.current) return;
    last.current = key;
    bar.parentElement!.style.visibility = "visible";
    bar.style.width = `${L * pxPerMm}px`;
    lbl.textContent = `${L} mm`;
  });
  return null;
}

// ───────────────────────── viewer ─────────────────────────

const EMPTY_SEGS: Segment[] = [];

/** Module regions: subtle outlines with a title chip; regions with no parts yet are drawn as planned placeholders. */
function ModuleRegions({ design, items, oh, solo }: { design: Design; items: Item[]; oh: number; solo: string | null }) {
  const P = usePalette();
  const focusBox = useView((v) => v.focusBox);
  const filled = useMemo(() => new Set(items.map((i) => i.group)), [items]);
  const h = -oh + 0.25;
  return (
    <group>
      {(design.modules ?? []).map((m) => {
        const [x, y, w, hh] = m.region;
        const planned = !filled.has(m.id);
        const faded = !!solo && solo !== m.id;
        return (
          <group key={m.id}>
            <Line
              points={[toW(x, y, h), toW(x + w, y, h), toW(x + w, y + hh, h), toW(x, y + hh, h), toW(x, y, h)]}
              color={planned ? P.warn : P.outline}
              lineWidth={planned ? 1.6 : 1}
              dashed={planned}
              dashSize={6}
              gapSize={4}
              transparent
              opacity={faded ? 0.3 : 0.9}
            />
            {planned && (
              <mesh position={[x + w / 2, h - 0.05, -(y + hh / 2)]} rotation={[-Math.PI / 2, 0, 0]} raycast={() => null}>
                <planeGeometry args={[w, hh]} />
                <meshBasicMaterial color={P.warn} transparent opacity={0.07} depthWrite={false} />
              </mesh>
            )}
            <Html position={toW(x + 3, y + hh - 3, h)} zIndexRange={[8, 0]} style={{ pointerEvents: "auto" }}>
              <div className={`mlabel${planned ? " planned" : ""}${faded ? " faded" : ""}`} onClick={() => focusBox(x, y, w, hh)} title={m.description || m.title || m.id}>
                {m.title || m.id}{planned ? " · planned" : ""}
              </div>
            </Html>
          </group>
        );
      })}
    </group>
  );
}

export default function Viewer() {
  const P = usePalette();
  const design = useStore((s) => s.design);
  const trace = useStore((s) => s.trace);
  const report = useStore((s) => s.report);
  const selected = useStore((s) => s.selected);
  const hoverSeg = useStore((s) => s.hoverSeg);
  const ex = useStore((s) => s.exaggeration);
  const select = useStore((s) => s.select);
  const setCursor = useView((v) => v.setCursor);
  const setPreset = useView((v) => v.setPreset);

  const bp = { ...DEFAULT_BASEPLATE, ...(design?.baseplate ?? {}) };
  const oh = bp.optical_height_mm;
  const items = useMemo(() => (design ? buildItems(design, trace) : []), [design, trace]);
  const labels = useMemo(() => placeLabels(items, trace?.segments ?? []), [items, trace]);
  const warnBy = useMemo(() => {
    const m = new Map<string, "error" | "warning">();
    for (const c of report?.checks ?? []) {
      if (!c.element_id || c.severity === "info") continue;
      if (c.severity === "error" || !m.has(c.element_id)) m.set(c.element_id, c.severity);
    }
    return m;
  }, [report]);
  const solo = useStore((s) => s.soloModule);
  const plan = useView((v) => v.preset === "top" && v.projection === "ortho");
  const zoomOk = useView((v) => v.labelsZoomOk);
  const labelsOn = plan ? zoomOk : items.length <= 60;
  const segs = trace?.segments ?? EMPTY_SEGS;
  const dimSet = useMemo(() => {
    if (!solo || !design) return null;
    const srcGroup = new Map(design.sources.map((x) => [x.id, x.group ?? null]));
    return new Set(segs.filter((x) => srcGroup.get(x.source_id) !== solo).map((x) => x.id));
  }, [solo, design, segs]);
  const designKey = design ? `${design.name}|${bp.width_mm}|${bp.height_mm}` : "";
  const selSeg = selected?.kind === "segment" ? selected.id : null;
  const selBranch = selSeg ? trace?.segments.find((s) => s.id === selSeg)?.branch : null;

  return (
    <Canvas
      dpr={[1, 2]}
      gl={{ antialias: true, preserveDrawingBuffer: true }}
      onPointerMissed={() => select(null)}
      style={{ background: "var(--canvas)" }}
    >
      <ambientLight intensity={1.1} />
      <hemisphereLight args={["#ffffff", P.darkBg ? "#3a414b" : "#b8bec6", 0.9]} />
      <directionalLight position={[-200, 600, 300]} intensity={1.4} />
      <directionalLight position={[300, 200, -400]} intensity={0.4} />
      <CameraRig bp={bp} trace={trace} designKey={designKey} sources={design?.sources ?? []} />
      {design && <Plate bp={bp} />}
      {/* invisible beam-plane catcher for cursor readout */}
      <mesh
        position={[bp.width_mm / 2, -oh + 0.01, -bp.height_mm / 2]}
        rotation={[-Math.PI / 2, 0, 0]}
        onPointerMove={(e) => setCursor([e.point.x, -e.point.z])}
        onPointerOut={() => setCursor(null)}
      >
        <planeGeometry args={[bp.width_mm * 4, bp.height_mm * 4]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>
      {design?.modules?.length ? <ModuleRegions design={design} items={items} oh={oh} solo={solo} /> : null}
      {segs.map((s) => (
        <Beam key={s.id} s={s} ex={ex} active={s.id === selSeg || s.id === hoverSeg || (!!selBranch && s.branch === selBranch)} dim={!!dimSet?.has(s.id)} />
      ))}
      <CoreLines segs={segs} dimSet={dimSet} />
      {items.map((it) => (
        <ElementNode
          key={it.id}
          it={it}
          oh={oh}
          selected={selected?.id === it.id && selected.kind === it.kind}
          warn={warnBy.get(it.id) ?? null}
          label={labels.get(it.id)}
          labelsOn={labelsOn}
          dim={!!solo && it.group !== solo}
        />
      ))}
      <GizmoHelper alignment="top-right" margin={[62, 62]}>
        <GizmoViewcube
          key={P.darkBg ? "d" : "l"}
          color={P.gizmo.color}
          hoverColor={P.gizmo.hover}
          textColor={P.gizmo.text}
          strokeColor={P.gizmo.stroke}
          opacity={1}
          font="500 18px IBM Plex Sans, sans-serif"
          faces={["Side", "Left", "Top", "Bottom", "Front", "Back"]}
          onClick={(e) => {
            e.stopPropagation();
            const n = e.face?.normal;
            if (!n) return null;
            if (n.y > 0.9) setPreset("top");
            else if (n.z > 0.9) setPreset("front");
            else if (n.x > 0.9) setPreset("side");
            else {
              // other faces: snap orthographically to that face
              const az = Math.atan2(n.x, n.z), polar = Math.acos(Math.max(-1, Math.min(1, n.y)));
              useView.setState({ preset: "iso", projection: "ortho" });
              customSnap(az, polar);
            }
            return null;
          }}
        />
      </GizmoHelper>
      <SnapHandler />
    </Canvas>
  );
}

// snapping to arbitrary gizmo faces (Left/Back/Bottom)
let snapReq: { az: number; polar: number; n: number } = { az: 0, polar: 0, n: 0 };
const snapListeners = new Set<() => void>();
function customSnap(az: number, polar: number) {
  snapReq = { az, polar: Math.min(Math.max(polar, 1e-4), Math.PI - 1e-4), n: snapReq.n + 1 };
  snapListeners.forEach((f) => f());
}
function SnapHandler() {
  const controls = useThree((s) => s.controls) as unknown as CameraControlsImpl | null;
  useEffect(() => {
    const f = () => controls?.rotateTo(snapReq.az, snapReq.polar, true);
    snapListeners.add(f);
    return () => { snapListeners.delete(f); };
  }, [controls]);
  return null;
}
