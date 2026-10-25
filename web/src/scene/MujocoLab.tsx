import { Edges, Html, Line } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { useMemo } from "react";
import { GANTRY_Z_MM, forwardArmFkClient, useLab, type CribSlot, type MmsKinematics } from "../labStore";
import { useStore } from "../store";
import { Part } from "./parts";

// Table (x, y, z_above_beam_plane) -> Three.js world [x, z_above_beam_plane, -y]
const toW = (x: number, y: number, h = 0): [number, number, number] => [x, h, -y];

function CylinderLink({
  from,
  to,
  radius,
  color,
  edgeColor = "#1f242c",
  metalness = 0.55,
  roughness = 0.3,
}: {
  from: [number, number, number];
  to: [number, number, number];
  radius: number;
  color: string;
  edgeColor?: string;
  metalness?: number;
  roughness?: number;
}) {
  const { pos, quat, len } = useMemo(() => {
    const a = new THREE.Vector3(...from);
    const b = new THREE.Vector3(...to);
    const diff = new THREE.Vector3().subVectors(b, a);
    const l = Math.max(diff.length(), 0.5);
    const mid = new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5);
    const q = new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      diff.clone().normalize(),
    );
    return { pos: [mid.x, mid.y, mid.z] as [number, number, number], quat: q, len: l };
  }, [from, to]);

  return (
    <mesh position={pos} quaternion={quat}>
      <cylinderGeometry args={[radius, radius, len, 24]} />
      <meshStandardMaterial color={color} roughness={roughness} metalness={metalness} />
      <Edges threshold={25} color={edgeColor} />
    </mesh>
  );
}

/** Universal Robots UR5e-style rotary joint housing with signature blue anodized cap. */
function UrJointDrum({
  pos,
  radius,
  length,
  axis = "horizontal",
  yawRad = 0,
}: {
  pos: [number, number, number];
  radius: number;
  length: number;
  axis?: "vertical" | "horizontal";
  yawRad?: number;
}) {
  const rot: [number, number, number] =
    axis === "vertical" ? [0, yawRad, 0] : [Math.PI / 2, yawRad, 0];
  return (
    <group position={pos} rotation={rot}>
      <mesh>
        <cylinderGeometry args={[radius, radius, length, 24]} />
        <meshStandardMaterial color="#cbd5e1" metalness={0.65} roughness={0.28} />
        <Edges threshold={25} color="#334155" />
      </mesh>
      <mesh position={[0, -length * 0.28, 0]}>
        <cylinderGeometry args={[radius * 1.03, radius * 1.03, length * 0.22, 24]} />
        <meshStandardMaterial color="#1e293b" metalness={0.4} roughness={0.5} />
      </mesh>
      <mesh position={[0, length * 0.5 + 1.5, 0]}>
        <cylinderGeometry args={[radius * 0.94, radius * 0.98, 3.0, 24]} />
        <meshStandardMaterial color="#2589bd" metalness={0.5} roughness={0.3} />
        <Edges threshold={25} color="#0c4a6e" />
      </mesh>
    </group>
  );
}

/** Motorized 2-Axis X/Y Part-Presentation Stage + Inventory Crib (decluttered, no floating text spam). */
function MotorizedXYCribStage({
  slots,
  stageSimMm,
  activeSlotIndex,
  pickXY,
  cols,
  pitch,
  oh,
}: {
  slots: CribSlot[];
  stageSimMm: [number, number];
  activeSlotIndex: number | null;
  pickXY: [number, number];
  cols: number;
  pitch: number;
  oh: number;
}) {
  const [pickX, pickY] = pickXY;
  const tableTop = -oh;
  const baseZ = tableTop - 16;

  const rows = Math.max(1, Math.ceil(slots.length / cols));
  const trayW = Math.max(170, cols * pitch + 28);
  const trayH = Math.max(170, rows * pitch + 28);
  const halfW = ((cols - 1) * pitch) / 2;

  const trayX = pickX + stageSimMm[0];
  const trayY = pickY + stageSimMm[1];

  return (
    <group>
      {/* Fixed Gantry Base & X-Axis Linear Rails */}
      <mesh position={toW(pickX - halfW, pickY, baseZ - 6)}>
        <boxGeometry args={[trayW + 24, 10, trayH + 24]} />
        <meshStandardMaterial color="#1f242d" roughness={0.6} metalness={0.3} />
        <Edges threshold={20} color="#3b4454" />
      </mesh>
      {[-trayH * 0.38, trayH * 0.38].map((dy) => (
        <mesh key={dy} position={toW(pickX - halfW, pickY + dy, baseZ)} rotation={[0, 0, Math.PI / 2]}>
          <cylinderGeometry args={[3.5, 3.5, trayW + 16, 16]} />
          <meshStandardMaterial color="#9aa4b2" roughness={0.25} metalness={0.75} />
        </mesh>
      ))}
      <mesh position={toW(pickX - halfW - trayW * 0.5 - 18, pickY, baseZ)}>
        <boxGeometry args={[28, 28, 28]} />
        <meshStandardMaterial color="#2b313c" roughness={0.5} metalness={0.4} />
        <Edges threshold={20} color="#f59e0b" />
      </mesh>

      {/* Moving X-Carriage + Y-Axis Rails */}
      <group position={toW(trayX - halfW, pickY, baseZ + 6)}>
        <mesh>
          <boxGeometry args={[trayW, 6, trayH + 10]} />
          <meshStandardMaterial color="#28303d" roughness={0.5} metalness={0.35} />
          <Edges threshold={20} color="#495468" />
        </mesh>
        <mesh position={[0, 2, trayH * 0.5 + 16]}>
          <boxGeometry args={[26, 26, 26]} />
          <meshStandardMaterial color="#2b313c" roughness={0.5} metalness={0.4} />
          <Edges threshold={20} color="#f59e0b" />
        </mesh>
      </group>

      {/* Moving X/Y Inventory Crib Tray */}
      <group position={toW(trayX, trayY, tableTop - 3)}>
        <mesh position={[-halfW, -3, 0]}>
          <boxGeometry args={[trayW, 6, trayH]} />
          <meshStandardMaterial color="#252c37" roughness={0.45} metalness={0.35} />
          <Edges threshold={20} color="#60a5fa" />
        </mesh>

        {slots.map((sl) => {
          const isActive = sl.slot_index === activeSlotIndex;
          const inCrib = sl.state === "in_crib";
          return (
            <group
              key={sl.element_id}
              position={[sl.pocket_local_xy_mm[0], 0, -sl.pocket_local_xy_mm[1]]}
              onClick={(e) => {
                e.stopPropagation();
                useLab.getState().indexCribSlot(sl.slot_index);
              }}
            >
              <mesh position={[0, 0.5, 0]} rotation={[-Math.PI / 2, 0, 0]}>
                <ringGeometry args={[11, 14.5, 24]} />
                <meshBasicMaterial color={isActive ? "#fbbf24" : inCrib ? "#38bdf8" : "#334155"} side={THREE.DoubleSide} />
              </mesh>
              {inCrib && (
                <group position={[0, oh, 0]} scale={cols > 6 ? 0.72 : 0.92}>
                  <Part type={sl.type} oh={oh} hi={isActive} />
                </group>
              )}
            </group>
          );
        })}
      </group>

      {/* Fixed Calibrated Pick Station Reticle */}
      <group position={toW(pickX, pickY, tableTop + 0.8)}>
        <mesh rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[16, 19.5, 32]} />
          <meshBasicMaterial color="#10b981" side={THREE.DoubleSide} />
        </mesh>
      </group>
    </group>
  );
}

/** Overhead Gantry Bridge + Inverted 6-DOF UR5e Cobot Arm + Integrated 0x23/MicroManipulatorStepper Toolhead. */
function OverheadGantryAndInvertedCobot({
  plateW,
  plateH,
  railSimXMm,
  carriageSimYMm,
  armSimRad,
  gripperM,
  carriedSlot,
  mmsKin,
  selectedMmsElementId,
  oh,
}: {
  plateW: number;
  plateH: number;
  railSimXMm: number;
  carriageSimYMm: number;
  armSimRad: [number, number, number, number, number, number];
  gripperM: number;
  carriedSlot: CribSlot | null;
  mmsKin: MmsKinematics;
  selectedMmsElementId: string;
  oh: number;
}) {
  const tableTop = -oh;
  const gantryW = GANTRY_Z_MM + tableTop;
  const xMin = -210;
  const xMax = plateW + 40;
  const spanX = xMax - xMin;
  const midX = (xMin + xMax) * 0.5;
  const yFront = -45;
  const yBack = plateH + 45;
  const spanY = yBack - yFront;
  const midY = (yFront + yBack) * 0.5;

  const fk = useMemo(
    () => forwardArmFkClient(armSimRad, [railSimXMm, carriageSimYMm]),
    [armSimRad, railSimXMm, carriageSimYMm],
  );

  const baseW = toW(fk.base_mm[0], fk.base_mm[1], tableTop + fk.base_mm[2]);
  const shoulderW = toW(fk.shoulder_mm[0], fk.shoulder_mm[1], tableTop + fk.shoulder_mm[2]);
  const elbowW = toW(fk.elbow_mm[0], fk.elbow_mm[1], tableTop + fk.elbow_mm[2]);
  const wristW = toW(fk.wrist_mm[0], fk.wrist_mm[1], tableTop + fk.wrist_mm[2]);
  const tipW = toW(fk.tip_mm[0], fk.tip_mm[1], tableTop + fk.tip_mm[2]);

  const fingerOffsetMm = Math.max(3.5, gripperM * 1000);
  const toolYawRad = (fk.tool_yaw_deg * Math.PI) / 180;
  const scaleMms = 0.28;

  return (
    <group>
      {/* 1. Overhead Gantry Support Frame (4 Corner Columns + Longitudinal X-Rails) */}
      {[
        [xMin, yFront],
        [xMax, yFront],
        [xMin, yBack],
        [xMax, yBack],
      ].map(([cx, cy], idx) => (
        <CylinderLink
          key={idx}
          from={toW(cx, cy, tableTop - 25)}
          to={toW(cx, cy, gantryW + 14)}
          radius={8}
          color="#334155"
          edgeColor="#475569"
        />
      ))}

      {[yFront, yBack].map((ry) => (
        <group key={ry} position={toW(midX, ry, gantryW + 10)}>
          <mesh>
            <boxGeometry args={[spanX + 24, 18, 22]} />
            <meshStandardMaterial color="#1e293b" metalness={0.5} roughness={0.4} />
            <Edges threshold={20} color="#475569" />
          </mesh>
          <mesh position={[0, 11, 0]}>
            <boxGeometry args={[spanX, 4, 8]} />
            <meshStandardMaterial color="#cbd5e1" metalness={0.85} roughness={0.18} />
          </mesh>
        </group>
      ))}

      {/* 2. Moving Overhead Gantry Bridge (slides along build plate length X = railSimXMm) */}
      <group position={toW(railSimXMm, midY, gantryW + 12)}>
        <mesh>
          <boxGeometry args={[34, 16, spanY + 20]} />
          <meshStandardMaterial color="#ea580c" metalness={0.35} roughness={0.4} />
          <Edges threshold={20} color="#fdba74" />
        </mesh>
        <mesh position={[0, -2, spanY * 0.5]}>
          <boxGeometry args={[52, 22, 32]} />
          <meshStandardMaterial color="#0f172a" metalness={0.5} roughness={0.4} />
          <Edges threshold={20} color="#38bdf8" />
        </mesh>
        <mesh position={[0, -2, -spanY * 0.5]}>
          <boxGeometry args={[52, 22, 32]} />
          <meshStandardMaterial color="#0f172a" metalness={0.5} roughness={0.4} />
          <Edges threshold={20} color="#38bdf8" />
        </mesh>
      </group>

      {/* 3. Overhead Trolley + Inverted UR3e 6-DOF Robot Arm */}
      <group position={baseW}>
        <mesh position={[0, 4, 0]}>
          <boxGeometry args={[36, 10, 36]} />
          <meshStandardMaterial color="#1e293b" metalness={0.55} roughness={0.35} />
          <Edges threshold={20} color="#38bdf8" />
        </mesh>
      </group>

      {/* Inverted Base Turret (Gantry Trolley -> J1/J2 Shoulder) */}
      <CylinderLink from={baseW} to={shoulderW} radius={13} color="#475569" edgeColor="#1e293b" />
      <UrJointDrum pos={shoulderW} radius={13} length={26} axis="vertical" yawRad={fk.yaw_rad} />
      <UrJointDrum pos={shoulderW} radius={13} length={26} axis="horizontal" yawRad={fk.yaw_rad} />

      {/* UR3e Upper Arm Tube (Shoulder J2 -> Elbow J3) */}
      <CylinderLink from={shoulderW} to={elbowW} radius={9.5} color="#e2e8f0" edgeColor="#64748b" metalness={0.7} roughness={0.22} />
      <UrJointDrum pos={elbowW} radius={10.5} length={22} axis="horizontal" yawRad={fk.yaw_rad} />

      {/* UR3e Forearm Tube (Elbow J3 -> Wrist J4/J5) */}
      <CylinderLink from={elbowW} to={wristW} radius={8} color="#e2e8f0" edgeColor="#64748b" metalness={0.7} roughness={0.22} />
      <UrJointDrum pos={wristW} radius={8.5} length={18} axis="horizontal" yawRad={fk.yaw_rad} />

      {/* UR3e Wrist 2/3 & Tool Flange (Wrist -> TCP) */}
      <CylinderLink from={wristW} to={tipW} radius={6.5} color="#334155" edgeColor="#2589bd" />
      <UrJointDrum pos={[tipW[0], tipW[1] + 12, tipW[2]]} radius={8.5} length={16} axis="vertical" yawRad={toolYawRad} />
      {/* 4. End-Effector: Parallel Servo Gripper + Integrated 0x23/MicroManipulatorStepper Delta-3D Toolhead */}
      <group position={tipW} rotation={[0, toolYawRad, 0]}>
        <mesh position={[0, 10, 0]}>
          <boxGeometry args={[18, 8, 30]} />
          <meshStandardMaterial color="#0f172a" roughness={0.35} metalness={0.55} />
          <Edges threshold={20} color="#38bdf8" />
        </mesh>
        <mesh position={[0, -4, fingerOffsetMm]}>
          <boxGeometry args={[7, 18, 3.5]} />
          <meshStandardMaterial color="#10b981" roughness={0.3} metalness={0.4} />
        </mesh>
        <mesh position={[0, -4, -fingerOffsetMm]}>
          <boxGeometry args={[7, 18, 3.5]} />
          <meshStandardMaterial color="#10b981" roughness={0.3} metalness={0.4} />
        </mesh>

        {/* Integrated 0x23/MicroManipulatorStepper Delta-3D Fine-Alignment Stage on Toolhead */}
        <group position={[18, 12, 0]}>
          <mesh>
            <boxGeometry args={[14, 14, 14]} />
            <meshStandardMaterial color="#1e293b" metalness={0.5} roughness={0.4} />
            <Edges threshold={20} color="#f59e0b" />
          </mesh>
          {mmsKin.actuators.map((act) => {
            const hc: [number, number, number] = [
              act.horn_center_mm[0] * scaleMms,
              act.horn_center_mm[2] * scaleMms,
              -act.horn_center_mm[1] * scaleMms,
            ];
            const ht: [number, number, number] = [
              act.horn_tip_mm[0] * scaleMms,
              act.horn_tip_mm[2] * scaleMms,
              -act.horn_tip_mm[1] * scaleMms,
            ];
            const ej: [number, number, number] = [
              act.ee_joint_mm[0] * scaleMms,
              act.ee_joint_mm[2] * scaleMms,
              -act.ee_joint_mm[1] * scaleMms,
            ];
            return (
              <group key={act.axis}>
                <CylinderLink from={hc} to={ht} radius={1.2} color="#f59e0b" edgeColor="#78350f" />
                <CylinderLink from={ht} to={ej} radius={0.8} color="#38bdf8" edgeColor="#0284c7" />
              </group>
            );
          })}
        </group>

        {carriedSlot && (
          <group position={[0, 0, 0]}>
            <Part type={carriedSlot.type} oh={oh} sel hi />
          </group>
        )}
      </group>

      {/* Single compact badge on the active TCP target only */}
      <Line points={[[tipW[0] + 18, tipW[1] + 12, tipW[2]], tipW]} color="#38bdf8" lineWidth={2} />
      {(carriedSlot || selectedMmsElementId) && (
        <Html position={[tipW[0], tipW[1] + 34, tipW[2]]} center style={{ pointerEvents: "none" }}>
          <div
            style={{
              font: "600 9.5px 'IBM Plex Mono', monospace",
              padding: "1px 5px",
              borderRadius: 3,
              background: "rgba(15, 23, 42, 0.88)",
              color: carriedSlot ? "#fbbf24" : "#38bdf8",
              border: `1px solid ${carriedSlot ? "#f59e0b" : "#0284c7"}`,
              whiteSpace: "nowrap",
            }}
          >
            {carriedSlot ? `PICK: ${carriedSlot.element_id}` : `MMS: ${selectedMmsElementId}`}
          </div>
        </Html>
      )}
    </group>
  );
}

export default function MujocoLabWorkcell({ oh }: { oh: number }) {
  const enabled = useLab((s) => s.enabled);
  const manifest = useLab((s) => s.manifest);
  const slots = useLab((s) => s.slots);
  const activeSlotIndex = useLab((s) => s.activeSlotIndex);
  const carriedElementId = useLab((s) => s.carriedElementId);
  const stageSimMm = useLab((s) => s.stageSimMm);
  const railSimXMm = useLab((s) => s.railSimXMm);
  const carriageSimYMm = useLab((s) => s.carriageSimYMm);
  const armSimRad = useLab((s) => s.armSimRad);
  const gripperM = useLab((s) => s.gripperM);
  const mmsKinematics = useLab((s) => s.mmsKinematics);
  const selectedMmsElementId = useLab((s) => s.selectedMmsElementId);
  const design = useStore((s) => s.design);

  useFrame((_, dt) => {
    if (enabled) {
      useLab.getState().stepMujoco(Math.min(dt, 0.05));
    }
  });

  if (!enabled || !design) return null;

  const plateW = design.baseplate?.width_mm ?? 300;
  const plateH = design.baseplate?.height_mm ?? 150;
  const pickXY: [number, number] = manifest?.pick_station_xy_mm ?? [-180, Math.round(plateH * 0.5)];
  const cols = manifest?.crib_cols ?? (slots.length > 24 ? 11 : 4);
  const pitch = manifest?.crib_pitch_mm?.[0] ?? (slots.length > 24 ? 34 : 42);
  const carriedSlot = carriedElementId ? (slots.find((s) => s.element_id === carriedElementId) ?? null) : null;

  return (
    <group>
      <MotorizedXYCribStage
        slots={slots}
        stageSimMm={stageSimMm}
        activeSlotIndex={activeSlotIndex}
        pickXY={pickXY}
        cols={cols}
        pitch={pitch}
        oh={oh}
      />
      <OverheadGantryAndInvertedCobot
        plateW={plateW}
        plateH={plateH}
        railSimXMm={railSimXMm}
        carriageSimYMm={carriageSimYMm}
        armSimRad={armSimRad}
        gripperM={gripperM}
        carriedSlot={carriedSlot}
        mmsKin={mmsKinematics}
        selectedMmsElementId={selectedMmsElementId}
        oh={oh}
      />
    </group>
  );
}
