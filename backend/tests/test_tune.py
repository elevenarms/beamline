"""Deterministic alignment pass: recovers detuned designs, emits contract events, bounded steps."""
import asyncio
from pathlib import Path

import pytest

from optics.ir import Design
from optics.trace import trace
from optics.tune import detune, tune

EX = Path(__file__).resolve().parent.parent / "examples"


def load(name):
    return Design.model_validate_json((EX / f"{name}.json").read_text())


def run(design):
    events = []

    async def emit(ev):
        events.append(ev)
    tuned = asyncio.run(tune(design, emit))
    return tuned, events


def fiber_power(d):
    return sum(e.power_out_mw or 0 for e in trace(d).elements if e.type == "fiber_coupler")


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_detuned_aom_doublepass_recovers(seed):
    orig = load("aom_doublepass_fixed")
    bad = detune(orig, seed)
    assert fiber_power(bad) < 0.9 * fiber_power(orig)    # detune actually misaligns
    tuned, events = run(bad)
    assert fiber_power(tuned) >= 0.95 * fiber_power(orig)
    fin = events[-1]
    assert fin["type"] == "final" and fin["summary"]["steps"] <= 160
    assert fin["summary"]["objective_after"] >= fin["summary"]["objective_before"]


def test_event_shapes():
    _, events = run(detune(load("aom_doublepass_fixed"), 1))
    assert events[0]["type"] == "tune_start"
    assert set(events[0]["baseline"]) == {"objective", "delivered_mw", "score"}
    steps = [e for e in events if e["type"] == "tune_step"]
    assert steps and all(set(e) == {"type", "element_id", "field", "value", "objective", "metrics",
                                    "best_so_far", "patch"} for e in steps)
    assert all(e["patch"] == {e["field"]: e["value"]} for e in steps)
    assert all(set(e["metrics"]) == {"delivered_mw", "coupling", "score"} for e in steps)
    dones = [e for e in events if e["type"] == "tune_done"]
    assert dones and all({"element_id", "field", "from", "to", "gain"} <= set(e) for e in dones)
    assert {"design", "trace", "report", "summary"} <= set(events[-1])
    assert len(steps) == events[-1]["summary"]["steps"]


def test_waveplate_scan_finds_pbs_maximum():
    d = Design.model_validate({
        "name": "wp", "baseplate": {"width_mm": 300, "height_mm": 200},
        "sources": [{"id": "L1", "position": [80, 100], "direction_deg": 0, "wavelength_nm": 780,
                     "power_mw": 10, "polarization": "H"}],
        "elements": [
            {"id": "W", "type": "half_wave_plate", "beam": "L1", "distance_mm": 30, "fast_axis_deg": 30},
            {"id": "P", "type": "pbs", "beam": "L1", "distance_mm": 30},
            {"id": "PD", "type": "photodiode", "beam": "L1.r", "distance_mm": 40},
            {"id": "BD", "type": "beam_dump", "beam": "L1.t", "distance_mm": 40}]})
    tuned, _ = run(d)
    w = next(e for e in tuned.elements if e.id == "W").fast_axis_deg
    assert w == pytest.approx(45.0, abs=1.0)       # H -> V: everything reflected onto the PD
    pd = next(e for e in trace(tuned).elements if e.id == "PD").power_out_mw
    assert pd == pytest.approx(10.0, rel=1e-3)


def test_aligned_design_is_left_alone():
    orig = load("mach_zehnder")
    tuned, events = run(orig)
    assert events[-1]["summary"]["objective_after"] == pytest.approx(events[-1]["summary"]["objective_before"])


def test_detune_keeps_everything_placed():
    for name in ("aom_doublepass_fixed", "rb_sas", "fiber_coupling_telescope"):
        assert all(e.placed for e in trace(detune(load(name), 7)).elements)
