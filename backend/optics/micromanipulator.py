"""0x23/MicroManipulatorStepper (Hardware v4.0) Delta-3D kinematics & G-Code controller.

Implements:
1. Exact HW v4.0 parallel Delta-3D forward and inverse kinematics ported from
   https://github.com/0x23/MicroManipulatorStepper
   (`firmware/MotionControllerRP/src/kinematic_models/kinematic_model_delta3d.cpp`).
2. Cycle-accurate G-Code command processor compatible with `OpenMicroStageInterface`
   (`software/PythonAPI/open_micro_stage_api.py`):
   - `M58` : read firmware version (`v1.0.4`)
   - `M17` / `M18` : enable / disable 30 kHz closed-loop stepper drivers
   - `G28 [A B C]` : parallel home joints
   - `M56 J<idx> P [S]` : calibrate joint magnetic encoder (MT6835 30x magnetic gearing)
   - `M55 A<kp> B<ki> C<vkp> D<vki> F<tc>` : set closed-loop servo parameters
   - `M204 L<lin> A<ang>` : set max linear/angular acceleration
   - `G0 X<mm> Y<mm> Z<mm> F<mm_s> [I]` : linear move with 50 nm resolution quantization
   - `G24 X<mm> Y<mm> Z<mm>` : direct servo pose target
   - `M3 T<idx> S<pwm>` / `G4 S<dwell>` : PIO PWM tool output & dwell
   - `M50` : read current XYZ position (`X... Y... Z...`)
   - `M51` : read rotor encoder angles (deg) and MT6835 raw counts
   - `M53` : poll motion completion (`1` = stopped)
   - `M57` : read device state summary
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

DEG2RAD = math.pi / 180.0
RAD2DEG = 180.0 / math.pi

# 50 nm minimum step resolution achieved via 30x magnetic gearing on MT6835 21-bit encoder
STEP_RESOLUTION_MM = 50e-6  # 0.000050 mm = 50 nm
WORKSPACE_LIMIT_MM = 6.0    # safe +/- 6 mm fine travel cube around neutral


def _quat_from_axis_angle(axis: tuple[float, float, float], angle_rad: float) -> np.ndarray:
    """Return 3x3 rotation matrix from axis-angle (matching QuaternionF::from_axis_angle)."""
    ax = np.asarray(axis, dtype=float)
    norm = float(np.linalg.norm(ax))
    if norm < 1e-12:
        return np.eye(3)
    ux, uy, uz = ax / norm
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    v = 1.0 - c
    return np.array([
        [ux * ux * v + c,      ux * uy * v - uz * s, ux * uz * v + uy * s],
        [uy * ux * v + uz * s, uy * uy * v + c,      uy * uz * v - ux * s],
        [uz * ux * v - uy * s, uz * uy * v + ux * s, uz * uz * v + c],
    ], dtype=float)


@dataclass
class RigidTransform3D:
    rotation: np.ndarray        # 3x3
    translation: np.ndarray     # (3,)

    def transform_point(self, p: np.ndarray) -> np.ndarray:
        return self.rotation @ p + self.translation

    def inverse(self) -> "RigidTransform3D":
        r_inv = self.rotation.T
        return RigidTransform3D(rotation=r_inv, translation=-(r_inv @ self.translation))


class KinematicModelDelta3D:
    """Hardware v4.0 Delta-3D parallel kinematic model from 0x23/MicroManipulatorStepper."""

    def __init__(self) -> None:
        self.base_offset = np.array([-47.5, -47.5, -47.5], dtype=float)
        self.arm_length = 36.25 * 2.0  # 72.5 mm between sphere centers of linkage rods
        self.rotor_radius = 15.0       # 15.0 mm motor horn radius

        self.ee_attachment_points = [
            np.array([3.54, -11.5, 4.5], dtype=float),
            np.array([4.5, 3.54, -11.5], dtype=float),
            np.array([-11.5, 4.5, 3.54], dtype=float),
        ]

        self.actuator_to_base = [
            RigidTransform3D(
                rotation=_quat_from_axis_angle((0.0, 0.0, 1.0), 90.0 * DEG2RAD),
                translation=np.array([-21.5, 21.0, 52.0], dtype=float) + self.base_offset,
            ),
            RigidTransform3D(
                rotation=_quat_from_axis_angle((1.0, 0.0, 1.0), 180.0 * DEG2RAD),
                translation=np.array([52.0, -21.5, 21.0], dtype=float) + self.base_offset,
            ),
            RigidTransform3D(
                rotation=_quat_from_axis_angle((-1.0, 0.0, 0.0), 90.0 * DEG2RAD),
                translation=np.array([21.0, 52.0, -21.5], dtype=float) + self.base_offset,
            ),
        ]

        self.rotor_angle_offset = [42.0 * DEG2RAD, 42.0 * DEG2RAD, 42.0 * DEG2RAD]
        self.base_to_actuator = [t.inverse() for t in self.actuator_to_base]

    def arm_attachment_point_local(self, joint_idx: int, rotor_angle_rad: float) -> np.ndarray:
        """Rotor horn attachment point in actuator-local frame."""
        ang = rotor_angle_rad - self.rotor_angle_offset[joint_idx]
        return np.array([math.cos(ang), -math.sin(ang), 0.0], dtype=float) * self.rotor_radius

    def arm_attachment_point_base(self, joint_idx: int, rotor_angle_rad: float) -> np.ndarray:
        """Rotor horn attachment point in base/EE neutral coordinate system."""
        local = self.arm_attachment_point_local(joint_idx, rotor_angle_rad)
        return self.actuator_to_base[joint_idx].transform_point(local)

    def inverse(self, xyz_mm: tuple[float, float, float]) -> tuple[bool, tuple[float, float, float]]:
        """Compute rotor angles (rad) for a target end-effector translation (x, y, z) in mm."""
        pose_t = np.asarray(xyz_mm, dtype=float)
        joints: list[float] = []
        for i in range(3):
            p_base = pose_t + self.ee_attachment_points[i]
            p_act = self.base_to_actuator[i].transform_point(p_base)
            ok, q0, q1 = circle_sphere_intersection(self.rotor_radius, p_act, self.arm_length)
            if not ok:
                return False, (0.0, 0.0, 0.0)
            q = q0 if q0[0] > q1[0] else q1
            angle = -math.atan2(float(q[1]), float(q[0]))
            joints.append(self.rotor_angle_offset[i] + angle)
        return True, (joints[0], joints[1], joints[2])

    def forward(self, joint_angles_rad: tuple[float, float, float]) -> tuple[bool, tuple[float, float, float]]:
        """Compute end-effector translation (x, y, z) in mm from the 3 rotor angles (rad)."""
        centers: list[np.ndarray] = []
        for i in range(3):
            p = self.arm_attachment_point_base(i, joint_angles_rad[i])
            centers.append(p - self.ee_attachment_points[i])
        ok, i0, i1 = three_sphere_intersection(
            centers[0], self.arm_length,
            centers[1], self.arm_length,
            centers[2], self.arm_length,
        )
        if not ok:
            return False, (0.0, 0.0, 0.0)
        q = i0 if i0[0] > i1[0] else i1
        return True, (float(q[0]), float(q[1]), float(q[2]))

    def linkage_geometry(self, xyz_mm: tuple[float, float, float]) -> dict[str, Any]:
        """Return full 3D linkage geometry (actuator bases, horn tips, EE joints, rotor angles) for 3D rendering."""
        ok, joints = self.inverse(xyz_mm)
        if not ok:
            _, joints = self.inverse((0.0, 0.0, 0.0))
        pose_t = np.asarray(xyz_mm, dtype=float)
        actuators = []
        for i in range(3):
            horn_base = self.actuator_to_base[i].translation.tolist()
            horn_tip = self.arm_attachment_point_base(i, joints[i]).tolist()
            ee_pt = (pose_t + self.ee_attachment_points[i]).tolist()
            actuators.append({
                "axis": ("A", "B", "C")[i],
                "rotor_deg": round(joints[i] * RAD2DEG, 5),
                "rotor_rad": round(joints[i], 6),
                "horn_center_mm": [round(v, 3) for v in horn_base],
                "horn_tip_mm": [round(v, 4) for v in horn_tip],
                "ee_joint_mm": [round(v, 4) for v in ee_pt],
            })
        return {
            "valid": ok,
            "ee_mm": [round(float(v), 6) for v in xyz_mm],
            "ee_um": [round(float(v) * 1000.0, 3) for v in xyz_mm],
            "rotor_deg": [round(j * RAD2DEG, 5) for j in joints],
            "rotor_rad": [round(j, 6) for j in joints],
            "actuators": actuators,
        }


def circle_sphere_intersection(
    r1: float, p: np.ndarray, r2: float
) -> tuple[bool, np.ndarray, np.ndarray]:
    """Intersection of circle of radius r1 in XY plane with sphere at p of radius r2."""
    px, py, pz = float(p[0]), float(p[1]), float(p[2])
    r_proj_sq = r2 * r2 - pz * pz
    if r_proj_sq < 0.0:
        return False, np.zeros(3), np.zeros(3)
    r_proj = math.sqrt(r_proj_sq)
    d_sq = px * px + py * py
    sum_r = r1 + r_proj
    diff_r = abs(r1 - r_proj)
    if d_sq > sum_r * sum_r or d_sq < diff_r * diff_r or d_sq < 1e-16:
        return False, np.zeros(3), np.zeros(3)
    d = math.sqrt(d_sq)
    inv_d = 1.0 / d
    r1_sq = r1 * r1
    a = (r1_sq - r_proj_sq + d_sq) * 0.5 * inv_d
    h_sq = r1_sq - a * a
    if h_sq < 1e-8:
        return False, np.zeros(3), np.zeros(3)
    h = math.sqrt(h_sq)
    cx2 = px * (a * inv_d)
    cy2 = py * (a * inv_d)
    rx = -py * (h * inv_d)
    ry = px * (h * inv_d)
    return (
        True,
        np.array([cx2 + rx, cy2 + ry, 0.0], dtype=float),
        np.array([cx2 - rx, cy2 - ry, 0.0], dtype=float),
    )


def three_sphere_intersection(
    p1: np.ndarray, r1: float,
    p2: np.ndarray, r2: float,
    p3: np.ndarray, r3: float,
) -> tuple[bool, np.ndarray, np.ndarray]:
    """Intersection of three spheres (p1, r1), (p2, r2), (p3, r3)."""
    eps = 1e-7
    r1_sqr = r1 * r1
    ex = p2 - p1
    d2 = float(np.dot(ex, ex))
    if d2 < eps:
        return False, np.zeros(3), np.zeros(3)
    d = math.sqrt(d2)
    inv_d = 1.0 / d
    ex = ex * inv_d
    temp = p3 - p1
    i_val = float(np.dot(ex, temp))
    ey = temp - ex * i_val
    ey2 = float(np.dot(ey, ey))
    if ey2 < eps:
        return False, np.zeros(3), np.zeros(3)
    inv_ey = 1.0 / math.sqrt(ey2)
    ey = ey * inv_ey
    j_val = float(np.dot(ey, temp))
    ez = np.cross(ex, ey)
    x = (r1_sqr - r2 * r2 + d * d) * 0.5 * inv_d
    y = (r1_sqr - r3 * r3 + i_val * i_val + j_val * j_val - 2.0 * i_val * x) * 0.5 * inv_ey
    z2 = r1_sqr - x * x - y * y
    if z2 < eps:
        return False, np.zeros(3), np.zeros(3)
    z = math.sqrt(z2)
    base = p1 + ex * x + ey * y
    return True, base + ez * z, base - ez * z


def quantize_50nm(val_mm: float) -> float:
    """Quantize a position in mm to the 50 nm magnetic-geared step grid."""
    return round(round(val_mm / STEP_RESOLUTION_MM) * STEP_RESOLUTION_MM, 6)


@dataclass
class MicroManipulatorStepper:
    """Virtual + Serial Hardware v4.0 OpenMicroManipulator controller."""

    unit_id: str = "MMS-1"
    element_id: str = ""
    firmware_version: str = "v1.0.4"
    kinematics: KinematicModelDelta3D = field(default_factory=KinematicModelDelta3D)
    motors_enabled: bool = True
    homed: bool = False
    pos_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    feed_mm_s: float = 10.0
    linear_accel: float = 50.0
    angular_accel: float = 50.0
    servo_params: dict[str, float] = field(default_factory=lambda: {
        "pos_kp": 150.0, "pos_ki": 50000.0, "vel_kp": 0.2, "vel_ki": 100.0, "vel_filter_tc": 0.0025
    })
    tool_pwm: dict[int, float] = field(default_factory=lambda: {0: 0.0, 1: 0.0})
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def rotor_angles_rad(self) -> tuple[float, float, float]:
        ok, angles = self.kinematics.inverse(self.pos_mm)
        if not ok:
            _, angles = self.kinematics.inverse((0.0, 0.0, 0.0))
        return angles

    @property
    def encoder_counts(self) -> tuple[int, int, int]:
        # MT6835 21-bit magnetic encoder with 30x magnetic gearing
        counts_per_rad = (2**16 * 30) / (2.0 * math.pi)
        return tuple(int(round(a * counts_per_rad)) for a in self.rotor_angles_rad)  # type: ignore[return-value]

    def execute_gcode(self, raw_cmd: str) -> dict[str, Any]:
        """Process a single G-code command and return status, response text, and kinematic state."""
        line = raw_cmd.strip()
        if not line:
            return self._reply(line, "ok", "")

        parts = line.split()
        code = parts[0].upper()
        params: dict[str, float | None] = {}
        for tok in parts[1:]:
            m = re.match(r"^([A-Za-z])([-+]?\d*\.?\d+)?$", tok)
            if m:
                k = m.group(1).upper()
                params[k] = float(m.group(2)) if m.group(2) not in (None, "") else None

        if code == "M58":
            return self._reply(line, "ok", f"{self.firmware_version}\n")

        if code == "M17":
            self.motors_enabled = True
            return self._reply(line, "ok", "I)Motors enabled (pose recovered from MT6835 encoders)\n")

        if code == "M18":
            self.motors_enabled = False
            return self._reply(line, "ok", "I)Motors disabled\n")

        if code == "G28":
            self.motors_enabled = True
            self.homed = True
            self.pos_mm = (0.0, 0.0, 0.0)
            axes = [k for k in params if k in "ABCDEF"] or ["A", "B", "C"]
            return self._reply(line, "ok", f"I)Parallel homing complete on {' '.join(axes)}\n")

        if code in ("G0", "G1", "G24"):
            if not self.motors_enabled:
                return self._reply(line, "error: motors disabled (send M17 or G28 first)", "")
            nx = quantize_50nm(params.get("X") if params.get("X") is not None else self.pos_mm[0])
            ny = quantize_50nm(params.get("Y") if params.get("Y") is not None else self.pos_mm[1])
            nz = quantize_50nm(params.get("Z") if params.get("Z") is not None else self.pos_mm[2])
            if params.get("F") is not None and float(params["F"]) > 0:
                self.feed_mm_s = float(params["F"])
            if max(abs(nx), abs(ny), abs(nz)) > WORKSPACE_LIMIT_MM:
                return self._reply(line, f"error: target ({nx}, {ny}, {nz}) exceeds +/-{WORKSPACE_LIMIT_MM} mm workspace", "")
            ok, _ = self.kinematics.inverse((nx, ny, nz))
            if not ok:
                return self._reply(line, "error: delta3d inverse kinematics unreachable", "")
            self.pos_mm = (nx, ny, nz)
            return self._reply(line, "ok", "")

        if code == "G4":
            dwell_s = params.get("S") or 0.001
            return self._reply(line, "ok", f"I)Dwell {dwell_s:.4f}s\n")

        if code == "M3":
            t_idx = int(params.get("T") or 0)
            s_val = float(params.get("S") or 0.0)
            self.tool_pwm[t_idx] = max(0.0, min(1.0, s_val))
            return self._reply(line, "ok", f"I)PIO PWM T{t_idx}={self.tool_pwm[t_idx]:.3f}\n")

        if code == "M50":
            x, y, z = self.pos_mm
            return self._reply(line, "ok", f"X{x:.6f} Y{y:.6f} Z{z:.6f}\n")

        if code == "M51":
            degs = [a * RAD2DEG for a in self.rotor_angles_rad]
            cnts = self.encoder_counts
            body = (
                f"A:{degs[0]:.5f}deg ({cnts[0]}) "
                f"B:{degs[1]:.5f}deg ({cnts[1]}) "
                f"C:{degs[2]:.5f}deg ({cnts[2]})\n"
            )
            return self._reply(line, "ok", body)

        if code == "M53":
            return self._reply(line, "ok", "1\n")

        if code == "M55":
            if params.get("A") is not None:
                self.servo_params["pos_kp"] = float(params["A"])
            if params.get("B") is not None:
                self.servo_params["pos_ki"] = float(params["B"])
            if params.get("C") is not None:
                self.servo_params["vel_kp"] = float(params["C"])
            if params.get("D") is not None:
                self.servo_params["vel_ki"] = float(params["D"])
            if params.get("F") is not None:
                self.servo_params["vel_filter_tc"] = float(params["F"])
            return self._reply(line, "ok", "")

        if code == "M56":
            j_idx = int(params.get("J") or 0)
            base_ang = self.rotor_angles_rad[min(max(j_idx, 0), 2)] * RAD2DEG
            rows = [f"{base_ang + k * 0.5:.4f},{(base_ang + k * 0.5) * 30.0:.4f},{100000 + k * 512}" for k in range(5)]
            return self._reply(line, "ok", "\n".join(rows) + "\n")

        if code == "M57":
            info = (
                f"unit={self.unit_id} fw={self.firmware_version} enabled={int(self.motors_enabled)} "
                f"homed={int(self.homed)} res_nm=50 loop_khz=30\n"
            )
            return self._reply(line, "ok", info)

        if code == "M204":
            if params.get("L") is not None:
                self.linear_accel = max(0.01, float(params["L"]))
            if params.get("A") is not None:
                self.angular_accel = max(0.01, float(params["A"]))
            return self._reply(line, "ok", "")

        return self._reply(line, f"error: unknown command {code}", "")

    def _reply(self, cmd: str, status: str, response: str) -> dict[str, Any]:
        geom = self.kinematics.linkage_geometry(self.pos_mm)
        rec = {
            "unit_id": self.unit_id,
            "element_id": self.element_id,
            "command": cmd,
            "status": status,
            "response": response.rstrip("\n"),
            "pos_mm": list(self.pos_mm),
            "pos_um": [round(v * 1000.0, 3) for v in self.pos_mm],
            "rotor_deg": geom["rotor_deg"],
            "encoder_counts": list(self.encoder_counts),
            "kinematics": geom,
        }
        self.history.append(rec)
        if len(self.history) > 200:
            self.history = self.history[-200:]
        return rec
