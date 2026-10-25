"""Tests for 0x23/MicroManipulatorStepper Delta-3D kinematics, MuJoCo workcell MJCF, and Argon RoboLab."""
from __future__ import annotations

import json
from pathlib import Path

import mujoco
from fastapi.testclient import TestClient

from optics.ir import Design
from optics.micromanipulator import KinematicModelDelta3D, MicroManipulatorStepper
from optics.mujoco_lab import build_lab_mjcf, forward_arm_fk, solve_arm_ik
from server import app

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _load(name: str = "aom_doublepass_fixed") -> Design:
    return Design.model_validate_json((EXAMPLES / f"{name}.json").read_text())


def test_delta3d_kinematics_roundtrip():
    kin = KinematicModelDelta3D()
    for target in [(0.0, 0.0, 0.0), (1.2, -0.8, 0.5), (-2.1, 1.5, -1.0), (0.00005, -0.00015, 0.00025)]:
        ok_ik, joints = kin.inverse(target)
        assert ok_ik, f"IK failed for {target}"
        ok_fk, recovered = kin.forward(joints)
        assert ok_fk, f"FK failed for {joints}"
        for a, b in zip(target, recovered):
            assert abs(a - b) < 1e-4, f"roundtrip mismatch: {target} vs {recovered}"


def test_micromanipulator_gcode_protocol():
    mms = MicroManipulatorStepper(unit_id="MMS-TEST", element_id="FC1")
    r_ver = mms.execute_gcode("M58")
    assert r_ver["status"] == "ok"
    assert r_ver["response"] == "v1.0.4"

    r_home = mms.execute_gcode("G28 A B C")
    assert r_home["status"] == "ok"
    assert mms.homed is True
    assert mms.pos_mm == (0.0, 0.0, 0.0)

    r_move = mms.execute_gcode("G0 X1.250050 Y-0.450100 Z0.125000 F15.000")
    assert r_move["status"] == "ok"
    assert mms.pos_mm == (1.25005, -0.4501, 0.125)

    r_pos = mms.execute_gcode("M50")
    assert r_pos["response"] == "X1.250050 Y-0.450100 Z0.125000"

    r_enc = mms.execute_gcode("M51")
    assert "A:" in r_enc["response"] and "B:" in r_enc["response"] and "C:" in r_enc["response"]

    r_stop = mms.execute_gcode("M53")
    assert r_stop["response"] == "1"

    r_lim = mms.execute_gcode("G0 X25.0 Y0.0 Z0.0 F10.0")
    assert r_lim["status"].startswith("error:")


def test_arm_ik_and_mujoco_mjcf_compiles_and_steps():
    d = _load("aom_doublepass_fixed")
    xml_str, manifest = build_lab_mjcf(d)
    assert len(manifest["slots"]) == len(d.elements)

    # Compile in real MuJoCo C engine and step physics
    model = mujoco.MjModel.from_xml_string(xml_str)
    data = mujoco.MjData(model)
    assert model.nu >= 14  # 2 crib XY + 6 arm + 2 gripper + 6 MMS

    slot0 = manifest["slots"][0]
    data.ctrl[0] = slot0["stage_present_xy_mm"][0] * 0.001
    data.ctrl[1] = slot0["stage_present_xy_mm"][1] * 0.001
    for j_idx, q_val in enumerate(slot0["ik_keyframes"]["pick"]):
        data.ctrl[2 + j_idx] = q_val

    for _ in range(40):
        mujoco.mj_step(model, data)

    fk = forward_arm_fk(solve_arm_ik((120.0, 65.0, 38.0), 45.0))
    assert fk["tool_yaw_deg"] == 45.0


def test_lab_endpoints_and_sse_run():
    d = _load("mach_zehnder")
    client = TestClient(app)

    r_mj = client.post("/api/lab/mjcf", json={"design": d.model_dump(mode="json")})
    assert r_mj.status_code == 200
    payload = r_mj.json()
    assert "<mujoco" in payload["xml"]
    assert len(payload["manifest"]["slots"]) == len(d.elements)

    r_gc = client.post(
        "/api/lab/gcode",
        json={"unit_id": "MMS-M1", "element_id": "M1", "commands": ["M58", "G28 A B C", "G0 X0.25 Y-0.10 Z0.05 F10", "M50"]},
    )
    assert r_gc.status_code == 200
    gc_data = r_gc.json()
    assert gc_data["homed"] is True
    assert gc_data["pos_mm"] == [0.25, -0.1, 0.05]

    r_run = client.post(
        "/api/lab/run",
        json={"design": d.model_dump(mode="json"), "use_llm": False, "pace_ms": 0.0},
    )
    assert r_run.status_code == 200
    events = [
        json.loads(line[5:].strip())
        for line in r_run.text.splitlines()
        if line.startswith("data:")
    ]
    types = {e["type"] for e in events}
    assert {"lab_init", "lab_stage", "lab_arm", "lab_place", "lab_mms", "lab_done", "final"} <= types
