import { Edges, Html, Line } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { useMemo } from "react";
import { forwardArmFkClient, useLab, type CribSlot, type MmsKinematics } from "../labStore";
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
}: {
  from: [number, number, number];
  to: [number, number, number];
  radius: number;
  color: string;
  edgeColor?: string;
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
      <cylinderGeometry args={[radius, radius, len, 20]} />
      <meshStandardMaterial color={color} roughness={0.35} metalness={0.45} />
      <Edges threshold={25} color={edgeColor} />
    </mesh>
  );
}

/** Motorized 2-Axis X/Y Part-Presentation Stage + Inventory Crib. */
function MotorizedXYCribStage({
  slots,
  stageSimMm,
  activeSlotIndex,
  oh,
}: {
  slots: CribSlot[];
  stageSimMm: [number, number];
  activeSlotIndex: number | null;
  oh: number;
}) {
  const pickX = -110;
  const pickY = 95;
  const tableTop = -oh;
  const baseZ = tableTop - 16;

  // Tray origin in table coordinates when stage is at (stageSimMm[0], stageSimMm[1])
  const trayX = pickX + stageSimMm[0];
  const trayY = pickY + stageSimMm[1];

  return (
    <group>
      {/* Fixed Gantry Base & X-Axis Linear Rails */}
      <mesh position={toW(pickX + 30, pickY + 30, baseZ - 6)}>
        <boxGeometry args={[210, 10, 210]} />
        <meshStandardMaterial color="#1f242d" roughness={0.6} metalness={0.3} />
        <Edges threshold={20} color="#3b4454" />
      </mesh>
      {/* X-Axis Linear Guide Rails */}
      {[-65, 65].map((dy) => (
        <mesh key={dy} position={toW(pickX + 30, pickY + 30 + dy, baseZ)} rotation={[0, 0, Math.PI / 2]}>
          <cylinderGeometry args={[3.2, 3.2, 195, 16]} />
          <meshStandardMaterial color="#9aa4b2" roughness={0.25} metalness={0.75} />
        </mesh>
      ))}
      {/* X-Axis NEMA17 Stepper Motor */}
      <mesh position={toW(pickX - 85, pickY + 30, baseZ)}>
        <boxGeometry args={[28, 28, 28]} />
        <meshStandardMaterial color="#2b313c" roughness={0.5} metalness={0.4} />
        <Edges threshold={20} color="#f59e0b" />
      </mesh>

      {/* Moving X-Carriage + Y-Axis Rails */}
      <group position={toW(trayX, pickY + 30, baseZ + 6)}>
        <mesh>
          <boxGeometry args={[165, 6, 175]} />
          <meshStandardMaterial color="#28303d" roughness={0.5} metalness={0.35} />
          <Edges threshold={20} color="#495468" />
        </mesh>
        {/* Y-Axis NEMA17 Stepper Motor */}
        <mesh position={[0, 2, 98]}>
          <boxGeometry args={[26, 26, 26]} />
          <meshStandardMaterial color="#2b313c" roughness={0.5} metalness={0.4} />
          <Edges threshold={20} color="#f59e0b" />
        </mesh>
      </group>

      {/* Moving X/Y Inventory Crib Tray */}
      <group position={toW(trayX + 63, trayY + 63, tableTop - 3)}>
        <mesh position={[0, -3, 0]}>
          <boxGeometry args={[180, 6, 180]} />
          <meshStandardMaterial color="#252c37" roughness={0.45} metalness={0.35} />
          <Edges threshold={20} color="#60a5fa" />
        </mesh>

        {/* Component Pockets inside the Inventory Crib */}
        {slots.map((sl) => {
          const lx = sl.pocket_local_xy_mm[0] - 63;
          const ly = sl.pocket_local_xy_mm[1] - 63;
          const isActive = sl.slot_index === activeSlotIndex;
          const inCrib = sl.state === "in_crib";
          return (
            <group
              key={sl.element_id}
              position={[lx, 0, -ly]}
              onClick={(e) => {
                e.stopPropagation();
                useLab.getState().indexCribSlot(sl.slot_index);
              }}
            >
              {/* Machined pocket ring */}
              <mesh position={[0, 0.5, 0]} rotation={[-Math.PI / 2, 0, 0]}>
                <ringGeometry args={[13, 17, 28]} />
                <meshBasicMaterial color={isActive ? "#fbbf24" : inCrib ? "#38bdf8" : "#475569"} side={THREE.DoubleSide} />
              </mesh>
              {/* Dowel alignment pins in pocket */}
              <mesh position={[0, 2, -8]}>
                <cylinderGeometry args={[1.0, 1.0, 4, 12]} />
                <meshStandardMaterial color="#cbd5e1" metalness={0.8} roughness={0.2} />
              </mesh>
              <mesh position={[0, 2, 8]}>
                <cylinderGeometry args={[1.0, 1.0, 4, 12]} />
                <meshStandardMaterial color="#cbd5e1" metalness={0.8} roughness={0.2} />
              </mesh>
              {/* Render actual 3D optical part while it sits in the crib */}
              {inCrib && (
                <group position={[0, oh, 0]}>
                  <Part type={sl.type} oh={oh} hi={isActive} />
                </group>
              )}
              {isActive && (
                <Html position={[0, 18, 0]} center style={{ pointerEvents: "none" }}>
                  <div
                    style={{
                      font: "600 9.5px 'IBM Plex Mono', monospace",
                      padding: "1px 5px",
                      borderRadius: 3,
                      background: "#f59e0b",
                      color: "#0f172a",
                      border: "1px solid #fbbf24",
                      whiteSpace: "nowrap",
                    }}
                  >
                    #{sl.slot_index} {sl.element_id} ({sl.type})
                  </div>
                </Html>
              )}
            </group>
          );
        })}
      </group>

      {/* Fixed Calibrated Pick Station Reticle above (-110, 95) */}
      <group position={toW(pickX, pickY, tableTop + 0.6)}>
        <mesh rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[18, 20.5, 36]} />
          <meshBasicMaterial color="#10b981" side={THREE.DoubleSide} />
        </mesh>
        <Html position={[0, 36, 0]} center style={{ pointerEvents: "none" }}>
          <div
            style={{
              font: "600 10px 'IBM Plex Mono', monospace",
              padding: "2px 6px",
              borderRadius: 4,
              background: "rgba(6, 78, 59, 0.9)",
              color: "#6ee7b7",
              border: "1px solid #10b981",
              whiteSpace: "nowrap",
            }}
          >
            PICK STATION ({pickX}, {pickY}) · X/Y Stage ({stageSimMm[0].toFixed(0)}, {stageSimMm[1].toFixed(0)}) mm
          </div>
        </Html>
      </group>
    </group>
  );
}

/** Articulated 6-DOF Robot Arm + Parallel Gripper driven by MuJoCo qpos. */
function SixDofRobotArm({
  armSimRad,
  gripperM,
  carriedSlot,
  oh,
}: {
  armSimRad: [number, number, number, number, number, number];
  gripperM: number;
  carriedSlot: CribSlot | null;
  oh: number;
}) {
  const fk = useMemo(() => forwardArmFkClient(armSimRad), [armSimRad]);
  const tableTop = -oh;

  const baseW = toW(fk.base_mm[0], fk.base_mm[1], tableTop + fk.base_mm[2]);
  const shoulderW = toW(fk.shoulder_mm[0], fk.shoulder_mm[1], tableTop + fk.shoulder_mm[2]);
  const elbowW = toW(fk.elbow_mm[0], fk.elbow_mm[1], tableTop + fk.elbow_mm[2]);
  const wristW = toW(fk.wrist_mm[0], fk.wrist_mm[1], tableTop + fk.wrist_mm[2]);
  const tipW = toW(fk.tip_mm[0], fk.tip_mm[1], tableTop + fk.tip_mm[2]);

  const fingerOffsetMm = Math.max(3, gripperM * 1000);
  const yawRad = (fk.tool_yaw_deg * Math.PI) / 180;

  return (
    <group>
      {/* Pedestal & J1 Turret */}
      <CylinderLink from={[baseW[0], baseW[1] - 12, baseW[2]]} to={shoulderW} radius={18} color="#334155" edgeColor="#64748b" />
      <mesh position={shoulderW}>
        <sphereGeometry args={[20, 20, 20]} />
        <meshStandardMaterial color="#f97316" roughness={0.35} metalness={0.4} />
        <Edges threshold={25} color="#1e293b" />
      </mesh>

      {/* Upper Arm Link (J2 -> J3) */}
      <CylinderLink from={shoulderW} to={elbowW} radius={13} color="#e2e8f0" edgeColor="#475569" />
      <mesh position={elbowW}>
        <sphereGeometry args={[16, 18, 18]} />
        <meshStandardMaterial color="#f97316" roughness={0.35} metalness={0.4} />
        <Edges threshold={25} color="#1e293b" />
      </mesh>

      {/* Forearm Link (J3 -> J4/J5) */}
      <CylinderLink from={elbowW} to={wristW} radius={10.5} color="#cbd5e1" edgeColor="#475569" />
      <mesh position={wristW}>
        <sphereGeometry args={[13, 16, 16]} />
        <meshStandardMaterial color="#38bdf8" roughness={0.3} metalness={0.5} />
      </mesh>

      {/* Wrist & Tool Flange (J5/J6 -> TCP) */}
      <CylinderLink from={wristW} to={tipW} radius={8} color="#1e293b" edgeColor="#38bdf8" />

      {/* Parallel Servo Gripper + Carried Optical Component */}
      <group position={tipW} rotation={[0, yawRad, 0]}>
        <mesh position={[0, 8, 0]}>
          <boxGeometry args={[16, 6, 28]} />
          <meshStandardMaterial color="#0f172a" roughness={0.4} metalness={0.5} />
          <Edges threshold={20} color="#38bdf8" />
        </mesh>
        {/* Left & Right Gripper Fingers */}
        <mesh position={[0, -4, fingerOffsetMm]}>
          <boxGeometry args={[7, 18, 3.5]} />
          <meshStandardMaterial color="#10b981" roughness={0.3} metalness={0.4} />
        </mesh>
        <mesh position={[0, -4, -fingerOffsetMm]}>
          <boxGeometry args={[7, 18, 3.5]} />
          <meshStandardMaterial color="#10b981" roughness={0.3} metalness={0.4} />
        </mesh>

        {/* Render the picked optical component inside the gripper while carried */}
        {carriedSlot && (
          <group position={[0, 0, 0]}>
            <Part type={carriedSlot.type} oh={oh} sel hi />
          </group>
        )}
      </group>
    </group>
  );
}

/** 0x23/MicroManipulatorStepper (HW v4.0) 3-DOF Parallel Delta-3D Stage. */
function MicroManipulatorDelta3D({
  kin,
  anchorXY,
  elementId,
  oh,
}: {
  kin: MmsKinematics;
  anchorXY: [number, number];
  elementId: string;
  oh: number;
}) {
  const tableTop = -oh;
  // Place the Delta-3D manipulator housing adjacent to the target optic (or bench edge)
  const originW = toW(anchorXY[0] + 45, anchorXY[1] - 42, tableTop + 32);
  const scale = 0.55; // Compact benchtop visualization scale

  const toLocalW = (p: [number, number, number]): [number, number, number] => [
    originW[0] + p[0] * scale,
    originW[1] + p[2] * scale,
    originW[2] - p[1] * scale,
  ];

  const eeCenterW = toLocalW(kin.ee_mm);
  const targetOpticW = toW(anchorXY[0], anchorXY[1], 0);

  return (
    <group>
      {/* Base Block Housing */}
      <mesh position={[originW[0] - 18 * scale, originW[1] - 14 * scale, originW[2] + 18 * scale]}>
        <boxGeometry args={[46 * scale, 42 * scale, 46 * scale]} />
        <meshStandardMaterial color="#1e293b" roughness={0.5} metalness={0.4} />
        <Edges threshold={20} color="#f59e0b" />
      </mesh>

      {/* 3 Orthogonal NEMA17 Actuators + Rotating Horns + Parallel Ball-Joint Linkage Rods */}
      {kin.actuators.map((act) => {
        const hCenter = toLocalW(act.horn_center_mm);
        const hTip = toLocalW(act.horn_tip_mm);
        const eeJoint = toLocalW(act.ee_joint_mm);
        return (
          <group key={act.axis}>
            {/* Actuator Motor Mount & MT6835 Magnetic Encoder Cap */}
            <mesh position={hCenter}>
              <cylinderGeometry args={[8 * scale, 8 * scale, 10 * scale, 18]} />
              <meshStandardMaterial color="#334155" roughness={0.4} metalness={0.5} />
              <Edges threshold={20} color="#94a3b8" />
            </mesh>
            {/* Rotating Motor Horn (r = 15 mm) */}
            <CylinderLink from={hCenter} to={hTip} radius={2.4 * scale} color="#f59e0b" edgeColor="#78350f" />
            {/* Parallel Linkage Rod Pair (L = 72.5 mm) */}
            <CylinderLink from={hTip} to={eeJoint} radius={1.6 * scale} color="#38bdf8" edgeColor="#0284c7" />
            {/* Miniature Ball Joints */}
            <mesh position={hTip}>
              <sphereGeometry args={[2.6 * scale, 12, 12]} />
              <meshStandardMaterial color="#f8fafc" metalness={0.85} roughness={0.15} />
            </mesh>
            <mesh position={eeJoint}>
              <sphereGeometry args={[2.6 * scale, 12, 12]} />
              <meshStandardMaterial color="#f8fafc" metalness={0.85} roughness={0.15} />
            </mesh>
          </group>
        );
      })}

      {/* Delta-3D End-Effector Plate + Flexure Coupling Probe to Optic */}
      <mesh position={eeCenterW}>
        <cylinderGeometry args={[13 * scale, 13 * scale, 5 * scale, 24]} />
        <meshStandardMaterial color="#0ea5e9" roughness={0.3} metalness={0.5} />
        <Edges threshold={20} color="#e0f2fe" />
      </mesh>
      <Line points={[eeCenterW, targetOpticW]} color="#38bdf8" lineWidth={2} dashed dashSize={3} gapSize={2} />

      <Html position={[eeCenterW[0], eeCenterW[1] + 22, eeCenterW[2]]} center style={{ pointerEvents: "none" }}>
        <div
          style={{
            font: "600 9.5px 'IBM Plex Mono', monospace",
            padding: "2px 6px",
            borderRadius: 4,
            background: "rgba(15, 23, 42, 0.92)",
            color: "#38bdf8",
            border: "1px solid #0284c7",
            whiteSpace: "nowrap",
          }}
        >
          0x23/MMS [{elementId || "bench"}] ({kin.ee_um[0].toFixed(1)}, {kin.ee_um[1].toFixed(1)}, {kin.ee_um[2].toFixed(1)}) µm
        </div>
      </Html>
    </group>
  );
}

export default function MujocoLabWorkcell({ oh }: { oh: number }) {
  const enabled = useLab((s) => s.enabled);
  const slots = useLab((s) => s.slots);
  const activeSlotIndex = useLab((s) => s.activeSlotIndex);
  const carriedElementId = useLab((s) => s.carriedElementId);
  const stageSimMm = useLab((s) => s.stageSimMm);
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

  const carriedSlot = carriedElementId ? (slots.find((s) => s.element_id === carriedElementId) ?? null) : null;
  const mmsSlot = slots.find((s) => s.element_id === selectedMmsElementId) ?? slots[slots.length - 1];
  const mmsAnchorXY: [number, number] = mmsSlot ? mmsSlot.bench_xy_mm : [(design.baseplate?.width_mm ?? 300) - 40, (design.baseplate?.height_mm ?? 150) / 2];

  return (
    <group>
      <MotorizedXYCribStage slots={slots} stageSimMm={stageSimMm} activeSlotIndex={activeSlotIndex} oh={oh} />
      <SixDofRobotArm armSimRad={armSimRad} gripperM={gripperM} carriedSlot={carriedSlot} oh={oh} />
      <MicroManipulatorDelta3D kin={mmsKinematics} anchorXY={mmsAnchorXY} elementId={selectedMmsElementId} oh={oh} />
    </group>
  );
}
