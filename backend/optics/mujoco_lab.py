"""MuJoCo workcell generator: Overhead Gantry + Inverted 6-DOF UR5e/UR3e Cobot + X/Y Crib Stage.

Models a complete self-running automated optics laboratory workcell scaled up to full
multi-module apparatus tables (such as the 121-optic, 1200x900 mm `sr_ion_apparatus`):
1. Optical breadboard (`baseplate`) with laser sources and dowel-pin mounting sites.
2. Motorized 2-axis X/Y part-presentation stage (`crib_x`, `crib_y`) carrying an inventory
   crib tray (`inventory_crib`) of optical components to the left of the table. Indexing
   `(crib_x, crib_y)` presents any requested part pocket directly to the calibrated Pick Station.
3. Overhead Gantry Bridge (`arm_rail_x` slider along the full build plate length) supporting an
   **inverted 6-DOF UR5e/UR3e industrial cobot arm** (`arm_j1..j6` + parallel gripper + integrated
   `0x23/MicroManipulatorStepper` fine-adjustment toolhead) hanging from above the optical table.
4. `0x23/MicroManipulatorStepper` (HW v4.0 Delta-3D) sub-micrometer alignment actuator carried on
   the robot's adjustment toolhead to dock onto and align each tunable optic from above.
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

# Overhead Gantry & Inverted 6-DOF Arm geometry (mm)
GANTRY_Z_MM = 260.0
L_BASE_Z_MM = 32.0     # inverted base turret drop from overhead gantry carriage (shoulder at Z = 228 mm)
L_UPPER_MM = 135.0     # upper arm link
L_FORE_MM = 125.0      # forearm link
L_WRIST_MM = 38.0      # wrist + gripper + MicroManipulator toolhead drop to TCP

def workcell_dims(design: Design) -> dict[str, Any]:
    """Compute adaptive workcell coordinates for any table size (from 300x150 mm up to 1200x900 mm `sr_ion_apparatus`)."""
    w = float(design.baseplate.width_mm)
    h = float(design.baseplate.height_mm)
    n_el = len(design.elements)
    cols = 11 if n_el > 24 else 4
    pitch = 34.0 if n_el > 24 else 42.0
    pick_x = -180.0
    pick_y = round(h * 0.5, 1)
    rail_min_x = -135.0
    rail_max_x = round(max(w, 150.0), 1)
    return {
        "plate_w_mm": w,
        "plate_h_mm": h,
        "pick_station_xy_mm": (pick_x, pick_y),
        "crib_cols": cols,
        "crib_pitch_mm": (pitch, pitch),
        "rail_min_x_mm": rail_min_x,
        "rail_max_x_mm": rail_max_x,
        "gantry_z_mm": GANTRY_Z_MM,
    }


def clamp_rail_x(x_mm: float, plate_width_mm: float = 300.0) -> float:
    """Clamp the overhead gantry bridge X coordinate along the build plate length."""
    return round(max(-135.0, min(max(plate_width_mm, 150.0), float(x_mm))), 2)


def solve_arm_ik(
    target_xyz_mm: tuple[float, float, float],
    tool_yaw_deg: float = 0.0,
    base_xy_mm: tuple[float, float] = (-125.0, 75.0),
) -> list[float]:
    """Analytical 6-DOF inverse kinematics for the **inverted** overhead-gantry cobot arm.

    The arm base hangs downward from `(base_xy_mm[0], base_xy_mm[1], GANTRY_Z_MM)` with the
    shoulder joint at `z_shoulder = GANTRY_Z_MM - L_BASE_Z_MM`.
    Returns `[j1, j2, j3, j4, j5, j6]` in radians:
    - `j1`: base yaw around vertical axis toward `(tx - bx, ty - by)`
    - `j2`: shoulder angle measured from straight down (`-Z`) outward
    - `j3`: elbow bend angle
    - `j4`: wrist 1 pitch (`-(j2 + j3)` so toolhead points vertically straight down `-Z`)
    - `j5`: wrist 2 roll (`0.0`)
    - `j6`: wrist 3 tool yaw to orient optical mount or adjustment driver to `tool_yaw_deg`
    """
    tx, ty, tz = target_xyz_mm
    bx, by = base_xy_mm
    dx = tx - bx
    dy = ty - by
    j1 = math.atan2(dy, dx) if abs(dx) + abs(dy) > 1e-3 else 0.0

    r_horiz = math.hypot(dx, dy)
    z_shoulder = GANTRY_Z_MM - L_BASE_Z_MM
    z_wrist = tz + L_WRIST_MM
    dz_down = max(20.0, z_shoulder - z_wrist)

    d = math.hypot(r_horiz, dz_down)
    max_reach = L_UPPER_MM + L_FORE_MM - 4.0
    min_reach = abs(L_UPPER_MM - L_FORE_MM) + 4.0
    d_clamped = max(min_reach, min(max_reach, d))

    cos_elbow = (L_UPPER_MM**2 + L_FORE_MM**2 - d_clamped**2) / (2.0 * L_UPPER_MM * L_FORE_MM)
    cos_elbow = max(-1.0, min(1.0, cos_elbow))
    # Elbow bends inward/downward after the upper arm reaches outward
    j3 = -(math.pi - math.acos(cos_elbow))

    alpha = math.atan2(r_horiz, dz_down)  # angle from straight down (-Z) to target wrist vector
    cos_beta = (L_UPPER_MM**2 + d_clamped**2 - L_FORE_MM**2) / (2.0 * L_UPPER_MM * d_clamped)
    cos_beta = max(-1.0, min(1.0, cos_beta))
    beta = math.acos(cos_beta)
    # Shoulder reaches outward by alpha + beta so the elbow bows cleanly away from vertical
    j2 = alpha + beta

    # Keep gripper + MicroManipulator toolhead pointing straight down (-Z)
    j4 = -(j2 + j3)
    j5 = 0.0
    j6 = (tool_yaw_deg * DEG2RAD) - j1
    j6 = (j6 + math.pi) % (2.0 * math.pi) - math.pi

    return [round(v, 5) for v in (j1, j2, j3, j4, j5, j6)]


def forward_arm_fk(
    joints_rad: list[float],
    base_xy_mm: tuple[float, float] = (-125.0, 75.0),
) -> dict[str, list[float] | float]:
    """Compute 3D positions (mm) of inverted overhead base, shoulder, elbow, wrist, and TCP tip."""
    j1, j2, j3, j4, _, j6 = (joints_rad + [0.0] * 6)[:6]
    bx, by = base_xy_mm
    c1, s1 = math.cos(j1), math.sin(j1)

    z_shoulder = GANTRY_Z_MM - L_BASE_Z_MM
    shoulder = [bx, by, z_shoulder]

    # j2 is measured from straight down (-Z) outward along (c1, s1)
    r_elbow = L_UPPER_MM * math.sin(j2)
    z_elbow = z_shoulder - L_UPPER_MM * math.cos(j2)
    elbow = [bx + r_elbow * c1, by + r_elbow * s1, z_elbow]

    pitch23 = j2 + j3
    r_wrist = r_elbow + L_FORE_MM * math.sin(pitch23)
    z_wrist = z_elbow - L_FORE_MM * math.cos(pitch23)
    wrist = [bx + r_wrist * c1, by + r_wrist * s1, z_wrist]

    pitch234 = pitch23 + j4
    tip = [
        bx + (r_wrist + L_WRIST_MM * math.sin(pitch234)) * c1,
        by + (r_wrist + L_WRIST_MM * math.sin(pitch234)) * s1,
        z_wrist - L_WRIST_MM * math.cos(pitch234),
    ]
    return {
        "base_mm": [round(bx, 2), round(by, 2), round(GANTRY_Z_MM, 2)],
        "shoulder_mm": [round(v, 2) for v in shoulder],
        "elbow_mm": [round(v, 2) for v in elbow],
        "wrist_mm": [round(v, 2) for v in wrist],
        "tip_mm": [round(v, 2) for v in tip],
        "tool_yaw_deg": round((j1 + j6) * RAD2DEG, 2),
    }


def build_crib_manifest(design: Design) -> dict[str, Any]:
    """Assign each optical element in `design` a pocket in the motorized X/Y inventory crib
    and compute its overhead-gantry + inverted 6-DOF pick, place, and adjustment trajectories."""
    tr = trace(design)
    placed_map = {p.id: p for p in tr.elements}
    dims = workcell_dims(design)
    plate_w = dims["plate_w_mm"]
    plate_h = dims["plate_h_mm"]
    pick_xy = dims["pick_station_xy_mm"]
    cols = dims["crib_cols"]
    pitch_x, pitch_y = dims["crib_pitch_mm"]

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
    rows = max(1, math.ceil(len(order_ids) / cols))

    for idx, eid in enumerate(order_ids):
        el = el_by_id.get(eid)
        if el is None:
            continue
        pl = placed_map.get(eid)
        bench_xy = list(pl.position) if (pl and pl.position) else list(el.at or (100.0, 75.0))
        bench_angle = float(pl.angle_deg if (pl and pl.angle_deg is not None) else (el.angle_deg or 0.0))

        col = idx % cols
        row = idx // cols
        pocket_local_xy = (-col * pitch_x, (row - (rows - 1) * 0.5) * pitch_y)
        stage_target_xy = (-pocket_local_xy[0], -pocket_local_xy[1])

        z_top = design.baseplate.thickness_mm + design.baseplate.optical_height_mm
        pick_z = 22.0
        transit_z = max(85.0, z_top + 42.0)
        adjust_engage_z = z_top + 14.0

        pick_rail_x = -125.0
        place_rail_x = clamp_rail_x(bench_xy[0] - 25.0, plate_w)
        # Overhead gantry carriage Y tracks target Y within table bounds so the inverted UR3e arm has ~35 mm horizontal reach
        pick_carriage_y = pick_xy[1]
        place_carriage_y = round(max(20.0, min(plate_h - 20.0, bench_xy[1] - 25.0)), 2)

        pick_base = (pick_rail_x, pick_carriage_y)
        place_base = (place_rail_x, place_carriage_y)
        keyframes = {
            "home": solve_arm_ik((pick_xy[0] + 35.0, pick_xy[1], transit_z), 0.0, pick_base),
            "pre_pick": solve_arm_ik((pick_xy[0], pick_xy[1], transit_z), 0.0, pick_base),
            "pick": solve_arm_ik((pick_xy[0], pick_xy[1], pick_z), 0.0, pick_base),
            "lift": solve_arm_ik((pick_xy[0], pick_xy[1], transit_z), 0.0, pick_base),
            "pre_place": solve_arm_ik((bench_xy[0], bench_xy[1], transit_z), bench_angle, place_base),
            "place": solve_arm_ik((bench_xy[0], bench_xy[1], z_top), bench_angle, place_base),
            "retract": solve_arm_ik((bench_xy[0], bench_xy[1], transit_z), bench_angle, place_base),
            "adjust_approach": solve_arm_ik((bench_xy[0], bench_xy[1], transit_z), bench_angle, place_base),
            "adjust_engage": solve_arm_ik((bench_xy[0], bench_xy[1], adjust_engage_z), bench_angle, place_base),
            "adjust_retract": solve_arm_ik((bench_xy[0], bench_xy[1], transit_z), bench_angle, place_base),
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
            "pick_station_xy_mm": list(pick_xy),
            "pick_rail_x_mm": pick_rail_x,
            "place_rail_x_mm": place_rail_x,
            "pick_carriage_y_mm": pick_carriage_y,
            "place_carriage_y_mm": place_carriage_y,
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
        "pick_station_xy_mm": list(pick_xy),
        "arm_base_xy_mm": [-125.0, pick_xy[1]],
        "gantry_z_mm": GANTRY_Z_MM,
        "rail_y_mm": pick_xy[1],
        "rail_range_mm": [dims["rail_min_x_mm"], dims["rail_max_x_mm"]],
        "arm_links_mm": {
            "base_z": L_BASE_Z_MM,
            "upper": L_UPPER_MM,
            "forearm": L_FORE_MM,
            "wrist": L_WRIST_MM,
        },
        "crib_cols": cols,
        "crib_pitch_mm": [pitch_x, pitch_y],
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
    """Generate a complete MuJoCo MJCF XML model of the overhead-gantry robotics optics lab."""
    manifest = build_crib_manifest(design)
    bp = design.baseplate
    w_m = bp.width_mm * 0.001
    h_m = bp.height_mm * 0.001
    t_m = bp.thickness_mm * 0.001
    gantry_z_m = GANTRY_Z_MM * 0.001
    pick_xy = manifest["pick_station_xy_mm"]

    mj = ET.Element("mujoco", model=f"beamteam_lab_{design.name}")
    ET.SubElement(mj, "compiler", angle="radian", coordinate="local", inertiafromgeom="true")
    ET.SubElement(mj, "option", timestep="0.004", gravity="0 0 -9.81", integrator="implicitfast")

    default = ET.SubElement(mj, "default")
    ET.SubElement(default, "joint", damping="3.0", armature="0.02")
    ET.SubElement(default, "geom", contype="0", conaffinity="0", friction="0.8 0.1 0.1")
    ET.SubElement(default, "position", kp="180")

    world = ET.SubElement(mj, "worldbody")
    ET.SubElement(world, "light", name="lab_key", pos=f"{w_m * 0.5:.3f} {h_m * 0.5:.3f} 1.2", dir="0 0 -1", diffuse="0.85 0.85 0.9")
    ET.SubElement(world, "geom", name="lab_floor", type="plane", pos="0.2 0.2 -0.04", size="2.0 2.0 0.05", rgba="0.11 0.13 0.16 1")

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
    px_m, py_m = pick_xy[0] * 0.001, pick_xy[1] * 0.001
    stage_base = ET.SubElement(world, "body", name="xy_stage_base", pos=f"{px_m:.4f} {py_m:.4f} 0.008")
    ET.SubElement(stage_base, "geom", name="xy_stage_frame", type="box", size="0.16 0.16 0.008", rgba="0.22 0.25 0.30 1")

    stage_x = ET.SubElement(stage_base, "body", name="xy_stage_x_carriage", pos="0 0 0.010")
    ET.SubElement(stage_x, "joint", name="crib_x", type="slide", axis="1 0 0", range="-0.45 0.45", damping="8.0")
    ET.SubElement(stage_x, "geom", name="xy_rail_x", type="box", size="0.14 0.14 0.004", rgba="0.28 0.33 0.40 1")

    stage_y = ET.SubElement(stage_x, "body", name="inventory_crib", pos="0 0 0.008")
    ET.SubElement(stage_y, "joint", name="crib_y", type="slide", axis="0 1 0", range="-0.45 0.45", damping="8.0")
    ET.SubElement(stage_y, "geom", name="crib_tray_geom", type="box", size="0.14 0.14 0.004", rgba="0.18 0.22 0.28 1")

    # Cap individual crib part geoms in MJCF at 32 so 121-element tables compile in <2 ms in WASM
    for slot in manifest["slots"][:32]:
        sx = slot["pocket_local_xy_mm"][0] * 0.001
        sy = slot["pocket_local_xy_mm"][1] * 0.001
        eid = slot["element_id"]
        p_body = ET.SubElement(stage_y, "body", name=f"crib_part_{eid}", pos=f"{sx:.4f} {sy:.4f} 0.010")
        ET.SubElement(p_body, "geom", name=f"crib_geom_{eid}", type="cylinder", size="0.008 0.007", rgba="0.35 0.65 0.95 1")

    # 3. Overhead Gantry Frame + Inverted 6-DOF UR5e/UR3e Arm
    rail_max_m = max(w_m, 0.15)
    gantry_frame = ET.SubElement(world, "body", name="overhead_gantry_frame", pos=f"0.0 0.0 {gantry_z_m:.4f}")
    ET.SubElement(
        gantry_frame, "geom", name="gantry_rail_front", type="box",
        pos=f"{(rail_max_m - 0.10) * 0.5:.4f} -0.035 0.012",
        size=f"{(rail_max_m + 0.22) * 0.5:.4f} 0.016 0.014",
        rgba="0.22 0.26 0.33 1",
    )
    ET.SubElement(
        gantry_frame, "geom", name="gantry_rail_back", type="box",
        pos=f"{(rail_max_m - 0.10) * 0.5:.4f} {h_m + 0.035:.4f} 0.012",
        size=f"{(rail_max_m + 0.22) * 0.5:.4f} 0.016 0.014",
        rgba="0.22 0.26 0.33 1",
    )

    gantry_bridge = ET.SubElement(gantry_frame, "body", name="gantry_x_bridge", pos="0 0 0")
    ET.SubElement(
        gantry_bridge, "joint", name="arm_rail_x", type="slide", axis="1 0 0",
        range=f"-0.15 {rail_max_m + 0.08:.4f}", damping="12.0",
    )
    ET.SubElement(
        gantry_bridge, "geom", name="bridge_beam_geom", type="box",
        pos=f"0 {h_m * 0.5:.4f} 0.015",
        size=f"0.024 {h_m * 0.5 + 0.045:.4f} 0.014",
        rgba="0.92 0.52 0.14 1",
    )

    arm_trolley = ET.SubElement(gantry_bridge, "body", name="gantry_y_trolley", pos=f"0 {py_m:.4f} 0")
    ET.SubElement(
        arm_trolley, "joint", name="arm_rail_y", type="slide", axis="0 1 0",
        range=f"{-py_m - 0.02:.4f} {h_m - py_m + 0.02:.4f}", damping="12.0",
    )
    ET.SubElement(arm_trolley, "geom", name="inverted_pedestal", type="cylinder", fromto="0 0 0 0 0 -0.042", size="0.034", rgba="0.20 0.23 0.28 1")

    b_j1 = ET.SubElement(arm_trolley, "body", name="arm_link1_waist", pos=f"0 0 {-L_BASE_Z_MM * 0.001:.4f}")
    ET.SubElement(b_j1, "joint", name="arm_j1", type="hinge", axis="0 0 1", range="-3.1416 3.1416", damping="4.0")
    ET.SubElement(b_j1, "geom", name="arm_g1", type="cylinder", fromto="0 0 0.02 0 0 -0.02", size="0.028", rgba="0.22 0.58 0.86 1")

    b_j2 = ET.SubElement(b_j1, "body", name="arm_link2_upper", pos="0 0 0")
    ET.SubElement(b_j2, "joint", name="arm_j2", type="hinge", axis="0 1 0", range="-2.6 2.6", damping="4.5")
    ET.SubElement(b_j2, "geom", name="arm_g2", type="capsule", fromto=f"0 0 0 0 0 {-L_UPPER_MM * 0.001:.4f}", size="0.019", rgba="0.86 0.89 0.93 1")

    b_j3 = ET.SubElement(b_j2, "body", name="arm_link3_forearm", pos=f"0 0 {-L_UPPER_MM * 0.001:.4f}")
    ET.SubElement(b_j3, "joint", name="arm_j3", type="hinge", axis="0 1 0", range="-2.9 2.9", damping="3.5")
    ET.SubElement(b_j3, "geom", name="arm_g3", type="capsule", fromto=f"0 0 0 0 0 {-L_FORE_MM * 0.001:.4f}", size="0.016", rgba="0.86 0.89 0.93 1")

    b_j4 = ET.SubElement(b_j3, "body", name="arm_link4_wrist1", pos=f"0 0 {-L_FORE_MM * 0.001:.4f}")
    ET.SubElement(b_j4, "joint", name="arm_j4", type="hinge", axis="0 1 0", range="-3.1416 3.1416", damping="2.0")
    ET.SubElement(b_j4, "geom", name="arm_g4", type="cylinder", fromto="0 -0.020 0 0 0.020 0", size="0.014", rgba="0.22 0.58 0.86 1")

    b_j5 = ET.SubElement(b_j4, "body", name="arm_link5_wrist2", pos="0 0 -0.026")
    ET.SubElement(b_j5, "joint", name="arm_j5", type="hinge", axis="1 0 0", range="-3.1416 3.1416", damping="1.5")
    ET.SubElement(b_j5, "geom", name="arm_g5", type="cylinder", fromto="0 0 0 0 0 -0.024", size="0.013", rgba="0.22 0.58 0.86 1")

    b_j6 = ET.SubElement(b_j5, "body", name="arm_link6_tool", pos="0 0 -0.030")
    ET.SubElement(b_j6, "joint", name="arm_j6", type="hinge", axis="0 0 1", range="-3.1416 3.1416", damping="1.0")
    ET.SubElement(b_j6, "geom", name="arm_g6_flange", type="cylinder", fromto="0 0 0 0 0 -0.014", size="0.015", rgba="0.18 0.20 0.24 1")
    ET.SubElement(b_j6, "site", name="gripper_tcp", pos="0 0 -0.025", size="0.004")

    grip_l = ET.SubElement(b_j6, "body", name="gripper_finger_l", pos="0 0.008 -0.018")
    ET.SubElement(grip_l, "joint", name="grip_l", type="slide", axis="0 1 0", range="0 0.014", damping="1.0")
    ET.SubElement(grip_l, "geom", name="grip_l_geom", type="box", size="0.004 0.002 0.012", rgba="0.15 0.80 0.55 1")

    grip_r = ET.SubElement(b_j6, "body", name="gripper_finger_r", pos="0 -0.008 -0.018")
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
    ET.SubElement(act, "position", name="act_arm_rail_x", joint="arm_rail_x", kp="240")
    ET.SubElement(act, "position", name="act_arm_rail_y", joint="arm_rail_y", kp="240")
    for j in range(1, 7):
        ET.SubElement(act, "position", name=f"act_arm_j{j}", joint=f"arm_j{j}", kp="180")
    ET.SubElement(act, "position", name="act_grip_l", joint="grip_l", kp="80")
    ET.SubElement(act, "position", name="act_grip_r", joint="grip_r", kp="80")
    for ax_char in ("a", "b", "c"):
        ET.SubElement(act, "position", name=f"act_mms_{ax_char}", joint=f"mms_j_{ax_char}", kp="120")
    for ax_char in ("x", "y", "z"):
        ET.SubElement(act, "position", name=f"act_mms_ee_{ax_char}", joint=f"mms_ee_x" if ax_char == "x" else f"mms_ee_{ax_char}", kp="200")

    ET.indent(mj, space="  ")
    xml_str = ET.tostring(mj, encoding="unicode")
    return xml_str, manifest
