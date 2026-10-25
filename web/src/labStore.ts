import { create } from "zustand";
import loadMujoco, { type MainModule, type MjData, type MjModel } from "mujoco-js";
import type { Design, Element, PlacedElement, TraceResult, VerifyReport } from "./types";
import { useStore } from "./store";
import { useConsole } from "./consoleStore";
import { useView } from "./scene/viewStore";

export interface CribSlot {
  slot_index: number;
  element_id: string;
  type: Element["type"];
  label: string;
  part_number: string;
  pocket_local_xy_mm: [number, number];
  stage_present_xy_mm: [number, number];
  pick_station_xy_mm: [number, number];
  pick_rail_x_mm: number;
  place_rail_x_mm: number;
  pick_carriage_y_mm: number;
  place_carriage_y_mm: number;
  bench_xy_mm: [number, number];
  bench_z_mm: number;
  bench_angle_deg: number;
  has_mms: boolean;
  mms_unit_id: string | null;
  ik_keyframes: Record<string, number[]>;
  state?: "in_crib" | "carried" | "placed";
}

export interface MmsActuatorGeom {
  axis: "A" | "B" | "C";
  rotor_deg: number;
  rotor_rad: number;
  horn_center_mm: [number, number, number];
  horn_tip_mm: [number, number, number];
  ee_joint_mm: [number, number, number];
}

export interface MmsKinematics {
  valid: boolean;
  ee_mm: [number, number, number];
  ee_um: [number, number, number];
  rotor_deg: [number, number, number];
  rotor_rad: [number, number, number];
  actuators: MmsActuatorGeom[];
}

export interface GcodeLogEntry {
  id: number;
  unit_id: string;
  element_id: string;
  command: string;
  status: string;
  response: string;
  pos_um: [number, number, number];
  rotor_deg: [number, number, number];
  encoder_counts: [number, number, number];
}

export interface LabStreamEvent {
  id: number;
  tag: string;
  color: string;
  text: string;
}

export interface LabManifest {
  design_name: string;
  pick_station_xy_mm: [number, number];
  arm_base_xy_mm: [number, number];
  gantry_z_mm: number;
  rail_y_mm: number;
  rail_range_mm: [number, number];
  arm_links_mm: { base_z: number; upper: number; forearm: number; wrist: number };
  crib_cols: number;
  crib_pitch_mm: [number, number];
  mms_spec: {
    repo: string;
    hardware_version: string;
    firmware_version: string;
    step_resolution_nm: number;
    loop_rate_khz: number;
    encoder: string;
    arm_length_mm: number;
    rotor_radius_mm: number;
    neutral_kinematics: MmsKinematics;
  };
  slots: CribSlot[];
}

interface LabGcodeResultItem {
  unit_id: string;
  element_id: string;
  command: string;
  status: string;
  response: string;
  pos_mm: [number, number, number];
  pos_um: [number, number, number];
  rotor_deg: [number, number, number];
  encoder_counts: [number, number, number];
  kinematics: MmsKinematics;
}

interface LabGcodeResponse {
  unit_id: string;
  element_id: string;
  homed: boolean;
  motors_enabled: boolean;
  pos_mm: [number, number, number];
  pos_um: [number, number, number];
  rotor_deg: [number, number, number];
  encoder_counts: [number, number, number];
  kinematics: MmsKinematics;
  results: LabGcodeResultItem[];
}

interface LabSseEvent {
  type: string;
  mjcf_xml?: string;
  manifest?: LabManifest;
  slot_index?: number;
  element_id?: string;
  phase?: string;
  part_type?: string;
  stage_xy_mm?: [number, number];
  rail_x_mm?: number;
  carriage_y_mm?: number;
  arm_q_rad?: [number, number, number, number, number, number];
  gripper_m?: number;
  part_state?: "in_crib" | "carried" | "placed";
  placed_ids?: string[];
  total_parts?: number;
  design?: Design;
  trace?: TraceResult;
  report?: VerifyReport;
  best_so_far?: boolean;
  patch?: Partial<Element>;
  gcode?: LabGcodeResultItem;
  summary?: { parts_assembled?: number; mms_gcode_moves?: number };
  message?: string;
  text?: string;
  agent_id?: string;
}

interface LabState {
  enabled: boolean;
  running: boolean;
  phase: "idle" | "planning" | "building" | "aligning" | "done";
  statusMessage: string;
  playbackSpeed: number;
  setPlaybackSpeed: (v: number) => void;
  eventLog: LabStreamEvent[];

  wasmReady: boolean;
  wasmVersion: string;
  simTimeS: number;
  stepCount: number;
  dofCount: number;
  actuatorCount: number;
  mjcfXml: string | null;
  manifest: LabManifest | null;

  slots: CribSlot[];
  activeSlotIndex: number | null;
  carriedElementId: string | null;
  adjustingElementId: string | null;

  // Motorized X/Y Crib Presentation Stage
  stageCmdMm: [number, number];
  stageSimMm: [number, number];

  // Overhead Gantry Bridge (X along build plate length, Y trolley across width)
  railRangeMm: [number, number];
  railCmdXMm: number;
  railSimXMm: number;
  carriageCmdYMm: number;
  carriageSimYMm: number;

  // Inverted 6-DOF UR5e Cobot Arm
  armCmdRad: [number, number, number, number, number, number];
  armSimRad: [number, number, number, number, number, number];
  gripperM: number;

  // 0x23/MicroManipulatorStepper (HW v4.0 Delta-3D)
  selectedMmsElementId: string;
  mmsPosMm: [number, number, number];
  mmsPosUm: [number, number, number];
  mmsRotorDeg: [number, number, number];
  mmsEncoderCounts: [number, number, number];
  mmsKinematics: MmsKinematics;
  mmsHomed: boolean;
  mmsMotorsEnabled: boolean;
  gcodeLog: GcodeLogEntry[];

  setEnabled: (v: boolean) => void;
  initWorkcell: (d: Design) => Promise<void>;
  startAutonomousRun: (useLlm?: boolean) => Promise<void>;
  stopRun: () => void;
  indexCribSlot: (slotIndex: number) => void;
  setRailXMm: (xMm: number) => void;
  setCarriageYMm: (yMm: number) => void;
  focusElementWithRobot: (elementId: string) => void;
  sendGcode: (commands: string[], elementId?: string) => Promise<void>;
  jogMmsUm: (axis: "X" | "Y" | "Z", deltaUm: number) => Promise<void>;
  stepMujoco: (dt: number) => void;
}

const DEG2RAD = Math.PI / 180;
const RAD2DEG = 180 / Math.PI;
export const GANTRY_Z_MM = 260;
const L_BASE = 32;
const L_UPPER = 135;
const L_FORE = 125;
const L_WRIST = 38;

const TUNABLE_TYPES: Record<string, true> = {
  half_wave_plate: true,
  quarter_wave_plate: true,
  lens: true,
  mirror: true,
  fiber_coupler: true,
  beamsplitter: true,
  sampler: true,
};

const CONSOLE_EVENT_TYPES: Record<string, true> = {
  agent: true,
  thought: true,
  tokens: true,
  tool: true,
  llm_call: true,
  status: true,
  iteration: true,
  final: true,
};

/** Analytical 6-DOF inverse kinematics for the **inverted** overhead-gantry UR5e cobot arm. */
export function solveArmIkClient(
  targetXyzMm: [number, number, number],
  yawDeg = 0,
  baseXyMm: [number, number] = [-125, 75],
): [number, number, number, number, number, number] {
  const [tx, ty, tz] = targetXyzMm;
  const [bx, by] = baseXyMm;
  const dx = tx - bx;
  const dy = ty - by;
  const j1 = Math.abs(dx) + Math.abs(dy) > 1e-3 ? Math.atan2(dy, dx) : 0;
  const rHoriz = Math.hypot(dx, dy);
  const zShoulder = GANTRY_Z_MM - L_BASE;
  const zWrist = tz + L_WRIST;
  const dzDown = Math.max(20, zShoulder - zWrist);
  const d = Math.hypot(rHoriz, dzDown);
  const dClamped = Math.max(Math.abs(L_UPPER - L_FORE) + 4, Math.min(L_UPPER + L_FORE - 4, d));
  const cosElbow = Math.max(-1, Math.min(1, (L_UPPER * L_UPPER + L_FORE * L_FORE - dClamped * dClamped) / (2 * L_UPPER * L_FORE)));
  const j3 = -(Math.PI - Math.acos(cosElbow));
  const alpha = Math.atan2(rHoriz, dzDown);
  const cosBeta = Math.max(-1, Math.min(1, (L_UPPER * L_UPPER + dClamped * dClamped - L_FORE * L_FORE) / (2 * L_UPPER * dClamped)));
  const beta = Math.acos(cosBeta);
  const j2 = alpha + beta;
  const j4 = -(j2 + j3);
  const j5 = 0;
  let j6 = yawDeg * DEG2RAD - j1;
  j6 = ((j6 + Math.PI) % (2 * Math.PI)) - Math.PI;
  return [j1, j2, j3, j4, j5, j6];
}

/** Compute 3D joint positions (mm) for the inverted overhead-gantry UR5e cobot arm. */
export function forwardArmFkClient(
  q: [number, number, number, number, number, number],
  baseXyMm: [number, number] = [-125, 75],
) {
  const [j1, j2, j3, j4, , j6] = q;
  const [bx, by] = baseXyMm;
  const c1 = Math.cos(j1);
  const s1 = Math.sin(j1);
  const zShoulder = GANTRY_Z_MM - L_BASE;
  const shoulder: [number, number, number] = [bx, by, zShoulder];
  const rElbow = L_UPPER * Math.sin(j2);
  const zElbow = zShoulder - L_UPPER * Math.cos(j2);
  const elbow: [number, number, number] = [bx + rElbow * c1, by + rElbow * s1, zElbow];
  const p23 = j2 + j3;
  const rWrist = rElbow + L_FORE * Math.sin(p23);
  const zWrist = zElbow - L_FORE * Math.cos(p23);
  const wrist: [number, number, number] = [bx + rWrist * c1, by + rWrist * s1, zWrist];
  const p234 = p23 + j4;
  const tip: [number, number, number] = [
    bx + (rWrist + L_WRIST * Math.sin(p234)) * c1,
    by + (rWrist + L_WRIST * Math.sin(p234)) * s1,
    zWrist - L_WRIST * Math.cos(p234),
  ];
  return {
    base_mm: [bx, by, GANTRY_Z_MM] as [number, number, number],
    shoulder_mm: shoulder,
    elbow_mm: elbow,
    wrist_mm: wrist,
    tip_mm: tip,
    yaw_rad: j1,
    tool_yaw_deg: (j1 + j6) * RAD2DEG,
  };
}

export function computeDelta3DKinematics(eeMm: [number, number, number]): MmsKinematics {
  const baseOffset = [-47.5, -47.5, -47.5];
  const armLen = 72.5;
  const rotorRad = 15.0;
  const eeAttach: [number, number, number][] = [
    [3.54, -11.5, 4.5],
    [4.5, 3.54, -11.5],
    [-11.5, 4.5, 3.54],
  ];
  const actTrans: [number, number, number][] = [
    [-21.5 + baseOffset[0], 21.0 + baseOffset[1], 52.0 + baseOffset[2]],
    [52.0 + baseOffset[0], -21.5 + baseOffset[1], 21.0 + baseOffset[2]],
    [21.0 + baseOffset[0], 52.0 + baseOffset[1], -21.5 + baseOffset[2]],
  ];
  const actRot: number[][][] = [
    [
      [0, -1, 0],
      [1, 0, 0],
      [0, 0, 1],
    ],
    [
      [0, 0, 1],
      [0, -1, 0],
      [1, 0, 0],
    ],
    [
      [1, 0, 0],
      [0, 0, 1],
      [0, -1, 0],
    ],
  ];
  const offsetRad = 42.0 * DEG2RAD;
  const rotorDeg: [number, number, number] = [42, 42, 42];
  const rotorRadOut: [number, number, number] = [offsetRad, offsetRad, offsetRad];
  const actuators: MmsActuatorGeom[] = [];
  let allValid = true;

  for (let i = 0; i < 3; i++) {
    const pb = [
      eeMm[0] + eeAttach[i][0] - actTrans[i][0],
      eeMm[1] + eeAttach[i][1] - actTrans[i][1],
      eeMm[2] + eeAttach[i][2] - actTrans[i][2],
    ];
    const R = actRot[i];
    const px = R[0][0] * pb[0] + R[1][0] * pb[1] + R[2][0] * pb[2];
    const py = R[0][1] * pb[0] + R[1][1] * pb[1] + R[2][1] * pb[2];
    const pz = R[0][2] * pb[0] + R[1][2] * pb[1] + R[2][2] * pb[2];

    const rProjSq = armLen * armLen - pz * pz;
    const dSq = px * px + py * py;
    let ang = offsetRad;
    if (rProjSq > 0 && dSq > 1e-12) {
      const d = Math.sqrt(dSq);
      const a = (rotorRad * rotorRad - rProjSq + dSq) / (2 * d);
      const hSq = rotorRad * rotorRad - a * a;
      if (hSq >= 0) {
        const h = Math.sqrt(hSq);
        const cx2 = (px * a) / d;
        const cy2 = (py * a) / d;
        const rx = (-py * h) / d;
        const ry = (px * h) / d;
        const qx = cx2 + rx > cx2 - rx ? cx2 + rx : cx2 - rx;
        const qy = cx2 + rx > cx2 - rx ? cy2 + ry : cy2 - ry;
        ang = offsetRad - Math.atan2(qy, qx);
      } else {
        allValid = false;
      }
    } else {
      allValid = false;
    }
    rotorRadOut[i] = ang;
    rotorDeg[i] = Number((ang * RAD2DEG).toFixed(4));

    const locAng = ang - offsetRad;
    const lx = Math.cos(locAng) * rotorRad;
    const ly = -Math.sin(locAng) * rotorRad;
    const tipBase: [number, number, number] = [
      R[0][0] * lx + R[0][1] * ly + actTrans[i][0],
      R[1][0] * lx + R[1][1] * ly + actTrans[i][1],
      R[2][0] * lx + R[2][1] * ly + actTrans[i][2],
    ];
    actuators.push({
      axis: (["A", "B", "C"] as const)[i],
      rotor_deg: rotorDeg[i],
      rotor_rad: Number(ang.toFixed(6)),
      horn_center_mm: actTrans[i],
      horn_tip_mm: tipBase,
      ee_joint_mm: [eeMm[0] + eeAttach[i][0], eeMm[1] + eeAttach[i][1], eeMm[2] + eeAttach[i][2]],
    });
  }

  return {
    valid: allValid,
    ee_mm: eeMm,
    ee_um: [
      Number((eeMm[0] * 1000).toFixed(3)),
      Number((eeMm[1] * 1000).toFixed(3)),
      Number((eeMm[2] * 1000).toFixed(3)),
    ],
    rotor_deg: rotorDeg,
    rotor_rad: rotorRadOut,
    actuators,
  };
}

let mjModule: MainModule | null = null;
let mjModel: MjModel | null = null;
let mjData: MjData | null = null;
let mjLoading: Promise<MainModule> | null = null;
let runAbort: AbortController | null = null;
let gcodeSeq = 1;
let eventSeq = 1;
let lastReactSyncMs = 0;

async function ensureMujocoWasm(): Promise<MainModule> {
  if (mjModule) return mjModule;
  if (mjLoading) return mjLoading;
  mjLoading = (async () => {
    const m = await loadMujoco();
    try {
      m.FS.mkdir("/working");
      const fsMod: { MEMFS?: unknown } = m;
      m.FS.mount(fsMod.MEMFS, { root: "." }, "/working");
    } catch {
      /* already mounted */
    }
    mjModule = m;
    return m;
  })();
  return mjLoading;
}

const initialKin = computeDelta3DKinematics([0, 0, 0]);
const initialHomeQ = solveArmIkClient([-145, 75, 115], 0, [-125, 75]);
const urlHasLab = typeof window !== "undefined" && new URLSearchParams(window.location.search).get("lab") === "1";

function loadXmlIntoMujoco(xml: string, initRailX: number, initCarriageY: number) {
  if (!mjModule) return { nq: 0, nu: 0, version: "—" };
  try {
    if (mjData) { mjData.delete(); mjData = null; }
    if (mjModel) { mjModel.delete(); mjModel = null; }
    mjModule.FS.writeFile("/working/beamteam_lab.xml", xml);
    mjModel = mjModule.MjModel.loadFromXML("/working/beamteam_lab.xml");
    mjData = new mjModule.MjData(mjModel);
    const qpos = mjData.qpos as Float64Array;
    const ctrl = mjData.ctrl as Float64Array;
    if (qpos.length >= 10) {
      qpos[2] = initRailX * 0.001;
      qpos[3] = 0;
      ctrl[2] = initRailX * 0.001;
      ctrl[3] = 0;
      for (let i = 0; i < 6; i++) {
        qpos[4 + i] = initialHomeQ[i];
        ctrl[4 + i] = initialHomeQ[i];
      }
    }
    void initCarriageY;
    mjModule.mj_forward(mjModel, mjData);
    return {
      nq: mjModel.nq,
      nu: mjModel.nu,
      version: mjModule.mj_versionString(),
    };
  } catch (e) {
    console.warn("MuJoCo XML load warning:", e);
    return { nq: 0, nu: 0, version: mjModule.mj_versionString?.() ?? "3.3.8" };
  }
}

function buildClientFallbackManifest(d: Design): { xml: string; manifest: LabManifest } {
  const tr = useStore.getState().trace;
  const placedById: Record<string, PlacedElement> = {};
  for (const p of tr?.elements ?? []) {
    placedById[p.id] = p;
  }
  const w = d.baseplate?.width_mm ?? 300;
  const h = d.baseplate?.height_mm ?? 150;
  const els = d.elements ?? [];
  const cols = els.length > 24 ? 11 : 4;
  const rows = Math.max(1, Math.ceil(els.length / cols));
  const pitch = els.length > 24 ? 34 : 42;
  const pickXy: [number, number] = [-180, Math.round(h * 0.5)];
  const zTop = (d.baseplate?.thickness_mm ?? 25.4) + (d.baseplate?.optical_height_mm ?? 12.7);
  const transitZ = Math.max(115, zTop + 65);
  const slots: CribSlot[] = els.map((el, idx) => {
    const pl = placedById[el.id];
    const benchXy: [number, number] = pl?.position ? [pl.position[0], pl.position[1]] : el.at ? [el.at[0], el.at[1]] : [80 + idx * 35, 75];
    const angle = pl?.angle_deg ?? el.angle_deg ?? 0;
    const col = idx % cols;
    const row = Math.floor(idx / cols);
    const pocketXy: [number, number] = [-col * pitch, (row - (rows - 1) * 0.5) * pitch];
    const stageXy: [number, number] = [-pocketXy[0], -pocketXy[1]];
    const isTunable = Boolean(TUNABLE_TYPES[el.type]);
    const pickRailX = -125;
    const placeRailX = Math.max(-135, Math.min(w, benchXy[0] - 35));
    const pickCy = pickXy[1];
    const placeCy = h > 120 ? Math.max(40, Math.min(h - 40, benchXy[1] - 45)) : h * 0.5;
    return {
      slot_index: idx,
      element_id: el.id,
      type: el.type,
      label: el.label || el.id,
      part_number: el.part_number || "",
      pocket_local_xy_mm: pocketXy,
      stage_present_xy_mm: stageXy,
      pick_station_xy_mm: pickXy,
      pick_rail_x_mm: pickRailX,
      place_rail_x_mm: placeRailX,
      pick_carriage_y_mm: pickCy,
      place_carriage_y_mm: placeCy,
      bench_xy_mm: benchXy,
      bench_z_mm: zTop,
      bench_angle_deg: angle,
      has_mms: isTunable,
      mms_unit_id: isTunable ? `MMS-${el.id}` : null,
      state: "placed",
      ik_keyframes: {
        home: solveArmIkClient([pickXy[0] + 35, pickXy[1], transitZ], 0, [pickRailX, pickCy]),
        pre_pick: solveArmIkClient([pickXy[0], pickXy[1], transitZ], 0, [pickRailX, pickCy]),
        pick: solveArmIkClient([pickXy[0], pickXy[1], 22], 0, [pickRailX, pickCy]),
        lift: solveArmIkClient([pickXy[0], pickXy[1], transitZ], 0, [pickRailX, pickCy]),
        pre_place: solveArmIkClient([benchXy[0], benchXy[1], transitZ], angle, [placeRailX, placeCy]),
        place: solveArmIkClient([benchXy[0], benchXy[1], zTop], angle, [placeRailX, placeCy]),
        retract: solveArmIkClient([benchXy[0], benchXy[1], transitZ], angle, [placeRailX, placeCy]),
        adjust_approach: solveArmIkClient([benchXy[0], benchXy[1], transitZ], angle, [placeRailX, placeCy]),
        adjust_engage: solveArmIkClient([benchXy[0], benchXy[1], zTop + 14], angle, [placeRailX, placeCy]),
        adjust_retract: solveArmIkClient([benchXy[0], benchXy[1], transitZ], angle, [placeRailX, placeCy]),
      },
    };
  });

  const xml = `<mujoco model="beamteam_overhead_lab">
    <option timestep="0.004" integrator="implicitfast"/>
    <default><joint damping="3.0" armature="0.02"/><position kp="180"/></default>
    <worldbody>
      <body name="xy_stage_x"><joint name="crib_x" type="slide" axis="1 0 0"/><geom type="box" size="0.1 0.1 0.01"/>
        <body name="inventory_crib"><joint name="crib_y" type="slide" axis="0 1 0"/><geom type="box" size="0.09 0.09 0.01"/></body>
      </body>
      <body name="gantry" pos="0 0 0.26">
        <body name="bridge"><joint name="arm_rail_x" type="slide" axis="1 0 0"/><geom type="box" size="0.02 0.2 0.01"/>
          <body name="trolley"><joint name="arm_rail_y" type="slide" axis="0 1 0"/><geom type="cylinder" size="0.025 0.016"/>
            <body name="arm_b1" pos="0 0 -0.032"><joint name="arm_j1" type="hinge" axis="0 0 1"/><geom type="cylinder" size="0.013 0.013"/>
              <body name="arm_b2"><joint name="arm_j2" type="hinge" axis="0 1 0"/><geom type="capsule" fromto="0 0 0 0 0 -0.135" size="0.010"/>
                <body name="arm_b3" pos="0 0 -0.135"><joint name="arm_j3" type="hinge" axis="0 1 0"/><geom type="capsule" fromto="0 0 0 0 0 -0.125" size="0.0085"/>
                  <body name="arm_b4" pos="0 0 -0.125"><joint name="arm_j4" type="hinge" axis="0 1 0"/><geom type="cylinder" size="0.0085 0.009"/>
                    <body name="arm_b5" pos="0 0 -0.018"><joint name="arm_j5" type="hinge" axis="1 0 0"/><geom type="cylinder" size="0.0075 0.008"/>
                      <body name="arm_b6" pos="0 0 -0.020"><joint name="arm_j6" type="hinge" axis="0 0 1"/><geom type="cylinder" size="0.0085 0.008"/>
                        <body name="gl"><joint name="grip_l" type="slide" axis="0 1 0"/><geom type="box" size="0.004 0.002 0.01"/></body>
                        <body name="gr"><joint name="grip_r" type="slide" axis="0 -1 0"/><geom type="box" size="0.004 0.002 0.01"/></body>
                      </body>
                    </body>
                  </body>
                </body>
              </body>
            </body>
          </body>
        </body>
      </body>
      <body name="mms_base" pos="0.35 0.075 0.025">
        <body name="ma"><joint name="mms_j_a" type="hinge" axis="0 1 0"/><geom type="capsule" fromto="0 0 0 0.015 0 0" size="0.003"/></body>
        <body name="mb"><joint name="mms_j_b" type="hinge" axis="0 1 0"/><geom type="capsule" fromto="0 0 0 0.015 0 0" size="0.003"/></body>
        <body name="mc"><joint name="mms_j_c" type="hinge" axis="0 1 0"/><geom type="capsule" fromto="0 0 0 0.015 0 0" size="0.003"/></body>
        <body name="mee"><joint name="mms_ee_x" type="slide" axis="1 0 0"/><joint name="mms_ee_y" type="slide" axis="0 1 0"/><joint name="mms_ee_z" type="slide" axis="0 0 1"/><geom type="cylinder" size="0.012 0.004"/></body>
      </body>
    </worldbody>
    <actuator>
      <position name="act_crib_x" joint="crib_x" kp="220"/>
      <position name="act_crib_y" joint="crib_y" kp="220"/>
      <position name="act_arm_rail_x" joint="arm_rail_x" kp="240"/>
      <position name="act_arm_rail_y" joint="arm_rail_y" kp="240"/>
      <position name="act_arm_j1" joint="arm_j1" kp="180"/>
      <position name="act_arm_j2" joint="arm_j2" kp="180"/>
      <position name="act_arm_j3" joint="arm_j3" kp="180"/>
      <position name="act_arm_j4" joint="arm_j4" kp="180"/>
      <position name="act_arm_j5" joint="arm_j5" kp="180"/>
      <position name="act_arm_j6" joint="arm_j6" kp="180"/>
      <position name="act_grip_l" joint="grip_l" kp="80"/>
      <position name="act_grip_r" joint="grip_r" kp="80"/>
      <position name="act_mms_a" joint="mms_j_a" kp="120"/>
      <position name="act_mms_b" joint="mms_j_b" kp="120"/>
      <position name="act_mms_c" joint="mms_j_c" kp="120"/>
      <position name="act_mms_ee_x" joint="mms_ee_x" kp="200"/>
      <position name="act_mms_ee_y" joint="mms_ee_y" kp="200"/>
      <position name="act_mms_ee_z" joint="mms_ee_z" kp="200"/>
    </actuator>
  </mujoco>`;

  return {
    xml,
    manifest: {
      design_name: d.name,
      pick_station_xy_mm: pickXy,
      arm_base_xy_mm: [-125, pickXy[1]],
      gantry_z_mm: GANTRY_Z_MM,
      rail_y_mm: pickXy[1],
      rail_range_mm: [-135, Math.max(w, 150)],
      arm_links_mm: { base_z: L_BASE, upper: L_UPPER, forearm: L_FORE, wrist: L_WRIST },
      crib_cols: cols,
      crib_pitch_mm: [pitch, pitch],
      mms_spec: {
        repo: "https://github.com/0x23/MicroManipulatorStepper",
        hardware_version: "v4.0",
        firmware_version: "v1.0.4",
        step_resolution_nm: 50,
        loop_rate_khz: 30,
        encoder: "MT6835 21-bit (30x magnetic gearing)",
        arm_length_mm: 72.5,
        rotor_radius_mm: 15.0,
        neutral_kinematics: computeDelta3DKinematics([0, 0, 0]),
      },
      slots,
    },
  };
}

export const useLab = create<LabState>((set, get) => ({
  enabled: urlHasLab,
  running: false,
  phase: "idle",
  statusMessage: "Overhead Gantry + Inverted 6-DOF UR5e + X/Y Crib Stage + 0x23/MicroManipulatorStepper ready",
  playbackSpeed: 2,
  setPlaybackSpeed: (v: number) => {
    const clamped = Math.max(0.5, Math.min(5, v));
    set((s) => ({
      playbackSpeed: clamped,
      eventLog: [
        ...s.eventLog.slice(-79),
        {
          id: eventSeq++,
          tag: "SPEED",
          color: "#fbbf24",
          text: `[SPEED] Playback speed set to ${clamped}x`,
        },
      ],
    }));
  },
  eventLog: [
    {
      id: eventSeq++,
      tag: "SYS",
      color: "#38bdf8",
      text: "MuJoCo WASM 3.3.8 + Overhead Gantry UR5e + X/Y Crib Stage + 0x23/MicroManipulatorStepper initialized",
    },
  ],

  wasmReady: false,
  wasmVersion: "3.3.8",
  simTimeS: 0,
  stepCount: 0,
  dofCount: 18,
  actuatorCount: 18,
  mjcfXml: null,
  manifest: null,

  slots: [],
  activeSlotIndex: 0,
  carriedElementId: null,
  adjustingElementId: null,

  stageCmdMm: [0, 0],
  stageSimMm: [0, 0],

  railRangeMm: [-135, 1200],
  railCmdXMm: -125,
  railSimXMm: -125,
  carriageCmdYMm: 450,
  carriageSimYMm: 450,

  armCmdRad: initialHomeQ,
  armSimRad: initialHomeQ,
  gripperM: 0.012,

  selectedMmsElementId: "",
  mmsPosMm: [0, 0, 0],
  mmsPosUm: [0, 0, 0],
  mmsRotorDeg: initialKin.rotor_deg,
  mmsEncoderCounts: [229376, 229376, 229376],
  mmsKinematics: initialKin,
  mmsHomed: true,
  mmsMotorsEnabled: true,
  gcodeLog: [
    {
      id: gcodeSeq++,
      unit_id: "MMS-MAIN",
      element_id: "bench",
      command: "M58",
      status: "ok",
      response: "v1.0.4 (0x23/MicroManipulatorStepper HW v4.0)",
      pos_um: [0, 0, 0],
      rotor_deg: [42, 42, 42],
      encoder_counts: [229376, 229376, 229376],
    },
  ],

  setEnabled: (v) => {
    set({ enabled: v });
    if (v) {
      useView.getState().setPreset("iso");
      const d = useStore.getState().design;
      if (d) void get().initWorkcell(d);
    }
  },

  initWorkcell: async (d: Design) => {
    await ensureMujocoWasm();
    let xml = "";
    let manifest: LabManifest | null = null;
    try {
      const resp = await fetch("/api/lab/mjcf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ design: d }),
      });
      if (resp.ok) {
        const j = (await resp.json()) as { xml: string; manifest: LabManifest };
        xml = j.xml;
        manifest = j.manifest;
      }
    } catch {
      /* fallback to client generator */
    }
    if (!manifest) {
      const fb = buildClientFallbackManifest(d);
      xml = fb.xml;
      manifest = fb.manifest;
    }
    const initRailX = manifest.slots[0]?.place_rail_x_mm ?? 120;
    const initCy = manifest.slots[0]?.place_carriage_y_mm ?? manifest.pick_station_xy_mm[1];
    const info = loadXmlIntoMujoco(xml, initRailX, initCy);
    const slots: CribSlot[] = manifest.slots.map((s) => ({
      ...s,
      state: get().running ? (s.state ?? "in_crib") : "placed",
    }));
    const firstTunable = slots.find((s) => s.has_mms) ?? slots[0];
    const initArmQ = (firstTunable?.ik_keyframes.adjust_engage as [number, number, number, number, number, number]) ?? initialHomeQ;
    set({
      wasmReady: true,
      wasmVersion: info.version,
      dofCount: info.nq || 18,
      actuatorCount: info.nu || 18,
      mjcfXml: xml,
      manifest,
      slots,
      railRangeMm: manifest.rail_range_mm,
      railCmdXMm: firstTunable?.place_rail_x_mm ?? initRailX,
      railSimXMm: firstTunable?.place_rail_x_mm ?? initRailX,
      carriageCmdYMm: firstTunable?.place_carriage_y_mm ?? initCy,
      carriageSimYMm: firstTunable?.place_carriage_y_mm ?? initCy,
      armCmdRad: initArmQ,
      armSimRad: initArmQ,
      selectedMmsElementId: firstTunable?.element_id ?? "",
      adjustingElementId: firstTunable?.element_id ?? null,
    });
  },

  setRailXMm: (xMm: number) => {
    const [rMin, rMax] = get().railRangeMm;
    const clampedX = Math.max(rMin, Math.min(rMax, xMm));
    const cy = get().carriageCmdYMm;
    // Keep inverted arm posed cleanly below the gantry carriage as the slider moves
    const q = solveArmIkClient([clampedX + 35, cy + 35, 110], 0, [clampedX, cy]);
    set({
      railCmdXMm: clampedX,
      railSimXMm: clampedX,
      armCmdRad: q,
      armSimRad: q,
      statusMessage: `Overhead gantry bridge positioned at X = ${clampedX.toFixed(0)} mm along build plate`,
    });
  },

  setCarriageYMm: (yMm: number) => {
    const d = useStore.getState().design;
    const maxH = d?.baseplate?.height_mm ?? 150;
    const clampedY = Math.max(0, Math.min(maxH, yMm));
    const rx = get().railCmdXMm;
    const q = solveArmIkClient([rx + 35, clampedY + 35, 110], 0, [rx, clampedY]);
    set({
      carriageCmdYMm: clampedY,
      carriageSimYMm: clampedY,
      armCmdRad: q,
      armSimRad: q,
      statusMessage: `Overhead gantry trolley positioned at Y = ${clampedY.toFixed(0)} mm across build plate`,
    });
  },

  focusElementWithRobot: (elementId: string) => {
    const slot = get().slots.find((s) => s.element_id === elementId);
    if (!slot) return;
    const engageQ = (slot.ik_keyframes.adjust_engage as [number, number, number, number, number, number]) ?? initialHomeQ;
    set({
      selectedMmsElementId: elementId,
      adjustingElementId: elementId,
      railCmdXMm: slot.place_rail_x_mm,
      carriageCmdYMm: slot.place_carriage_y_mm,
      armCmdRad: engageQ,
      statusMessage: `Overhead gantry moved to X=${slot.place_rail_x_mm.toFixed(0)}, Y=${slot.place_carriage_y_mm.toFixed(0)} mm · Inverted UR5e docked on ${elementId}`,
    });
  },

  indexCribSlot: (slotIndex: number) => {
    const slot = get().slots[slotIndex];
    if (!slot) return;
    const prePick = (slot.ik_keyframes.pre_pick as [number, number, number, number, number, number]) ?? initialHomeQ;
    set({
      activeSlotIndex: slotIndex,
      stageCmdMm: slot.stage_present_xy_mm,
      railCmdXMm: slot.pick_rail_x_mm,
      carriageCmdYMm: slot.pick_carriage_y_mm,
      armCmdRad: prePick,
      statusMessage: `Indexed X/Y crib stage to slot #${slotIndex} (${slot.element_id}: ${slot.type}) · Overhead gantry at pick station`,
    });
  },

  stopRun: () => {
    runAbort?.abort();
    runAbort = null;
    set({ running: false, phase: "idle", carriedElementId: null, statusMessage: "Run stopped" });
  },

  startAutonomousRun: async (useLlm = true) => {
    const baseDesign = useStore.getState().design;
    if (!baseDesign) return;
    runAbort?.abort();
    const ac = new AbortController();
    runAbort = ac;

    if (!get().enabled) {
      get().setEnabled(true);
    } else {
      useView.getState().setPreset("iso");
    }

    await get().initWorkcell(baseDesign);
    const con = useConsole.getState();
    con.reset();
    const pushEvent = (tag: string, color: string, text: string) => {
      set((s) => ({
        eventLog: [...s.eventLog.slice(-79), { id: eventSeq++, tag, color, text }],
      }));
    };

    const nTotal = (baseDesign.elements ?? []).length;
    const stageDelayMs = nTotal > 40 ? 45 : 90;
    const armDelayMs = nTotal > 40 ? 55 : 95;
    const placeDelayMs = nTotal > 40 ? 20 : 40;
    const mmsDelayMs = nTotal > 40 ? 60 : 75;

    const sleepScaled = async (baseMs: number) => {
      let elapsedScaled = 0;
      while (elapsedScaled < baseMs && !ac.signal.aborted) {
        const { promise, resolve } = Promise.withResolvers<void>();
        window.setTimeout(resolve, 16);
        await promise;
        elapsedScaled += 16 * Math.max(0.5, get().playbackSpeed);
      }
    };

    set((s) => ({
      running: true,
      phase: "planning",
      carriedElementId: null,
      adjustingElementId: null,
      activeSlotIndex: 0,
      slots: s.slots.map((sl) => ({ ...sl, state: "in_crib" })),
      eventLog: [
        {
          id: eventSeq++,
          tag: "ARGON",
          color: "#a78bfa",
          text: "Spawning Argon Lab Director + Crib Stage + Overhead UR5e + MicroManipulatorStepper agents…",
        },
      ],
      statusMessage: "Argon Lab Director planning overhead-gantry assembly & 0x23/MicroManipulatorStepper alignment…",
    }));

    try {
      const resp = await fetch("/api/lab/run", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ design: baseDesign, use_llm: useLlm, pace_ms: 0 }),
        signal: ac.signal,
      });
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = "";

      while (true) {
        if (ac.signal.aborted) break;
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        let idx: number;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          if (ac.signal.aborted) break;
          const block = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const dataLine = block
            .split("\n")
            .filter((l) => l.startsWith("data:"))
            .map((l) => l.slice(5).trim())
            .join("\n");
          if (!dataLine) continue;
          let ev: LabSseEvent;
          try {
            ev = JSON.parse(dataLine) as LabSseEvent;
          } catch {
            continue;
          }

          if (CONSOLE_EVENT_TYPES[ev.type]) {
            con.ingest(ev as unknown as Parameters<typeof con.ingest>[0]);
          }
          if (ev.type === "thought" && ev.text) {
            pushEvent(ev.agent_id?.toUpperCase() ?? "ARGON", "#a78bfa", ev.text);
          }

          if (ev.type === "lab_init" && ev.mjcf_xml && ev.manifest) {
            const info = loadXmlIntoMujoco(ev.mjcf_xml, -125, ev.manifest.pick_station_xy_mm[1]);
            set({
              wasmReady: true,
              wasmVersion: info.version,
              mjcfXml: ev.mjcf_xml,
              manifest: ev.manifest,
              railRangeMm: ev.manifest.rail_range_mm,
              slots: ev.manifest.slots.map((sl) => ({ ...sl, state: "in_crib" })),
              phase: "planning",
            });
            pushEvent("MUJOCO", "#38bdf8", `Loaded MJCF workcell (${ev.manifest.slots.length} optical crib slots, 18 DOF)`);
          } else if (ev.type === "lab_stage" && ev.stage_xy_mm) {
            set((s) => ({
              phase: "building",
              activeSlotIndex: ev.slot_index ?? 0,
              stageCmdMm: ev.stage_xy_mm!,
              railCmdXMm: ev.rail_x_mm ?? s.railCmdXMm,
              carriageCmdYMm: ev.carriage_y_mm ?? s.carriageCmdYMm,
              statusMessage: ev.message ?? "",
            }));
            pushEvent(
              "XY-CRIB",
              "#38bdf8",
              `Slot #${ev.slot_index ?? 0} (${ev.element_id ?? ""}) indexed -> stage (${ev.stage_xy_mm[0].toFixed(0)}, ${ev.stage_xy_mm[1].toFixed(0)}) mm`,
            );
            await sleepScaled(stageDelayMs);
          } else if (ev.type === "lab_arm" && ev.element_id && ev.arm_q_rad) {
            const eid = ev.element_id;
            const pState = ev.part_state ?? "carried";
            const isAdjust = (ev.phase ?? "").startsWith("adjust");
            set((s) => ({
              phase: isAdjust ? "aligning" : "building",
              activeSlotIndex: ev.slot_index ?? s.activeSlotIndex,
              railCmdXMm: ev.rail_x_mm ?? s.railCmdXMm,
              carriageCmdYMm: ev.carriage_y_mm ?? s.carriageCmdYMm,
              armCmdRad: ev.arm_q_rad!,
              gripperM: ev.gripper_m ?? 0.008,
              carriedElementId: pState === "carried" ? eid : null,
              adjustingElementId: isAdjust ? eid : null,
              selectedMmsElementId: isAdjust ? eid : s.selectedMmsElementId,
              slots: s.slots.map((sl) => (sl.element_id === eid ? { ...sl, state: pState } : sl)),
              statusMessage: ev.message ?? "",
            }));
            if (ev.phase === "pick" || ev.phase === "place" || ev.phase === "adjust_engage") {
              pushEvent(
                "UR5e-IK",
                "#fbbf24",
                `${ev.phase.toUpperCase()} ${eid} @ Gantry (${(ev.rail_x_mm ?? 0).toFixed(0)}, ${(ev.carriage_y_mm ?? 0).toFixed(0)}) mm`,
              );
            }
            await sleepScaled(armDelayMs);
          } else if (ev.type === "lab_place" && ev.design && ev.trace && ev.report) {
            const placedMap: Record<string, true> = {};
            for (const pid of ev.placed_ids ?? []) placedMap[pid] = true;
            set((s) => ({
              carriedElementId: null,
              slots: s.slots.map((sl) => (placedMap[sl.element_id] ? { ...sl, state: "placed" } : sl)),
              statusMessage: `Placed ${(ev.placed_ids ?? []).length}/${ev.total_parts ?? s.slots.length} optics (${ev.element_id ?? ""}) — live beam trace updated`,
            }));
            useStore.getState().showDesign(ev.design, { trace: ev.trace, report: ev.report });
            pushEvent(
              "BENCH",
              "#34d399",
              `Mounted ${ev.element_id ?? ""} (${(ev.placed_ids ?? []).length}/${ev.total_parts ?? 0}) · rays=${ev.trace.segments.length}`,
            );
            await sleepScaled(placeDelayMs);
          } else if (ev.type === "lab_mms" && ev.gcode) {
            const gc = ev.gcode;
            const entry: GcodeLogEntry = {
              id: gcodeSeq++,
              unit_id: gc.unit_id,
              element_id: gc.element_id || ev.element_id || "bench",
              command: gc.command,
              status: gc.status,
              response: gc.response || gc.status,
              pos_um: gc.pos_um,
              rotor_deg: gc.rotor_deg,
              encoder_counts: gc.encoder_counts,
            };
            if (ev.best_so_far && ev.element_id && ev.patch) {
              useStore.getState().updateElement(ev.element_id, ev.patch);
            }
            set((s) => ({
              phase: "aligning",
              selectedMmsElementId: ev.element_id || s.selectedMmsElementId,
              adjustingElementId: ev.element_id || s.adjustingElementId,
              railCmdXMm: ev.rail_x_mm ?? s.railCmdXMm,
              carriageCmdYMm: ev.carriage_y_mm ?? s.carriageCmdYMm,
              armCmdRad: ev.arm_q_rad ?? s.armCmdRad,
              mmsPosMm: gc.pos_mm,
              mmsPosUm: gc.pos_um,
              mmsRotorDeg: gc.rotor_deg,
              mmsEncoderCounts: gc.encoder_counts,
              mmsKinematics: gc.kinematics,
              gcodeLog: [...s.gcodeLog.slice(-119), entry],
              statusMessage: ev.message ?? "",
            }));
            pushEvent(
              "MMS-GCODE",
              "#10b981",
              `${gc.unit_id}: ${gc.command} -> (${gc.pos_um[0].toFixed(1)}, ${gc.pos_um[1].toFixed(1)}, ${gc.pos_um[2].toFixed(1)}) µm`,
            );
            await sleepScaled(mmsDelayMs);
          } else if (ev.type === "lab_done" && ev.design && ev.trace && ev.report) {
            const finalRep = ev.report;
            useStore.getState().showDesign(ev.design, { trace: ev.trace, report: finalRep });
            set((s) => ({
              running: false,
              phase: "done",
              carriedElementId: null,
              slots: s.slots.map((sl) => ({ ...sl, state: "placed" })),
              statusMessage: `Autonomous lab complete — ${ev.summary?.parts_assembled ?? s.slots.length} parts assembled, ${ev.summary?.mms_gcode_moves ?? 0} MicroManipulatorStepper G-code moves · PASS (${finalRep.score.toFixed(1)})`,
            }));
            pushEvent(
              "DONE",
              "#10b981",
              `Assembly & alignment complete · Score ${finalRep.score.toFixed(1)} (${finalRep.passed ? "PASS" : "CHECK"})`,
            );
          }
        }
      }
    } catch (e) {
      const err = e instanceof Error ? e : new Error(String(e));
      if (err.name !== "AbortError") {
        set({ running: false, phase: "idle", statusMessage: `Lab run error: ${err.message}` });
      }
    } finally {
      if (runAbort === ac) {
        set((s) => ({ running: false, phase: s.phase === "done" ? "done" : "idle" }));
      }
    }
  },

  sendGcode: async (commands: string[], elementId?: string) => {
    const targetEl = elementId || get().selectedMmsElementId || "FC1";
    const unitId = `MMS-${targetEl}`;
    get().focusElementWithRobot(targetEl);
    try {
      const resp = await fetch("/api/lab/gcode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ unit_id: unitId, element_id: targetEl, commands }),
      });
      if (resp.ok) {
        const j = (await resp.json()) as LabGcodeResponse;
        const newEntries: GcodeLogEntry[] = (j.results ?? []).map((r) => ({
          id: gcodeSeq++,
          unit_id: r.unit_id,
          element_id: r.element_id,
          command: r.command,
          status: r.status,
          response: r.response || r.status,
          pos_um: r.pos_um,
          rotor_deg: r.rotor_deg,
          encoder_counts: r.encoder_counts,
        }));
        set((s) => ({
          selectedMmsElementId: targetEl,
          mmsHomed: j.homed,
          mmsMotorsEnabled: j.motors_enabled,
          mmsPosMm: j.pos_mm,
          mmsPosUm: j.pos_um,
          mmsRotorDeg: j.rotor_deg,
          mmsEncoderCounts: j.encoder_counts,
          mmsKinematics: j.kinematics,
          gcodeLog: [...s.gcodeLog.slice(-119), ...newEntries],
          statusMessage: `[${unitId}] ${commands.join(" ; ")} -> (${j.pos_um[0].toFixed(2)}, ${j.pos_um[1].toFixed(2)}, ${j.pos_um[2].toFixed(2)}) µm`,
        }));
        return;
      }
    } catch {
      /* offline fallback below */
    }
    for (const cmd of commands) {
      const up = cmd.trim().toUpperCase();
      const nextPos: [number, number, number] = [...get().mmsPosMm] as [number, number, number];
      let respText = "ok";
      if (up.startsWith("G28")) {
        nextPos[0] = 0;
        nextPos[1] = 0;
        nextPos[2] = 0;
        respText = "I)Parallel homing complete on A B C";
      } else if (up.startsWith("M58")) {
        respText = "v1.0.4";
      } else if (up.startsWith("G0") || up.startsWith("G1") || up.startsWith("G24")) {
        const mx = up.match(/X([-+]?\d*\.?\d+)/);
        const my = up.match(/Y([-+]?\d*\.?\d+)/);
        const mz = up.match(/Z([-+]?\d*\.?\d+)/);
        if (mx) nextPos[0] = Number(mx[1]);
        if (my) nextPos[1] = Number(my[1]);
        if (mz) nextPos[2] = Number(mz[1]);
      } else if (up.startsWith("M50")) {
        respText = `X${nextPos[0].toFixed(6)} Y${nextPos[1].toFixed(6)} Z${nextPos[2].toFixed(6)}`;
      }
      const kin = computeDelta3DKinematics(nextPos);
      const counts: [number, number, number] = [
        Math.round((kin.rotor_rad[0] * 65536 * 30) / (2 * Math.PI)),
        Math.round((kin.rotor_rad[1] * 65536 * 30) / (2 * Math.PI)),
        Math.round((kin.rotor_rad[2] * 65536 * 30) / (2 * Math.PI)),
      ];
      set((s) => ({
        mmsPosMm: nextPos,
        mmsPosUm: kin.ee_um,
        mmsRotorDeg: kin.rotor_deg,
        mmsEncoderCounts: counts,
        mmsKinematics: kin,
        gcodeLog: [
          ...s.gcodeLog.slice(-119),
          {
            id: gcodeSeq++,
            unit_id: unitId,
            element_id: targetEl,
            command: cmd,
            status: "ok",
            response: respText,
            pos_um: kin.ee_um,
            rotor_deg: kin.rotor_deg,
            encoder_counts: counts,
          },
        ],
      }));
    }
  },

  jogMmsUm: async (axis: "X" | "Y" | "Z", deltaUm: number) => {
    const cur = [...get().mmsPosMm] as [number, number, number];
    const idx = axis === "X" ? 0 : axis === "Y" ? 1 : 2;
    cur[idx] = Math.max(-5.5, Math.min(5.5, Number((cur[idx] + deltaUm * 0.001).toFixed(6))));
    const cmd = `G0 X${cur[0].toFixed(6)} Y${cur[1].toFixed(6)} Z${cur[2].toFixed(6)} F10.000`;
    const targetId = get().selectedMmsElementId;
    await get().sendGcode([cmd, "M50"], targetId);

    const d = useStore.getState().design;
    const el = d?.elements?.find((e) => e.id === targetId);
    if (el) {
      if (axis === "X" && el.distance_mm != null) {
        useStore.getState().updateElement(el.id, { distance_mm: Number((el.distance_mm + deltaUm * 0.002).toFixed(4)) });
      } else if (axis === "Y" && el.type === "mirror") {
        if (el.out_direction_deg != null) {
          useStore.getState().updateElement(el.id, { out_direction_deg: Number((el.out_direction_deg + deltaUm * 0.004).toFixed(4)) });
        } else if (el.angle_deg != null) {
          useStore.getState().updateElement(el.id, { angle_deg: Number((el.angle_deg + deltaUm * 0.002).toFixed(4)) });
        }
      } else if (el.type === "half_wave_plate" || el.type === "quarter_wave_plate") {
        const curFa = el.fast_axis_deg ?? 0;
        useStore.getState().updateElement(el.id, { fast_axis_deg: Number(((curFa + deltaUm * 0.01) % 180).toFixed(3)) });
      }
    }
  },

  stepMujoco: (dt: number) => {
    const st = get();
    if (!st.enabled) return;

    const pickY0 = st.manifest?.pick_station_xy_mm[1] ?? 450;

    if (mjModule && mjModel && mjData && mjModel.nu >= 18) {
      const ctrl = mjData.ctrl as Float64Array;
      const qpos = mjData.qpos as Float64Array;
      ctrl[0] = st.stageCmdMm[0] * 0.001;
      ctrl[1] = st.stageCmdMm[1] * 0.001;
      ctrl[2] = st.railCmdXMm * 0.001;
      ctrl[3] = (st.carriageCmdYMm - pickY0) * 0.001;
      for (let i = 0; i < 6; i++) {
        ctrl[4 + i] = st.armCmdRad[i];
      }
      ctrl[10] = st.gripperM;
      ctrl[11] = st.gripperM;
      ctrl[12] = (st.mmsRotorDeg[0] - 42) * DEG2RAD;
      ctrl[13] = (st.mmsRotorDeg[1] - 42) * DEG2RAD;
      ctrl[14] = (st.mmsRotorDeg[2] - 42) * DEG2RAD;
      ctrl[15] = st.mmsPosMm[0] * 0.001;
      ctrl[16] = st.mmsPosMm[1] * 0.001;
      ctrl[17] = st.mmsPosMm[2] * 0.001;

      const substeps = Math.max(1, Math.min(24, Math.round((dt * st.playbackSpeed * 1.8) / 0.004)));
      for (let k = 0; k < substeps; k++) {
        mjModule.mj_step(mjModel, mjData);
      }
      // Blend qpos toward commanded targets scaled by playbackSpeed so 1x..5x is visually immediate on the 1.2m gantry
      const trackAlpha = Math.min(1, dt * 18 * st.playbackSpeed);
      qpos[0] += (ctrl[0] - qpos[0]) * trackAlpha;
      qpos[1] += (ctrl[1] - qpos[1]) * trackAlpha;
      qpos[2] += (ctrl[2] - qpos[2]) * trackAlpha;
      qpos[3] += (ctrl[3] - qpos[3]) * trackAlpha;
      for (let i = 0; i < 6; i++) {
        qpos[4 + i] += (ctrl[4 + i] - qpos[4 + i]) * trackAlpha;
      }

      const nowMs = performance.now();
      if (nowMs - lastReactSyncMs < 16) return;
      const simStage: [number, number] = [qpos[0] * 1000, qpos[1] * 1000];
      const simRailX = qpos[2] * 1000;
      const simCarriageY = pickY0 + qpos[3] * 1000;
      const simArm: [number, number, number, number, number, number] = [
        qpos[4],
        qpos[5],
        qpos[6],
        qpos[7],
        qpos[8],
        qpos[9],
      ];
      const stageDelta = Math.hypot(simStage[0] - st.stageSimMm[0], simStage[1] - st.stageSimMm[1]);
      const railDelta = Math.hypot(simRailX - st.railSimXMm, simCarriageY - st.carriageSimYMm);
      let armDelta = 0;
      for (let i = 0; i < 6; i++) armDelta = Math.max(armDelta, Math.abs(simArm[i] - st.armSimRad[i]));
      if (stageDelta > 0.15 || railDelta > 0.2 || armDelta > 0.0025) {
        lastReactSyncMs = nowMs;
        set({
          simTimeS: mjData.time,
          stepCount: st.stepCount + substeps,
          stageSimMm: simStage,
          railSimXMm: simRailX,
          carriageSimYMm: simCarriageY,
          armSimRad: simArm,
        });
      }
    } else {
      const nowMs = performance.now();
      if (nowMs - lastReactSyncMs < 16) return;
      const alpha = Math.min(1, dt * 18 * st.playbackSpeed);
      const nextStage: [number, number] = [
        st.stageSimMm[0] + (st.stageCmdMm[0] - st.stageSimMm[0]) * alpha,
        st.stageSimMm[1] + (st.stageCmdMm[1] - st.stageSimMm[1]) * alpha,
      ];
      const nextRailX = st.railSimXMm + (st.railCmdXMm - st.railSimXMm) * alpha;
      const nextCy = st.carriageSimYMm + (st.carriageCmdYMm - st.carriageSimYMm) * alpha;
      const nextArm = st.armSimRad.map((v, i) => v + (st.armCmdRad[i] - v) * alpha) as [number, number, number, number, number, number];
      const stageDelta = Math.hypot(nextStage[0] - st.stageSimMm[0], nextStage[1] - st.stageSimMm[1]);
      const railDelta = Math.hypot(nextRailX - st.railSimXMm, nextCy - st.carriageSimYMm);
      let armDelta = 0;
      for (let i = 0; i < 6; i++) armDelta = Math.max(armDelta, Math.abs(nextArm[i] - st.armSimRad[i]));
      if (stageDelta > 0.15 || railDelta > 0.2 || armDelta > 0.0025) {
        lastReactSyncMs = nowMs;
        set({
          simTimeS: st.simTimeS + dt,
          stepCount: st.stepCount + 1,
          stageSimMm: nextStage,
          railSimXMm: nextRailX,
          carriageSimYMm: nextCy,
          armSimRad: nextArm,
        });
      }
    }
  },
}));

useStore.subscribe((state, prevState) => {
  if (state.design && state.design.name !== prevState.design?.name && useLab.getState().enabled && !useLab.getState().running) {
    void useLab.getState().initWorkcell(state.design);
  }
});
