"""Argon (`gemini-4-argon`) Autonomous Optics Lab Controller & FastAPI routes.

Orchestrates the self-running automated optics laboratory:
1. Workcell Planning (`lab-director` using `gemini-4-argon` with deterministic fallback):
   - Audits the `Design` against the motorized X/Y inventory crib slots.
   - Plans safe assembly order, pilot laser interlock power, and `0x23/MicroManipulatorStepper`
     Delta-3D fine alignment targets.
2. Robotic Construction (`crib-xy-stage` + `arm-6dof`):
   - Commands the 2-axis motorized X/Y presentation stage (`crib_x`, `crib_y`) to index each
     component pocket to the calibrated Pick Station `(pick_x, pick_y)`.
   - Commands the 6-DOF robot arm (`arm_j1..j6` + parallel gripper) through IK trajectories
     (`pre_pick` -> `pick` -> `lift` -> `pre_place` -> `place` -> `retract`).
   - Re-traces the optical bench as each component is physically seated on the breadboard
     (with realistic as-built placement tolerances), so the laser beam propagates step-by-step.
3. Sub-Micrometer Alignment (`mms-aligner` via `0x23/MicroManipulatorStepper` G-Code):
   - Homes (`G28 A B C`), enables 30 kHz closed-loop servos (`M17`, `M55`), and steps the
     3-DOF Delta-3D manipulators (`G0 X... Y... Z... F...`, `M50`, `M51`) in a closed-loop
     power-meter feedback loop until the bench reaches peak optical alignment (`PASS`).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from optics.ir import Design
from optics.micromanipulator import MicroManipulatorStepper, quantize_50nm
from optics.mujoco_lab import build_lab_mjcf, forward_arm_fk
from optics.trace import trace
from optics.tune import detune, tune
from optics.verify import verify

from . import events, llm

router = APIRouter()
Emit = Callable[[dict[str, Any]], Awaitable[None]]

# Persistent virtual MicroManipulatorStepper units keyed by unit_id for interactive G-code
_MMS_UNITS: dict[str, MicroManipulatorStepper] = {}


def get_mms_unit(unit_id: str, element_id: str = "") -> MicroManipulatorStepper:
    if unit_id not in _MMS_UNITS:
        _MMS_UNITS[unit_id] = MicroManipulatorStepper(unit_id=unit_id, element_id=element_id)
    elif element_id and not _MMS_UNITS[unit_id].element_id:
        _MMS_UNITS[unit_id].element_id = element_id
    return _MMS_UNITS[unit_id]


class LabMjcfBody(BaseModel):
    design: Design


class LabGcodeBody(BaseModel):
    unit_id: str = "MMS-1"
    element_id: str = ""
    commands: list[str]


class LabRunBody(BaseModel):
    design: Design
    use_llm: bool = True
    pace_ms: float = 45.0


class LabPlanSchema(BaseModel):
    workcell_summary: str = Field(description="Concise summary of the robotic assembly and alignment plan")
    safety_protocol: str = Field(description="Laser interlock & stray-beam containment protocol during assembly")
    assembly_notes: list[str] = Field(default_factory=list, description="Per-stage notes for X/Y crib presentation and 6-DOF pick-and-place")
    mms_alignment_strategy: str = Field(description="Closed-loop sub-micrometer alignment strategy using 0x23/MicroManipulatorStepper G-code")


def _field_to_mms_xyz_mm(field: str, delta_val: float) -> tuple[float, float, float]:
    """Map an optical knob adjustment (`fast_axis_deg`, `distance_mm`, `out_direction_deg`, `angle_deg`, `focal_length_mm`)
    to a physical sub-millimetre (X, Y, Z) displacement on the 0x23/MicroManipulatorStepper Delta-3D stage."""
    if field == "distance_mm":
        return (quantize_50nm(max(-4.5, min(4.5, delta_val * 0.35))), 0.0, 0.0)
    if field in ("out_direction_deg", "angle_deg"):
        # 1 deg mirror tilt corresponds to ~0.44 mm linear actuator push at 25 mm lever arm
        return (0.0, quantize_50nm(max(-4.5, min(4.5, delta_val * 0.44))), quantize_50nm(delta_val * 0.12))
    if field == "fast_axis_deg":
        # Tangential worm/flexure drive coupled to waveplate rotation ring
        rad = delta_val * 0.0174533
        return (quantize_50nm(max(-4.5, min(4.5, 2.2 * rad))), quantize_50nm(max(-4.5, min(4.5, 0.8 * rad))), 0.0)
    if field == "focal_length_mm":
        return (0.0, 0.0, quantize_50nm(max(-4.5, min(4.5, delta_val * 0.25))))
    return (quantize_50nm(max(-4.5, min(4.5, delta_val))), 0.0, 0.0)


async def run_autonomous_lab(
    design: Design,
    emit: Emit,
    *,
    use_llm: bool = True,
    pace_ms: float = 45.0,
) -> Design:
    """Execute the full Argon-controlled robotic optics lab construction and alignment loop."""
    tracker = events.AgentTracker(emit, model=llm.MODEL)
    step_delay = max(0.0, min(pace_ms, 500.0)) / 1000.0

    # 1. Generate MuJoCo MJCF model and crib/arm/MMS manifest
    t_mj = time.perf_counter()
    mjcf_xml, manifest = build_lab_mjcf(design)
    mj_ms = (time.perf_counter() - t_mj) * 1000.0
    slots = manifest["slots"]

    # Create as-built (slightly detuned) version of the design to simulate real mechanical seating tolerances
    as_built_full = detune(design, seed=7)
    as_built_by_id = {e.id: e for e in as_built_full.elements}

    await emit({
        "type": "lab_init",
        "mjcf_xml": mjcf_xml,
        "manifest": manifest,
        "design": design.model_dump(mode="json"),
    })

    # 2. Phase 1: Argon Lab Director Agent plans the robotic build & alignment
    plan_summary = (
        f"Index {len(slots)} optics on motorized X/Y crib stage to pick station "
        f"({manifest['pick_station_xy_mm'][0]}, {manifest['pick_station_xy_mm'][1]}) mm; "
        f"assemble with 6-DOF arm under 5% pilot laser interlock; align tunable mounts with "
        f"0x23/MicroManipulatorStepper (HW v4.0 Delta-3D, 50 nm resolution, 30 kHz loop)."
    )
    async with tracker.agent(
        "lab-director", "architect", "Argon Lab Director · Workcell Plan",
        thinking_level="low" if use_llm else None,
    ) as director:
        await tracker.tool("lab-director", "mujoco_mjcf", f"{len(slots)} crib slots · MJCF built", mj_ms)
        if use_llm:
            prompt = (
                f"You are the Argon Autonomous Optics Lab Controller for BEAMTEAM.\n"
                f"Design: {design.name} ({design.description})\n"
                f"Baseplate: {design.baseplate.width_mm}x{design.baseplate.height_mm} mm\n"
                f"Inventory crib slots ({len(slots)} parts on motorized X/Y presentation stage): "
                + ", ".join(f"{s['element_id']}:{s['type']}->({s['bench_xy_mm'][0]},{s['bench_xy_mm'][1]})mm" for s in slots)
                + "\nProduce a brief robotic execution plan covering: "
                "(1) motorized X/Y crib presentation to pick station, "
                "(2) 6-DOF arm pick-and-place onto dowel-pinned baseplate under pilot laser safety interlock, and "
                "(3) closed-loop sub-micrometer alignment using 0x23/MicroManipulatorStepper G-code (G28, G0, M50)."
            )
            try:
                llm_plan = await asyncio.wait_for(
                    llm.generate_model(
                        prompt, LabPlanSchema,
                        system="Concise robotics & laser-optics workcell controller. Return valid JSON.",
                        thinking="low", temperature=0.4, max_output_tokens=4096,
                        timeout=12.0, retries=0, tag="lab_director",
                    ),
                    timeout=13.0,
                )
                plan_summary = llm_plan.workcell_summary
                await emit({
                    "type": "thought",
                    "agent_id": "lab-director",
                    "text": f"{llm_plan.workcell_summary} | Safety: {llm_plan.safety_protocol} | MMS: {llm_plan.mms_alignment_strategy}",
                })
            except Exception as exc:
                await emit({
                    "type": "thought",
                    "agent_id": "lab-director",
                    "text": f"Using deterministic workcell plan ({type(exc).__name__}): {plan_summary}",
                })
        else:
            await emit({"type": "thought", "agent_id": "lab-director", "text": plan_summary})

    await emit({
        "type": "status",
        "stage": "plan",
        "message": f"Lab Director: {plan_summary}",
    })

    # 3. Phase 2: Motorized X/Y Crib Presentation + 6-DOF Arm Pick-and-Place Construction
    placed_ids: list[str] = []
    async with tracker.agent(
        "arm-6dof", "designer", "6-DOF Arm + X/Y Crib Stage · Assembly",
        parent="lab-director", thinking_level=None,
    ) as builder:
        for idx, slot in enumerate(slots):
            eid = slot["element_id"]
            stage_xy = slot["stage_present_xy_mm"]
            kf = slot["ik_keyframes"]

            # 3a. Index motorized X/Y crib stage so part pocket arrives at Pick Station
            await emit({
                "type": "lab_stage",
                "slot_index": idx,
                "element_id": eid,
                "part_type": slot["type"],
                "stage_xy_mm": stage_xy,
                "pick_station_xy_mm": slot["pick_station_xy_mm"],
                "message": f"X/Y crib stage indexing slot #{idx} ({eid}: {slot['type']}) to pick station ({stage_xy[0]:+.1f}, {stage_xy[1]:+.1f}) mm",
            })
            if step_delay:
                await asyncio.sleep(step_delay * 0.9)

            # 3b. Step 6-DOF robot arm through pick-and-place keyframes
            arm_phases = [
                ("pre_pick", kf["pre_pick"], 0.012, "in_crib", f"Arm slewing to pick station above {eid}"),
                ("pick", kf["pick"], 0.002, "carried", f"Gripper closing on {eid} ({slot['type']})"),
                ("lift", kf["lift"], 0.002, "carried", f"Lifting {eid} from X/Y presentation crib"),
                ("pre_place", kf["pre_place"], 0.002, "carried", f"Transferring {eid} to bench ({slot['bench_xy_mm'][0]:.1f}, {slot['bench_xy_mm'][1]:.1f}) mm"),
                ("place", kf["place"], 0.012, "placed", f"Seating {eid} onto Ø2mm dowel pins at {slot['bench_angle_deg']:.1f}°"),
                ("retract", kf["retract"], 0.012, "placed", f"Released {eid}; arm retracting"),
            ]
            for phase_name, q_joints, grip_open_m, part_state, msg in arm_phases:
                fk = forward_arm_fk(q_joints)
                await emit({
                    "type": "lab_arm",
                    "slot_index": idx,
                    "element_id": eid,
                    "phase": phase_name,
                    "arm_q_rad": q_joints,
                    "gripper_m": grip_open_m,
                    "stage_xy_mm": stage_xy,
                    "part_state": part_state,
                    "fk": fk,
                    "message": msg,
                })
                if step_delay:
                    await asyncio.sleep(step_delay * 0.75)

            # 3c. Part is now seated on the breadboard: trace the partial bench!
            placed_ids.append(eid)
            partial_elements = [as_built_by_id.get(pid, next(e for e in design.elements if e.id == pid)) for pid in placed_ids]
            partial_design = design.model_copy(deep=True)
            partial_design.elements = [e.model_copy(deep=True) for e in partial_elements]
            t0 = time.perf_counter()
            partial_tr = trace(partial_design)
            partial_rep = verify(partial_design, partial_tr)
            tr_ms = (time.perf_counter() - t0) * 1000.0

            await tracker.tool(
                "arm-6dof", "trace",
                f"placed {len(placed_ids)}/{len(slots)} ({eid}) -> {len(partial_tr.segments)} beams, {partial_rep.metrics.get('delivered_mw', 0.0):.2f} mW",
                tr_ms,
            )
            await emit({
                "type": "lab_place",
                "slot_index": idx,
                "element_id": eid,
                "placed_ids": list(placed_ids),
                "total_parts": len(slots),
                "design": partial_design.model_dump(mode="json"),
                "trace": partial_tr.model_dump(mode="json"),
                "report": partial_rep.model_dump(mode="json"),
            })


    # 4. Phase 3: Closed-Loop Fine Alignment via 0x23/MicroManipulatorStepper (HW v4.0 Delta-3D)
    async with tracker.agent(
        "mms-aligner", "repair", "0x23/MicroManipulatorStepper · Closed-Loop Align",
        parent="lab-director", thinking_level=None,
    ) as aligner:
        # Initialize & home primary MMS controller
        mms_boot = get_mms_unit("MMS-MAIN", element_id="bench")
        for init_cmd in ("M58", "M17", "G28 A B C", "M55 A150.000000 B50000.000000 C0.200000 D100.000000 F0.002500"):
            rec = mms_boot.execute_gcode(init_cmd)
            await emit({
                "type": "lab_mms",
                "phase": "boot",
                "gcode": rec,
                "message": f"[MMS-MAIN] {rec['command']} -> {rec['response'] or rec['status']}",
            })

        # Run coordinate-ascent optical alignment and translate each knob step into 0x23/MicroManipulatorStepper G-code
        baseline_vals: dict[tuple[str, str], float] = {}
        for el in as_built_full.elements:
            for f_name in ("fast_axis_deg", "distance_mm", "out_direction_deg", "angle_deg", "focal_length_mm", "split_ratio"):
                v = getattr(el, f_name, None)
                if v is not None:
                    baseline_vals[(el.id, f_name)] = float(v)

        mms_steps = 0

        async def on_tune_event(ev: dict[str, Any]) -> None:
            nonlocal mms_steps
            etype = ev.get("type")
            if etype == "tune_start":
                await emit(ev)
                return
            if etype == "tune_step":
                eid = str(ev["element_id"])
                field = str(ev["field"])
                val = float(ev["value"])
                base_v = baseline_vals.get((eid, field), val)
                delta_v = val - base_v
                tx, ty, tz = _field_to_mms_xyz_mm(field, delta_v)
                unit = get_mms_unit(f"MMS-{eid}", element_id=eid)
                if not unit.homed:
                    unit.execute_gcode("G28 A B C")
                gcode_str = f"G0 X{tx:.6f} Y{ty:.6f} Z{tz:.6f} F12.000"
                rec = unit.execute_gcode(gcode_str)
                mms_steps += 1
                await emit({
                    "type": "lab_mms",
                    "phase": "step",
                    "element_id": eid,
                    "field": field,
                    "value": val,
                    "best_so_far": bool(ev.get("best_so_far")),
                    "metrics": ev.get("metrics", {}),
                    "patch": ev.get("patch", {}),
                    "gcode": rec,
                    "message": f"[MMS-{eid}] {gcode_str} -> rotors ({rec['rotor_deg'][0]:.1f}°, {rec['rotor_deg'][1]:.1f}°, {rec['rotor_deg'][2]:.1f}°) | P={ev.get('metrics', {}).get('delivered_mw', 0.0):.2f} mW",
                })
                await emit(ev)
                if step_delay:
                    await asyncio.sleep(step_delay * 0.45)
                return
            if etype == "tune_done":
                eid = str(ev["element_id"])
                field = str(ev["field"])
                from_val = ev.get("from")
                to_val = ev.get("to")
                if to_val is not None and to_val != from_val:
                    base_v = baseline_vals.get((eid, field), float(from_val if from_val is not None else to_val))
                    tx, ty, tz = _field_to_mms_xyz_mm(field, float(to_val) - base_v)
                    unit = get_mms_unit(f"MMS-{eid}", element_id=eid)
                    unit.execute_gcode(f"G0 X{tx:.6f} Y{ty:.6f} Z{tz:.6f} F8.000")
                    m50 = unit.execute_gcode("M50")
                    await emit({
                        "type": "lab_mms",
                        "phase": "lock",
                        "element_id": eid,
                        "field": field,
                        "gcode": m50,
                        "message": f"[MMS-{eid}] Locked {field}={float(to_val):.3f} ({m50['response']})",
                    })
                await emit(ev)
                return
            if etype == "final":
                final_d: Design = ev["design"]
                final_tr = ev["trace"]
                final_rep = ev["report"]
                summary = ev.get("summary", {})
                await tracker.tool(
                    "mms-aligner", "scale",
                    f"{mms_steps} G-code moves -> {final_rep.metrics.get('delivered_mw', 0.0):.2f} mW (score {final_rep.score:.1f})",
                    0.0,
                )
                await emit({
                    "type": "lab_done",
                    "design": final_d.model_dump(mode="json"),
                    "trace": final_tr.model_dump(mode="json"),
                    "report": final_rep.model_dump(mode="json"),
                    "summary": {**summary, "mms_gcode_moves": mms_steps, "parts_assembled": len(placed_ids)},
                })
                await emit({
                    "type": "final",
                    "design": final_d.model_dump(mode="json"),
                    "trace": final_tr.model_dump(mode="json"),
                    "report": final_rep.model_dump(mode="json"),
                    "summary": summary,
                })

        tuned_design = await tune(as_built_full, on_tune_event, objective="auto", pace_ms=0.0)

    return tuned_design


@router.post("/api/lab/mjcf")
def lab_mjcf_endpoint(body: LabMjcfBody) -> dict[str, Any]:
    xml_str, manifest = build_lab_mjcf(body.design)
    return {"xml": xml_str, "manifest": manifest}


@router.post("/api/lab/gcode")
def lab_gcode_endpoint(body: LabGcodeBody) -> dict[str, Any]:
    unit = get_mms_unit(body.unit_id, element_id=body.element_id)
    results = [unit.execute_gcode(cmd) for cmd in body.commands]
    return {
        "unit_id": unit.unit_id,
        "element_id": unit.element_id,
        "firmware_version": unit.firmware_version,
        "motors_enabled": unit.motors_enabled,
        "homed": unit.homed,
        "pos_mm": list(unit.pos_mm),
        "pos_um": [round(v * 1000.0, 3) for v in unit.pos_mm],
        "rotor_deg": results[-1]["rotor_deg"] if results else [42.0, 42.0, 42.0],
        "encoder_counts": list(unit.encoder_counts),
        "kinematics": unit.kinematics.linkage_geometry(unit.pos_mm),
        "results": results,
    }


@router.post("/api/lab/run")
async def lab_run_endpoint(body: LabRunBody) -> EventSourceResponse:
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def emit(ev: dict[str, Any]) -> None:
        await queue.put(ev)

    async def runner() -> None:
        try:
            await run_autonomous_lab(body.design, emit, use_llm=body.use_llm, pace_ms=body.pace_ms)
        except Exception as e:
            await queue.put({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            await queue.put(None)

    async def events_gen():
        import json
        task = asyncio.create_task(runner())
        try:
            while (ev := await queue.get()) is not None:
                yield {"data": json.dumps(ev)}
        finally:
            task.cancel()

    return EventSourceResponse(events_gen(), ping=10)
