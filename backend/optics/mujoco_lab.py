"""MuJoCo workcell generator and 6-DOF robot arm + X/Y crib stage kinematics.

Models a complete self-running automated optics laboratory workcell:
1. Optical breadboard (`baseplate`) with laser sources and dowel-pin mounting sites.
2. Motorized 2-axis X/Y part-presentation stage (`crib_stage_x`, `crib_stage_y`) carrying
   an inventory crib tray (`inventory_crib`) of optical components. Indexing `(crib_x, crib_y)`
   presents any requested part pocket directly to the calibrated Pick Station `(pick_x, pick_y)`.
3. 6-DOF Robot Arm (`arm_j1..j6` + parallel gripper) mounted between the X/Y crib stage and
   the optical breadboard for automated pick-and-place bench assembly.
4. `0x23/MicroManipulatorStepper` (HW v4.0 Delta-3D) sub-micrometer alignment actuators coupled
   to the tunable optical mounts for closed-loop alignment.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any

from .ir import Design
from .micromanipulator import KinematicModelDelta3D
from .trace import trace

DEG2RAD = math.pi / 180.0
RAD2DEG = 180.0 / math.pi

# Workcell geometry constants (in millimetres, converted to metres in MJCF XML)
# Optical breadboard lower-left corner is at (0, 0, 0) in table frame.
# Motorized X/Y presentation stage + crib sits to the left of the optical table (negative X).
PICK_STATION_XY_MM: tuple[float, float] = (-110.0, 95.0)
ARM_BASE_XY_MM: tuple[float, float] = (-55.0, -45.0)
CRIB_COLS = 4
CRIB_PITCH_X_MM = 42.0
CRIB_PITCH_Y_MM = 42.0

# 6-DOF robot arm link lengths (mm)
L_BASE_Z_MM = 85.0
L_UPPER_MM = 240.0
L_FORE_MM = 220.0
L_WRIST_MM = 55.0


def solve_arm_ik(
    target_xyz_mm: tuple[float, float, float],
    tool_yaw_deg: float = 0.0,
    base_xy_mm: tuple[float, float] = ARM_BASE_XY_MM,
) -> list[float]:
    """Analytical 6-DOF inverse kinematics returning [j1, j2, j3, j4, j5, j6] in radians.

    - j1: waist yaw around +Z toward target (x, y)
    - j2: shoulder pitch
    - j3: elbow pitch
    - j4: wrist pitch (keeps end-effector pointing straight down -Z)
    - j5: wrist roll (0 for vertical pick/place)
    - j6: tool yaw to align optical mount to `tool_yaw_deg`
    """
    tx, ty, tz = target_xyz_mm
    bx, by = base_xy_mm
    dx = tx - bx
    dy = ty - by
    j1 = math.atan2(dy, dx)

    r_horiz = math.hypot(dx, dy)
    # Wrist center height when tool points down (-Z)
    wrist_z = tz + L_WRIST_MM
    dz = wrist_z - L_BASE_Z_MM

    d = math.hypot(r_horiz, dz)
    max_reach = L_UPPER_MM + L_FORE_MM - 2.0
    min_reach = abs(L_UPPER_MM - L_FORE_MM) + 2.0
    d_clamped = max(min_reach, min(max_reach, d))

    # Law of cosines for elbow-up configuration
    cos_elbow = (L_UPPER_MM**2 + L_FORE_MM**2 - d_clamped**2) / (2.0 * L_UPPER_MM * L_FORE_MM)
    cos_elbow = max(-1.0, min(1.0, cos_elbow))
    # j3 = 0 means straight out; positive bends downward
    j3 = math.pi - math.acos(cos_elbow)

    alpha = math.atan2(dz, r_horiz)
    cos_beta = (L_UPPER_MM**2 + d_clamped**2 - L_FORE_MM**2) / (2.0 * L_UPPER_MM * d_clamped)
    cos_beta = max(-1.0, min(1.0, cos_beta))
    beta = math.acos(cos_beta)
    # j2 measured from vertical (+Z) forward
    j2 = (math.pi / 2.0) - (alpha + beta)

    # Keep gripper vertical (-Z): j2 + j3 + j4 = pi/2
    j4 = (math.pi / 2.0) - (j2 + j3)
    j5 = 0.0
    j6 = (tool_yaw_deg * DEG2RAD) - j1
    # Wrap j6 to [-pi, pi]
    j6 = (j6 + math.pi) % (2.0 * math.pi) - math.pi

    return [round(v, 5) for v in (j1, j2, j3, j4, j5, j6)]


def forward_arm_fk(
    joints_rad: list[float],
    base_xy_mm: tuple[float, float] = ARM_BASE_XY_MM,
) -> dict[str, list[float]]:
    """Compute 3D positions (mm) of base, shoulder, elbow, wrist, and gripper tip for rendering & verification."""
    j1, j2, j3, j4, _, j6 = (joints_rad + [0.0] * 6)[:6]
    bx, by = base_xy_mm
    c1, s1 = math.cos(j1), math.sin(j1)

    shoulder = [bx, by, L_BASE_Z_MM]
    # j2 is angle from +Z toward radial direction (c1, s1)
    r_elbow = L_UPPER_MM * math.sin(j2)
    z_elbow = L_BASE_Z_MM + L_UPPER_MM * math.cos(j2)
    elbow = [bx + r_elbow * c1, by + r_elbow * s1, z_elbow]

    pitch23 = j2 + j3
    r_wrist = r_elbow + L_FORE_MM * math.sin(pitch23)
    z_wrist = z_elbow + L_FORE_MM * math.cos(pitch23)
    wrist = [bx + r_wrist * c1, by + r_wrist * s1, z_wrist]

    pitch234 = pitch23 + j4
    r_tip = r_wrist + L_WRIST_MM * math.sin(pitch234)
    z_tip = z_wrist - L_WRIST_MM * math.sin(pitch234) if abs(pitch234 - math.pi / 2.0) < 0.2 else z_wrist + L_WRIST_MM * math.cos(pitch234)
    # Exact tip when pointing down (pitch234 == pi/2 -> downwards along -Z)
    tip = [
        bx + (r_wrist + L_WRIST_MM * math.cos(pitch234)) * c1,
        by + (r_wrist + L_WRIST_MM * math.cos(pitch234)) * s1,
        z_wrist - L_WRIST_MM * math.sin(pitch234),
    ]
    return {
        "base_mm": [round(bx, 2), round(by, 2), 0.0],
        "shoulder_mm": [round(v, 2) for v in shoulder],
        "elbow_mm": [round(v, 2) for v in elbow],
        "wrist_mm": [round(v, 2) for v in wrist],
        "tip_mm": [round(v, 2) for v in tip],
        "tool_yaw_deg": round((j1 + j6) * RAD2DEG, 2),
    }


def build_crib_manifest(design: Design) -> dict[str, Any]:
    """Assign each optical element in `design` a pocket in the motorized X/Y inventory crib
    and compute its exact pick-and-place trajectory and `MicroManipulatorStepper` coupling."""
    tr = trace(design)
    placed_map = {p.id: p for p in tr.elements}

    # Order elements by beam arrival order (like assembly order), then any remaining
    order_ids: list[str] = []
    for seg in tr.segments:
        if seg.end_element and seg.end_element not in order_ids:
            order_ids.append(seg.end_element)
    for el in design.elements:
        if el.id not in order_ids:
            order_ids.append(el.id)

    el_by_id = {e.id: e for e in design.elements}
    slots: list[dict[str, Any]] = []
    tunable_types = {"half_wave_plate", "quarter_wave_plate", "lens", "mirror", "fiber_coupler", "beamsplitter", "sampler"}

    for idx, eid in enumerate(order_ids):
        el = el_by_id.get(eid)
        if el is None:
            continue
        pl = placed_map.get(eid)
        bench_xy = list(pl.position) if (pl and pl.position) else list(el.at or (100.0, 75.0))
        bench_angle = float(pl.angle_deg if (pl and pl.angle_deg is not None) else (el.angle_deg or 0.0))

        col = idx % CRIB_COLS
        row = idx // CRIB_COLS
        # Local pocket offset inside the inventory crib tray
        pocket_local_xy = (col * CRIB_PITCH_X_MM, row * CRIB_PITCH_Y_MM)
        # Stage (crib_x, crib_y) displacement needed to bring this pocket to PICK_STATION_XY_MM
        stage_target_xy = (-pocket_local_xy[0], -pocket_local_xy[1])

        z_top = design.baseplate.thickness_mm + design.baseplate.optical_height_mm
        pick_z = 22.0
        transit_z = max(85.0, z_top + 45.0)

        keyframes = {
            "home": solve_arm_ik((PICK_STATION_XY_MM[0] + 35.0, PICK_STATION_XY_MM[1], transit_z), 0.0),
            "pre_pick": solve_arm_ik((PICK_STATION_XY_MM[0], PICK_STATION_XY_MM[1], transit_z), 0.0),
            "pick": solve_arm_ik((PICK_STATION_XY_MM[0], PICK_STATION_XY_MM[1], pick_z), 0.0),
            "lift": solve_arm_ik((PICK_STATION_XY_MM[0], PICK_STATION_XY_MM[1], transit_z), 0.0),
            "pre_place": solve_arm_ik((bench_xy[0], bench_xy[1], transit_z), bench_angle),
            "place": solve_arm_ik((bench_xy[0], bench_xy[1], z_top), bench_angle),
            "retract": solve_arm_ik((bench_xy[0], bench_xy[1], transit_z), bench_angle),
        }

        has_mms = el.type in tunable_types
        slots.append({
            "slot_index": idx,
            "element_id": eid,
            "type": el.type,
            "label": el.label or eid,
            "part_number": el.part_number or "",
            "pocket_local_xy_mm": [round(pocket_local_xy[0], 2), round(pocket_local_xy[1], 2)],
            "stage_present_xy_mm": [round(stage_target_xy[0], 2), round(stage_target_xy[1], 2)],
            "pick_station_xy_mm": list(PICK_STATION_XY_MM),
            "bench_xy_mm": [round(bench_xy[0], 2), round(bench_xy[1], 2)],
            "bench_z_mm": round(z_top, 2),
            "bench_angle_deg": round(bench_angle, 2),
            "has_mms": has_mms,
            "mms_unit_id": f"MMS-{eid}" if has_mms else None,
            "ik_keyframes": keyframes,
        })

    delta = KinematicModelDelta3D()
    return {
        "design_name": design.name,
        "pick_station_xy_mm": list(PICK_STATION_XY_MM),
        "arm_base_xy_mm": list(ARM_BASE_XY_MM),
        "arm_links_mm": {
            "base_z": L_BASE_Z_MM,
            "upper": L_UPPER_MM,
            "forearm": L_FORE_MM,
            "wrist": L_WRIST_MM,
        },
        "crib_cols": CRIB_COLS,
        "crib_pitch_mm": [CRIB_PITCH_X_MM, CRIB_PITCH_Y_MM],
        "mms_spec": {
            "repo": "https://github.com/0x23/MicroManipulatorStepper",
            "hardware_version": "v4.0",
            "firmware_version": "v1.0.4",
            "step_resolution_nm": 50.0,
            "loop_rate_khz": 30.0,
            "encoder": "MT6835 21-bit (30x magnetic gearing)",
            "arm_length_mm": delta.arm_length,
            "rotor_radius_mm": delta.rotor_radius,
            "neutral_kinematics": delta.linkage_geometry((0.0, 0.0, 0.0)),
        },
        "slots": slots,
    }


def build_lab_mjcf(design: Design) -> tuple[str, dict[str, Any]]:
    """Generate a complete MuJoCo MJCF XML model of the robotics optics lab for `design`.

    Units in MJCF are metres (1 mm = 0.001 m).
    """
    manifest = build_crib_manifest(design)
    bp = design.baseplate
    w_m = bp.width_mm * 0.001
    h_m = bp.height_mm * 0.001
    t_m = bp.thickness_mm * 0.001

    mj = ET.Element("mujoco", model=f"beamteam_lab_{design.name}")
    ET.SubElement(mj, "compiler", angle="radian", coordinate="local", inertiafromgeom="true")
    ET.SubElement(mj, "option", timestep="0.004", gravity="0 0 -9.81", integrator="implicitfast")

    default = ET.SubElement(mj, "default")
    ET.SubElement(default, "joint", damping="2.5", armature="0.02")
    ET.SubElement(default, "geom", contype="0", conaffinity="0", friction="0.8 0.1 0.1")
    ET.SubElement(default, "position", kp="180")

    world = ET.SubElement(mj, "worldbody")
    ET.SubElement(world, "light", name="lab_key", pos="0.15 0.1 0.9", dir="0 0 -1", diffuse="0.85 0.85 0.9")
    ET.SubElement(world, "geom", name="lab_floor", type="plane", pos="0.1 0.1 -0.04", size="1.2 1.2 0.05", rgba="0.11 0.13 0.16 1")

    # 1. Optical breadboard
    plate_body = ET.SubElement(
        world, "body", name="optical_baseplate",
        pos=f"{w_m / 2:.4f} {h_m / 2:.4f} {t_m / 2:.4f}",
    )
    ET.SubElement(
        plate_body, "geom", name="baseplate_geom", type="box",
        size=f"{w_m / 2:.4f} {h_m / 2:.4f} {t_m / 2:.4f}",
        rgba="0.16 0.18 0.22 1",
    )

    # 2. Motorized X/Y Part-Presentation Stage + Inventory Crib
    px_m, py_m = PICK_STATION_XY_MM[0] * 0.001, PICK_STATION_XY_MM[1] * 0.001
    stage_base = ET.SubElement(world, "body", name="xy_stage_base", pos=f"{px_m:.4f} {py_m:.4f} 0.008")
    ET.SubElement(stage_base, "geom", name="xy_stage_frame", type="box", size="0.11 0.11 0.008", rgba="0.22 0.25 0.30 1")

    stage_x = ET.SubElement(stage_base, "body", name="xy_stage_x_carriage", pos="0 0 0.010")
    ET.SubElement(stage_x, "joint", name="crib_x", type="slide", axis="1 0 0", range="-0.25 0.25", damping="8.0")
    ET.SubElement(stage_x, "geom", name="xy_rail_x", type="box", size="0.095 0.085 0.004", rgba="0.28 0.33 0.40 1")

    stage_y = ET.SubElement(stage_x, "body", name="inventory_crib", pos="0 0 0.008")
    ET.SubElement(stage_y, "joint", name="crib_y", type="slide", axis="0 1 0", range="-0.25 0.25", damping="8.0")
    ET.SubElement(stage_y, "geom", name="crib_tray_geom", type="box", size="0.09 0.09 0.004", rgba="0.18 0.22 0.28 1")

    # Populate crib pockets
    for slot in manifest["slots"]:
        sx = slot["pocket_local_xy_mm"][0] * 0.001
        sy = slot["pocket_local_xy_mm"][1] * 0.001
        eid = slot["element_id"]
        p_body = ET.SubElement(stage_y, "body", name=f"crib_part_{eid}", pos=f"{sx:.4f} {sy:.4f} 0.010")
        ET.SubElement(p_body, "geom", name=f"crib_geom_{eid}", type="cylinder", size="0.009 0.008", rgba="0.35 0.65 0.95 1")

    # 3. 6-DOF Robot Arm + Parallel Gripper
    bx_m, by_m = ARM_BASE_XY_MM[0] * 0.001, ARM_BASE_XY_MM[1] * 0.001
    arm_pedestal = ET.SubElement(world, "body", name="arm_pedestal", pos=f"{bx_m:.4f} {by_m:.4f} 0.0")
    ET.SubElement(arm_pedestal, "geom", name="pedestal_geom", type="cylinder", fromto="0 0 0 0 0 0.045", size="0.032", rgba="0.24 0.27 0.32 1")

    b_j1 = ET.SubElement(arm_pedestal, "body", name="arm_link1_waist", pos=f"0 0 {L_BASE_Z_MM * 0.001:.4f}")
    ET.SubElement(b_j1, "joint", name="arm_j1", type="hinge", axis="0 0 1", range="-3.1416 3.1416", damping="4.0")
    ET.SubElement(b_j1, "geom", name="arm_g1", type="cylinder", fromto="0 0 -0.04 0 0 0.02", size="0.026", rgba="0.92 0.48 0.14 1")

    b_j2 = ET.SubElement(b_j1, "body", name="arm_link2_upper", pos="0 0 0")
    ET.SubElement(b_j2, "joint", name="arm_j2", type="hinge", axis="0 1 0", range="-2.4 2.4", damping="4.0")
    ET.SubElement(b_j2, "geom", name="arm_g2", type="capsule", fromto=f"0 0 0 0 0 {L_UPPER_MM * 0.001:.4f}", size="0.018", rgba="0.88 0.90 0.94 1")

    b_j3 = ET.SubElement(b_j2, "body", name="arm_link3_forearm", pos=f"0 0 {L_UPPER_MM * 0.001:.4f}")
    ET.SubElement(b_j3, "joint", name="arm_j3", type="hinge", axis="0 1 0", range="-2.8 2.8", damping="3.5")
    ET.SubElement(b_j3, "geom", name="arm_g3", type="capsule", fromto=f"0 0 0 0 0 {L_FORE_MM * 0.001:.4f}", size="0.015", rgba="0.92 0.48 0.14 1")

    b_j4 = ET.SubElement(b_j3, "body", name="arm_link4_wrist1", pos=f"0 0 {L_FORE_MM * 0.001:.4f}")
    ET.SubElement(b_j4, "joint", name="arm_j4", type="hinge", axis="0 1 0", range="-3.1416 3.1416", damping="2.0")
    ET.SubElement(b_j4, "geom", name="arm_g4", type="cylinder", fromto="0 -0.018 0 0 0.018 0", size="0.013", rgba="0.25 0.28 0.34 1")

    b_j5 = ET.SubElement(b_j4, "body", name="arm_link5_wrist2", pos="0 0 0.025")
    ET.SubElement(b_j5, "joint", name="arm_j5", type="hinge", axis="1 0 0", range="-3.1416 3.1416", damping="1.5")
    ET.SubElement(b_j5, "geom", name="arm_g5", type="cylinder", fromto="0 0 0 0 0 0.025", size="0.011", rgba="0.88 0.90 0.94 1")

    b_j6 = ET.SubElement(b_j5, "body", name="arm_link6_tool", pos="0 0 0.030")
    ET.SubElement(b_j6, "joint", name="arm_j6", type="hinge", axis="0 0 1", range="-3.1416 3.1416", damping="1.0")
    ET.SubElement(b_j6, "geom", name="arm_g6_flange", type="cylinder", fromto="0 0 0 0 0 0.012", size="0.014", rgba="0.18 0.20 0.24 1")
    ET.SubElement(b_j6, "site", name="gripper_tcp", pos="0 0 0.025", size="0.004")

    grip_l = ET.SubElement(b_j6, "body", name="gripper_finger_l", pos="0 0.008 0.018")
    ET.SubElement(grip_l, "joint", name="grip_l", type="slide", axis="0 1 0", range="0 0.014", damping="1.0")
    ET.SubElement(grip_l, "geom", name="grip_l_geom", type="box", size="0.004 0.002 0.012", rgba="0.15 0.80 0.55 1")

    grip_r = ET.SubElement(b_j6, "body", name="gripper_finger_r", pos="0 -0.008 0.018")
    ET.SubElement(grip_r, "joint", name="grip_r", type="slide", axis="0 -1 0", range="0 0.014", damping="1.0")
    ET.SubElement(grip_r, "geom", name="grip_r_geom", type="box", size="0.004 0.002 0.012", rgba="0.15 0.80 0.55 1")

    # 4. 0x23/MicroManipulatorStepper Delta-3D Fine Alignment Unit
    mms_body = ET.SubElement(world, "body", name="mms_delta3d_base", pos=f"{w_m + 0.055:.4f} {h_m * 0.5:.4f} {t_m:.4f}")
    ET.SubElement(mms_body, "geom", name="mms_block_geom", type="box", size="0.028 0.028 0.024", rgba="0.20 0.23 0.29 1")
    for idx, ax_char in enumerate(("a", "b", "c")):
        horn = ET.SubElement(mms_body, "body", name=f"mms_rotor_{ax_char}", pos=f"{(idx - 1) * 0.018:.4f} -0.026 0.010")
        ET.SubElement(horn, "joint", name=f"mms_j_{ax_char}", type="hinge", axis="0 1 0", range="-1.57 1.57", damping="0.8")
        ET.SubElement(horn, "geom", name=f"mms_horn_geom_{ax_char}", type="capsule", fromto="0 0 0 0.015 0 0", size="0.003", rgba="0.95 0.72 0.18 1")

    mms_ee = ET.SubElement(mms_body, "body", name="mms_end_effector", pos="0 0 0.036")
    ET.SubElement(mms_ee, "joint", name="mms_ee_x", type="slide", axis="1 0 0", range="-0.006 0.006", damping="2.0")
    ET.SubElement(mms_ee, "joint", name="mms_ee_y", type="slide", axis="0 1 0", range="-0.006 0.006", damping="2.0")
    ET.SubElement(mms_ee, "joint", name="mms_ee_z", type="slide", axis="0 0 1", range="-0.006 0.006", damping="2.0")
    ET.SubElement(mms_ee, "geom", name="mms_ee_plate", type="cylinder", size="0.014 0.004", rgba="0.22 0.75 0.92 1")

    # Actuators
    act = ET.SubElement(mj, "actuator")
    ET.SubElement(act, "position", name="act_crib_x", joint="crib_x", kp="220")
    ET.SubElement(act, "position", name="act_crib_y", joint="crib_y", kp="220")
    for j in range(1, 7):
        ET.SubElement(act, "position", name=f"act_arm_j{j}", joint=f"arm_j{j}", kp="180")
    ET.SubElement(act, "position", name="act_grip_l", joint="grip_l", kp="80")
    ET.SubElement(act, "position", name="act_grip_r", joint="grip_r", kp="80")
    for ax_char in ("a", "b", "c"):
        ET.SubElement(act, "position", name=f"act_mms_{ax_char}", joint=f"mms_j_{ax_char}", kp="120")
    for ax_char in ("x", "y", "z"):
        ET.SubElement(act, "position", name=f"act_mms_ee_{ax_char}", joint=f"mms_ee_{ax_char}", kp="200")

    ET.indent(mj, space="  ")
    xml_str = ET.tostring(mj, encoding="unicode")
    return xml_str, manifest
