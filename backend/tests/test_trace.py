import json
import math
import pathlib
import time

import pytest

from optics.ir import Design
from optics.trace import trace
from optics.verify import verify


def mk(elements, src=None, targets=(), plate=(400, 300)):
    s = {"id": "L1", "position": [10, 150], "direction_deg": 0, "wavelength_nm": 780,
         "power_mw": 10, "waist_mm": 0.5, "polarization": "H"}
    s.update(src or {})
    return Design.model_validate({"name": "t", "baseplate": {"width_mm": plate[0], "height_mm": plate[1]},
                                  "sources": [s], "elements": list(elements), "targets": list(targets)})


def el(tr, i):
    return next(e for e in tr.elements if e.id == i)


def segs(tr, branch):
    return [s for s in tr.segments if s.branch == branch]


def test_lens_waist_location():
    # collimated 1 mm-radius beam, f = 100 mm -> waist ~100 mm after the lens
    d = mk([{"id": "L", "type": "lens", "beam": "L1", "distance_mm": 50, "focal_length_mm": 100,
             "aperture_mm": 25.4},
            {"id": "BD", "type": "beam_dump", "beam": "L1", "distance_mm": 250}],
           src={"waist_mm": 1.0})
    tr = trace(d)
    after = [s for s in tr.segments if s.start_element == "L"][0]
    assert after.waist_z_mm == pytest.approx(100.0, abs=0.5)
    assert after.w0_mm == pytest.approx(0.78e-3 * 100 / (math.pi * 1.0), rel=0.02)


def test_mirror_out_direction_turns_90():
    d = mk([{"id": "M", "type": "mirror", "beam": "L1", "distance_mm": 50, "out_direction_deg": 90},
            {"id": "BD", "type": "beam_dump", "beam": "L1", "distance_mm": 50}])
    tr = trace(d)
    s1 = tr.segments[1]
    assert s1.direction_deg == pytest.approx(90.0)
    assert el(tr, "M").angle_deg == pytest.approx(135.0)
    assert el(tr, "BD").position == pytest.approx((60.0, 200.0))


def test_pbs_splits_D_5050():
    d = mk([{"id": "P", "type": "pbs", "beam": "L1", "distance_mm": 50},
            {"id": "D1", "type": "beam_dump", "beam": "L1.t", "distance_mm": 50},
            {"id": "D2", "type": "beam_dump", "beam": "L1.r", "distance_mm": 50}], src={"polarization": "D"})
    tr = trace(d)
    t, r = segs(tr, "L1.t")[0], segs(tr, "L1.r")[0]
    assert t.power_mw == pytest.approx(5.0) and r.power_mw == pytest.approx(5.0)
    assert t.polarization_label == "H" and r.polarization_label == "V"
    assert r.direction_deg == pytest.approx(90.0)  # default reflection is +90 (CCW)


def test_pbs_out_direction_minus_90():
    d = mk([{"id": "P", "type": "pbs", "beam": "L1", "distance_mm": 50, "out_direction_deg": -90},
            {"id": "D2", "type": "beam_dump", "beam": "L1.r", "distance_mm": 50}], src={"polarization": "V"})
    tr = trace(d)
    assert segs(tr, "L1.r")[0].direction_deg == pytest.approx(-90.0)
    assert el(tr, "P").angle_deg == pytest.approx(90.0)  # canonical: along 90 reflects to 180 / along 0 to -90


def test_hwp_rotates_H_to_D():
    d = mk([{"id": "W", "type": "half_wave_plate", "beam": "L1", "distance_mm": 30, "fast_axis_deg": 22.5},
            {"id": "BD", "type": "beam_dump", "beam": "L1", "distance_mm": 30}])
    tr = trace(d)
    assert tr.segments[1].polarization_label == "D"


def test_aom_orders():
    d = mk([{"id": "A", "type": "aom", "beam": "L1", "distance_mm": 30, "aom_frequency_mhz": 80},
            {"id": "B0", "type": "beam_dump", "beam": "L1.0", "distance_mm": 300},
            {"id": "B1", "type": "beam_dump", "beam": "L1.+1", "distance_mm": 300}])
    tr = trace(d)
    assert set(tr.branches) >= {"L1.0", "L1.+1"}
    s0, s1 = segs(tr, "L1.0")[0], segs(tr, "L1.+1")[0]
    theta = math.degrees(780e-9 * 80e6 / 4200)
    assert s1.direction_deg == pytest.approx(theta, rel=1e-6)
    assert s0.direction_deg == pytest.approx(0.0)
    assert s1.power_mw == pytest.approx(8.0) and s0.power_mw == pytest.approx(2.0)
    assert s1.freq_shift_mhz == pytest.approx(80.0)


def test_fiber_coupling_mode_matched():
    # w at lens = lambda f / (pi w_f) for f = 11 mm, MFD 5 um
    w = 780e-6 * 11 / (math.pi * 2.5e-3)
    d = mk([{"id": "FC", "type": "fiber_coupler", "beam": "L1", "distance_mm": 100}],
           src={"waist_mm": w, "waist_offset_mm": 100}, targets=[{"element_id": "FC", "kind": "min_coupling", "value": 0.9}])
    tr = trace(d)
    fc = el(tr, "FC")
    assert fc.coupling_efficiency > 0.9
    rep = verify(d, tr)
    assert rep.passed, rep.checks


def test_stray_beam_detected():
    d = mk([{"id": "M", "type": "mirror", "beam": "L1", "distance_mm": 50, "out_direction_deg": 90}])
    rep = verify(d, trace(d))
    assert not rep.passed
    assert any(c.id == "stray_beam" and c.severity == "error" for c in rep.checks)


def test_unplaced_lists_branches():
    d = mk([{"id": "P", "type": "pbs", "beam": "L1", "distance_mm": 50},
            {"id": "X", "type": "lens", "beam": "L1.x", "distance_mm": 50}])
    tr = trace(d)
    x = el(tr, "X")
    assert not x.placed and "L1.t" in x.error and "L1.r" in x.error
    assert any(c.id == "unplaced" for c in verify(d, tr).checks)


def test_double_pass_returns_to_pbs():
    # H -> PBS (t) -> QWP 45 -> retro mirror -> QWP -> V -> PBS reflects onto L1.t.r
    d = mk([{"id": "P", "type": "pbs", "beam": "L1", "distance_mm": 50},
            {"id": "Q", "type": "quarter_wave_plate", "beam": "L1.t", "distance_mm": 30, "fast_axis_deg": 45},
            {"id": "M", "type": "mirror", "beam": "L1.t", "distance_mm": 30, "out_direction_deg": 180},
            {"id": "BD", "type": "beam_dump", "beam": "L1.t.r", "distance_mm": 60}])
    tr = trace(d)
    assert all(e.placed for e in tr.elements), [e.error for e in tr.elements]
    assert len(el(tr, "P").hits) == 2
    ret = segs(tr, "L1.t.r")[0]
    assert ret.power_mw == pytest.approx(10.0, rel=1e-6)
    assert ret.polarization_label == "V"
    assert ret.direction_deg == pytest.approx(-90.0)  # returning beam (180) reflects to 180+90
    assert el(tr, "BD").power_out_mw == pytest.approx(10.0, rel=1e-6)
    assert "L1.t.t" not in tr.branches  # no back-transmitted beam toward the laser
    assert verify(d, tr).passed


def test_clipping_on_iris():
    d = mk([{"id": "I", "type": "iris", "beam": "L1", "distance_mm": 30, "aperture_mm": 1.0},
            {"id": "BD", "type": "beam_dump", "beam": "L1", "distance_mm": 30}])
    rep = verify(d, trace(d))
    assert any(c.id == "clipping" and c.severity == "error" for c in rep.checks)


def test_performance_30_elements():
    els = []
    for i in range(29):
        els.append({"id": f"W{i}", "type": "half_wave_plate", "beam": "L1", "distance_mm": 10, "fast_axis_deg": 0})
    els.append({"id": "BD", "type": "beam_dump", "beam": "L1", "distance_mm": 10})
    d = mk(els)
    trace(d)
    t0 = time.perf_counter()
    for _ in range(10):
        tr = trace(d)
        verify(d, tr)
    assert (time.perf_counter() - t0) / 10 < 0.02


EXAMPLES = sorted((pathlib.Path(__file__).parent.parent / "examples").glob("*.json"))


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_examples_trace(path):
    d = Design.model_validate(json.loads(path.read_text()))
    verify(d, trace(d))  # must not crash
