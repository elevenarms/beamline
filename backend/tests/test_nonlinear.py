"""Nonlinear elements: SOA gain saturation, SFG, saturable absorber, convergence, disabled sources."""
import math

import pytest

from optics.ir import Design
from optics.trace import NL_MAX_ITER, trace
from optics.verify import verify


def mk(sources, elements):
    base = {"position": [80, 100], "direction_deg": 0, "wavelength_nm": 1550, "waist_mm": 0.5,
            "polarization": "H"}
    return Design.model_validate({"name": "nl", "baseplate": {"width_mm": 500, "height_mm": 300},
                                  "sources": [{**base, **s} for s in sources], "elements": elements})


def pd(tr, i="PD"):
    return next(e for e in tr.elements if e.id == i).power_out_mw


def test_soa_gain_saturation_single_beam():
    # self-consistent: G = G0/(1 + P_in/Psat) with P_in = 1 mW, G0 = 15 dB, Psat = 5 mW
    d = mk([{"id": "L", "power_mw": 1.0}],
           [{"id": "S", "type": "soa", "beam": "L", "distance_mm": 50},
            {"id": "PD", "type": "photodiode", "beam": "L", "distance_mm": 50}])
    g = 10 ** 1.5 / (1 + 1.0 / 5.0)
    assert pd(trace(d)) == pytest.approx(g, rel=1e-6)


def test_soa_cross_gain_modulation():
    # a strong co-propagating control beam (separate source, same line) darkens the probe
    def run(ctrl_on):
        d = mk([{"id": "P", "power_mw": 0.5},
                {"id": "C", "power_mw": 20.0, "wavelength_nm": 1310, "position": [200, 230],
                 "direction_deg": -90, "enabled": ctrl_on}],
               [{"id": "DC", "type": "dichroic", "beam": "C", "distance_mm": 130, "out_direction_deg": 0,
                 "cutoff_nm": 1400, "reflect": "below"},
                {"id": "S", "type": "soa", "beam": "P.t", "distance_mm": 50},
                {"id": "DF", "type": "dichroic", "beam": "P.t", "distance_mm": 50, "out_direction_deg": 90,
                 "cutoff_nm": 1400, "reflect": "below"},
                {"id": "BD", "type": "beam_dump", "beam": "C.r.r", "distance_mm": 50},
                {"id": "PD", "type": "photodiode", "beam": "P.t.t", "distance_mm": 50}])
        tr = trace(d)
        assert all(e.placed for e in tr.elements), [e.error for e in tr.elements]
        return pd(tr), tr
    off, _ = run(False)
    on, tr = run(True)
    g0 = 10 ** 1.5
    assert off == pytest.approx(0.5 * g0 / (1 + 0.5 / 5), rel=1e-6)
    assert on == pytest.approx(0.5 * g0 / (1 + 20.5 / 5), rel=1e-6)
    assert on < off / 4


def test_saturable_absorber_curve():
    for p in (0.1, 10.0, 100.0):
        d = mk([{"id": "L", "power_mw": p}],
               [{"id": "SA", "type": "saturable_absorber", "beam": "L", "distance_mm": 50},
                {"id": "PD", "type": "photodiode", "beam": "L", "distance_mm": 50}])
        t = 0.05 + 0.95 * p / (p + 10.0)
        assert pd(trace(d)) == pytest.approx(p * t, rel=1e-6)


def _sfg_design(a_on=True, b_on=True, pa=10.0, pb=10.0):
    return mk([{"id": "A", "power_mw": pa, "wavelength_nm": 1064, "enabled": a_on},
               {"id": "B", "power_mw": pb, "wavelength_nm": 1550, "position": [200, 230],
                "direction_deg": -90, "enabled": b_on}],
              [{"id": "DI", "type": "dichroic", "beam": "A", "distance_mm": 120, "out_direction_deg": -90,
                "cutoff_nm": 1300, "reflect": "above"},
               {"id": "X", "type": "sfg_crystal", "beam": "A.t", "distance_mm": 50},
               {"id": "DO", "type": "dichroic", "beam": "A.t", "distance_mm": 50, "out_direction_deg": 90,
                "cutoff_nm": 800, "reflect": "below"},
               {"id": "PD", "type": "photodiode", "beam": "A.t.sfg.r", "distance_mm": 50},
               {"id": "BD", "type": "beam_dump", "beam": "A.t.t", "distance_mm": 50}])


def test_sfg_power_and_wavelength():
    tr = trace(_sfg_design())
    sfg = [s for s in tr.segments if s.branch == "A.t.sfg"]
    assert len(sfg) == 1
    assert sfg[0].wavelength_nm == pytest.approx(1 / (1 / 1064 + 1 / 1550))
    # low-power limit ~ eta*P1*P2 (0.2 mW); the tanh^2 law gives 0.198 mW here
    assert sfg[0].power_mw == pytest.approx(2.0 * 10 * 10 * 1e-3, rel=0.02)
    assert pd(tr) == pytest.approx(sfg[0].power_mw)
    # energy conservation: residual IR + red = input
    dump = pd(tr, "BD")
    assert dump + pd(tr) == pytest.approx(20.0, rel=1e-6)
    assert verify(_sfg_design(), tr).passed


@pytest.mark.parametrize("a,b", [(0, 0), (0, 1), (1, 0)])
def test_sfg_needs_both(a, b):
    tr = trace(_sfg_design(bool(a), bool(b)))
    assert pd(tr) == 0.0
    assert all(e.placed for e in tr.elements)


def test_shg_only_when_efficiency_set():
    def d(eta):
        x = {"id": "X", "type": "sfg_crystal", "beam": "L", "distance_mm": 50}
        if eta is not None:
            x["nl_efficiency_per_w"] = eta
        return mk([{"id": "L", "power_mw": 100.0, "wavelength_nm": 1064}],
                  [x, {"id": "BD", "type": "beam_dump", "beam": "L", "distance_mm": 50},
                   {"id": "PD", "type": "photodiode", "beam": "L.sfg", "distance_mm": 30}])
    assert not [s for s in trace(d(None)).segments if s.branch == "L.sfg"]
    shg = [s for s in trace(d(1.0)).segments if s.branch == "L.sfg"]
    assert shg and shg[0].wavelength_nm == pytest.approx(532.0)
    assert shg[0].power_mw == pytest.approx(100 * math.tanh(math.sqrt(1.0 * 100 * 1e-3)) ** 2)


def test_disabled_source_placement_is_stable():
    on, off = trace(_sfg_design(True, True)), trace(_sfg_design(True, False))
    for a, b in zip(on.elements, off.elements):
        assert a.placed and b.placed, (a.error, b.error)
        assert a.position == pytest.approx(b.position) and a.angle_deg == pytest.approx(b.angle_deg)
    assert not [s for s in off.segments if s.source_id == "B"]
    assert not [c for c in verify(_sfg_design(True, False), off).checks if c.id == "unplaced"]


def test_converges_and_flags_nonconvergence(monkeypatch):
    tr = trace(_sfg_design())
    assert tr.nonconverged == []
    # force a cap of 1 iteration: an SFG design needs >= 2, so it must be flagged
    import optics.trace as T
    monkeypatch.setattr(T, "NL_MAX_ITER", 1)
    d = _sfg_design()
    tr = T.trace(d)
    assert tr.nonconverged == ["X"]
    assert any(c.id == "nonlinear_convergence" for c in verify(d, tr).checks)
    assert NL_MAX_ITER == 12


def test_cascaded_soas_converge():
    d = mk([{"id": "L", "power_mw": 2.0}],
           [{"id": "S1", "type": "soa", "beam": "L", "distance_mm": 40},
            {"id": "S2", "type": "soa", "beam": "L", "distance_mm": 40},
            {"id": "SA", "type": "saturable_absorber", "beam": "L", "distance_mm": 40},
            {"id": "PD", "type": "photodiode", "beam": "L", "distance_mm": 40}])
    tr = trace(d)
    assert tr.nonconverged == []
    g0 = 10 ** 1.5
    p1 = 2.0 * g0 / (1 + 2.0 / 5)
    p2 = p1 * g0 / (1 + p1 / 5)
    p3 = p2 * (0.05 + 0.95 * p2 / (p2 + 10))
    assert pd(tr) == pytest.approx(p3, rel=1e-6)


def test_sfg_low_power_limit_and_photon_bound():
    from optics.trace import _sfg_power
    lo = 1 / (1 / 1064 + 1 / 1550)
    # low power -> eta P1 P2
    assert _sfg_power(0.1, 1064, 0.1, 1550, lo, 2.0) == pytest.approx(2.0 * 0.01 * 1e-3, rel=1e-4)
    # monotonic and bounded by the weaker photon flux
    q_min = min(100 * 1064, 100 * 1550) / lo
    prev = 0.0
    for eta in (1, 10, 100, 1000, 1e5):
        p = _sfg_power(100, 1064, 100, 1550, lo, eta)
        assert prev < p <= q_min
        prev = p
    assert prev == pytest.approx(q_min, rel=1e-6)


def test_sfg_strong_depletion_energy_conserved():
    # matched photon fluxes, high-efficiency waveguide: both inputs mostly depleted
    pb = 150.0
    pa = pb * 1550 / 1064
    d = _sfg_design(pa=pa, pb=pb)
    for e in d.elements:
        if e.id == "X":
            e.nl_efficiency_per_w = 50.0
    tr = trace(d)
    assert tr.nonconverged == []
    residual, red = pd(tr, "BD"), pd(tr)
    assert residual + red == pytest.approx(pa + pb, rel=1e-6)
    assert residual < 0.08 * (pa + pb)


def test_no_parasitic_shg_in_two_wavelength_crystal():
    # eta set explicitly (enables SHG for single-wavelength crystals), but this crystal is fed
    # 1064 + 1550 when all sources are on -> QPM for SFG only: one input alone makes nothing
    d = _sfg_design(True, False)
    for e in d.elements:
        if e.id == "X":
            e.nl_efficiency_per_w = 50.0
    tr = trace(d)
    assert pd(tr) == 0.0
    assert not [s for s in tr.segments if s.branch.endswith(".sfg")]
