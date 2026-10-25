import { Edges } from "@react-three/drei";
import type { ElementType } from "../types";
import { createContext, useContext } from "react";
import { usePalette, type ScenePalette } from "../lib/theme";

const DimCtx = createContext(false);
const useDimCtx = () => useContext(DimCtx);

// Stylised optomechanics in a local frame: +X = element axis (table angle), +Y = up (beam at y = 0),
// -Z = table +v. Neutral CAD-like materials with crisp dark edges; colour is reserved for beams.

function mats(P: ScenePalette, dim = false) {
  const m = {
    anod: { color: P.anod, roughness: 0.55, metalness: 0.2 },
    steel: { color: P.steel, roughness: 0.35, metalness: 0.5 },
    housing: { color: P.housing, roughness: 0.7, metalness: 0 },
    glass: { color: P.glass, roughness: 0.1, metalness: 0, transparent: true, opacity: P.glassOpacity },
    coat: { color: P.coat, roughness: 0.15, metalness: 0.7 },
    plate: { color: P.wp, roughness: 0.2, metalness: 0, transparent: true, opacity: 0.6 },
    black: { color: P.black, roughness: 0.9, metalness: 0 },
  };
  if (dim) for (const k of Object.keys(m) as (keyof typeof m)[]) m[k] = { ...m[k], transparent: true, opacity: 0.22 } as never;
  return m;
}

function E({ sel, hi, dim }: { sel?: boolean; hi?: boolean; dim?: boolean }) {
  const P = usePalette();
  if (dim) return null;
  return <Edges threshold={20} color={sel ? P.sel : hi ? P.hover : P.edge} lineWidth={sel || hi ? 2 : 1} />;
}

function Post({ oh, under = 6 }: { oh: number; under?: number }) {
  const MAT = mats(usePalette());
  if (useDimCtx()) return null;
  const h = Math.max(oh - under, 0.5);
  return (
    <group>
      <mesh position={[0, -under - h / 2, 0]}>
        <cylinderGeometry args={[4.5, 4.5, h, 20]} />
        <meshStandardMaterial {...MAT.steel} />
      </mesh>
      <mesh position={[0, -oh + 1, 0]}>
        <cylinderGeometry args={[7.5, 7.5, 2, 24]} />
        <meshStandardMaterial {...MAT.anod} />
      </mesh>
    </group>
  );
}

// cylinder whose axis is local X
function XCyl({ r, len, x = 0, seg = 32, mat, sel, hi, dim }: { r: number; len: number; x?: number; seg?: number; mat: object; sel?: boolean; hi?: boolean; dim?: boolean }) {
  return (
    <mesh position={[x, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
      <cylinderGeometry args={[r, r, len, seg]} />
      <meshStandardMaterial {...mat} />
      <E sel={sel} hi={hi} dim={dim} />
    </mesh>
  );
}

function Box({ size, pos = [0, 0, 0], mat, rotY = 0, sel, hi, dim, edges = true }: { size: [number, number, number]; pos?: [number, number, number]; mat: object; rotY?: number; sel?: boolean; hi?: boolean; dim?: boolean; edges?: boolean }) {
  return (
    <mesh position={pos} rotation={[0, rotY, 0]}>
      <boxGeometry args={size} />
      <meshStandardMaterial {...mat} />
      {edges && <E sel={sel} hi={hi} dim={dim} />}
    </mesh>
  );
}

type PartProps = { type: ElementType | "source"; oh: number; sel?: boolean; hi?: boolean; aperture?: number; focal?: number; dim?: boolean };
export function Part(props: PartProps) {
  return <DimCtx.Provider value={!!props.dim}><PartInner {...props} /></DimCtx.Provider>;
}

function PartInner({ type, oh, sel, hi, aperture, focal, dim }: PartProps) {
  const s = { sel, hi, dim };
  const P = usePalette();
  const MAT = mats(P, dim);
  switch (type) {
    case "mirror":
      return (
        <group>
          <XCyl r={12.7} len={6} x={-3} mat={MAT.coat} {...s} />
          <Box size={[5, 32, 32]} pos={[-8.5, 0, 0]} mat={MAT.anod} {...s} />
          <Post oh={oh} under={16} />
        </group>
      );
    case "lens": {
      const neg = (focal ?? 1) < 0;
      return (
        <group>
          <mesh scale={[neg ? 0.12 : 0.22, 1, 1]}>
            <sphereGeometry args={[12.7, 32, 16]} />
            <meshStandardMaterial {...MAT.glass} />
          </mesh>
          <mesh rotation={[0, Math.PI / 2, 0]}>
            <torusGeometry args={[14, 1.6, 10, 40]} />
            <meshStandardMaterial {...MAT.anod} />
            <E {...s} />
          </mesh>
          <Post oh={oh} under={15.5} />
        </group>
      );
    }
    case "half_wave_plate":
    case "quarter_wave_plate":
      return (
        <group>
          <XCyl r={11} len={1.6} mat={MAT.plate} {...s} />
          <mesh rotation={[0, Math.PI / 2, 0]}>
            <torusGeometry args={[12.6, 1.8, 10, 40]} />
            <meshStandardMaterial {...MAT.anod} />
            <E {...s} />
          </mesh>
          <Post oh={oh} under={14.4} />
        </group>
      );
    case "pbs":
    case "beamsplitter":
    case "dichroic":
      return (
        <group>
          <Box size={[12.7, 12.7, 12.7]} mat={MAT.glass} {...s} />
          <Box size={[17.6, 12.6, 0.35]} rotY={Math.PI / 4} mat={type === "pbs" ? MAT.coat : MAT.plate} edges={false} />
          <Box size={[20, 3, 20]} pos={[0, -7.85, 0]} mat={MAT.anod} />
          <Post oh={oh} under={9.35} />
        </group>
      );
    case "sampler":
      return (
        <group>
          <Box size={[25.4, 25.4, 2]} rotY={Math.PI / 4} mat={MAT.glass} {...s} />
          <Post oh={oh} under={12.7} />
        </group>
      );
    case "aom":
      return (
        <group>
          <Box size={[14, 18, 34]} pos={[0, 0, 4]} mat={MAT.housing} {...s} />
          <Box size={[14.2, 3, 3]} pos={[0, 0, 0]} mat={MAT.black} edges={false} />
          <mesh position={[0, 5, 21]} rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[2.2, 2.2, 6, 16]} />
            <meshStandardMaterial {...MAT.steel} />
          </mesh>
          <Post oh={oh} under={9} />
        </group>
      );
    case "iris": {
      const a = Math.max((aperture ?? 2) / 2, 0.8);
      return (
        <group>
          <mesh rotation={[0, Math.PI / 2, 0]}>
            <ringGeometry args={[a, 12, 40]} />
            <meshStandardMaterial {...MAT.anod} side={2} />
          </mesh>
          <mesh rotation={[0, Math.PI / 2, 0]}>
            <torusGeometry args={[12.5, 1.6, 10, 40]} />
            <meshStandardMaterial {...MAT.anod} />
            <E {...s} />
          </mesh>
          <Post oh={oh} under={14} />
        </group>
      );
    }
    case "fiber_coupler":
      return (
        <group>
          <XCyl r={8} len={14} x={7} mat={MAT.anod} {...s} />
          <XCyl r={3} len={6} x={17} mat={MAT.steel} />
          <XCyl r={1.4} len={22} x={31} seg={12} mat={{ color: P.fiber, roughness: 0.6 }} />
          <Post oh={oh} under={8} />
        </group>
      );
    case "photodiode":
      return (
        <group>
          <Box size={[9, 22, 22]} pos={[4.5, 0, 0]} mat={MAT.anod} {...s} />
          <XCyl r={3.5} len={0.6} x={-0.1} mat={MAT.black} />
          <Post oh={oh} under={11} />
        </group>
      );
    case "beam_dump":
      return (
        <group>
          <Box size={[10, 18, 18]} pos={[5, 0, 0]} mat={MAT.black} {...s} />
          <Post oh={oh} under={9} />
        </group>
      );
    case "vapor_cell":
      return (
        <group>
          <XCyl r={12.5} len={75} mat={MAT.glass} {...s} />
          <XCyl r={12.9} len={1.2} x={-37} mat={MAT.glass} />
          <XCyl r={12.9} len={1.2} x={37} mat={MAT.glass} />
          <mesh position={[0, 15, 0]}>
            <cylinderGeometry args={[3, 3, 6, 16]} />
            <meshStandardMaterial {...MAT.glass} />
          </mesh>
          <Box size={[8, 4, 18]} pos={[-28, -14.5, 0]} mat={MAT.anod} />
          <Box size={[8, 4, 18]} pos={[28, -14.5, 0]} mat={MAT.anod} />
        </group>
      );
    case "isolator":
      return (
        <group>
          <XCyl r={11} len={50} mat={MAT.anod} {...s} />
          <XCyl r={11.3} len={4} x={-23} mat={MAT.steel} />
          <XCyl r={11.3} len={4} x={23} mat={MAT.steel} />
          <Post oh={oh} under={11} />
        </group>
      );
    case "soa":
      return (
        <group>
          <Box size={[22, 10, 14]} mat={MAT.housing} {...s} />
          <Box size={[8, 2, 3]} pos={[0, 5.4, 0]} mat={MAT.black} edges={false} />
          <XCyl r={2.2} len={6} x={-14} mat={MAT.steel} />
          <XCyl r={2.2} len={6} x={14} mat={MAT.steel} />
          <Box size={[40, 3, 22]} pos={[0, -6.5, 0]} mat={MAT.anod} />
          <Post oh={oh} under={8} />
        </group>
      );
    case "sfg_crystal":
      return (
        <group>
          <Box size={[10, 6, 6]} mat={{ ...MAT.glass, color: P.sfgTint, opacity: Math.min(0.75, (MAT.glass as { opacity?: number }).opacity ?? 0.5) + 0.1 }} {...s} />
          <Box size={[14, 3, 12]} pos={[0, -4.5, 0]} mat={MAT.anod} />
          <Post oh={oh} under={6} />
        </group>
      );
    case "saturable_absorber":
      return (
        <group>
          <XCyl r={9} len={1.4} mat={{ color: P.absorber, roughness: 0.2, transparent: true, opacity: dim ? 0.2 : 0.7 }} {...s} />
          <mesh rotation={[0, Math.PI / 2, 0]}>
            <torusGeometry args={[10.5, 1.5, 10, 40]} />
            <meshStandardMaterial {...MAT.anod} />
            <E {...s} />
          </mesh>
          <Post oh={oh} under={12} />
        </group>
      );
    case "source":
      return (
        <group>
          <Box size={[56, 30, 40]} pos={[-30, 2, 0]} mat={MAT.housing} {...s} />
          <XCyl r={4} len={4} x={-1} mat={MAT.anod} />
          <Box size={[56, Math.max(oh - 13, 0.5), 40]} pos={[-30, -oh + Math.max(oh - 13, 0.5) / 2, 0]} mat={MAT.anod} edges={false} />
        </group>
      );
    default:
      return <Box size={[10, 10, 10]} mat={MAT.housing} {...s} />;
  }
}

/** footprint radius (mm) used for hit areas, outlines and label placement */
export function partRadius(type: ElementType | "source"): number {
  switch (type) {
    case "vapor_cell": return 40;
    case "isolator": return 27;
    case "source": return 34;
    case "fiber_coupler": return 18;
    case "aom": return 18;
    case "soa": return 20;
    default: return 15;
  }
}
/** footprint centre along local +X */
export function partCenterX(type: ElementType | "source"): number {
  switch (type) {
    case "fiber_coupler": return 10;
    case "photodiode": return 4;
    case "beam_dump": return 5;
    case "source": return -30;
    default: return 0;
  }
}
