"""Scale tests: module merging and a ~120-element multi-laser apparatus.

Also the generator for examples/sr_ion_apparatus.json:
    uv run python tests/test_scale.py          # rebuilds the example and prints stats/timing
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from optics.ir import Baseplate, Design, Element, Module, Source, Target  # noqa: E402
from optics.merge import merge_modules, place_design, region_violations  # noqa: E402
from optics.trace import trace  # noqa: E402
from optics.verify import verify  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
EXAMPLES = BACKEND / "examples"
SR_EXAMPLE = EXAMPLES / "sr_ion_apparatus.json"
ROW_H = 180.0


def load(name: str) -> Design:
    return Design.model_validate_json((EXAMPLES / f"{name}.json").read_text())


# ───────────────────────────── block generators ─────────────────────────────

def retune(d: Design, lam: float, name: str | None = None) -> Design:
    """Change a block's wavelength keeping its geometry: AOM f scales as 1/lambda (same Bragg angle),
    fiber MFD scales with lambda (same mode matching)."""
    k = lam / d.sources[0].wavelength_nm
    d = d.model_copy(deep=True)
    d.name = name or f"{d.name}_{lam:g}"
    for s in d.sources:
        s.wavelength_nm = lam
    for e in d.elements:
        if e.type == "aom":
            e.aom_frequency_mhz = round((e.aom_frequency_mhz or 80.0) / k, 2)
        if e.type == "fiber_coupler":
            e.fiber_mfd_um = round((e.fiber_mfd_um or 5.0) * k, 2)
    return d


def fiber_distribution(lam: float, n_taps: int, power_mw: float = 40.0, waist_mm: float = 0.43) -> Design:
    """Fiber launch -> 5% sampler to a monitor PD -> n_taps (lambda/2 + PBS) taps, each reflected down via two
    steering mirrors into a fiber, remainder via two mirrors into a last fiber. Equal power per output."""
    f_fc = 4.6
    mfd = round(2000 * (lam * 1e-6) * f_fc / (math.pi * waist_mm), 2)
    y0 = ROW_H - 35
    width = 200 + 110 * n_taps
    els: list[Element] = []
    main = "L1"

    def E(**kw):
        els.append(Element(**kw))

    E(id="S1", type="sampler", label="5% pickoff", part_number="BSF05-A", beam=main, distance_mm=35,
      split_ratio=0.05, out_direction_deg=270)
    E(id="PD1", type="photodiode", label="Power monitor", part_number="PDA36A2", beam=main + ".r", distance_mm=45)
    main += ".t"
    n_out = n_taps + 1
    for k in range(n_taps):
        r = 1.0 / (n_out - k)
        th = math.degrees(0.5 * math.asin(math.sqrt(r)))
        i = k + 1
        E(id=f"HWP{i}", type="half_wave_plate", label=f"lambda/2 tap {i}", part_number="WPH05M",
          beam=main, distance_mm=40 if k == 0 else 80, fast_axis_deg=round(th, 3))
        E(id=f"PBS{i}", type="pbs", label=f"Tap {i} PBS", part_number="PBS101", beam=main, distance_mm=30,
          out_direction_deg=270)
        tap = main + ".r"
        E(id=f"M{i}a", type="mirror", label=f"Tap {i} steering 1", part_number="BB05-E02", beam=tap,
          distance_mm=45, out_direction_deg=0)
        E(id=f"M{i}b", type="mirror", label=f"Tap {i} steering 2", part_number="BB05-E02", beam=tap,
          distance_mm=40, out_direction_deg=270)
        E(id=f"FC{i}", type="fiber_coupler", label=f"Output fiber {i}", part_number="PAF2-A4A", beam=tap,
          distance_mm=50, focal_length_mm=f_fc, fiber_mfd_um=mfd)
        main += ".t"
    E(id="MZa", type="mirror", label="Last output steering 1", part_number="BB05-E02", beam=main,
      distance_mm=90, out_direction_deg=270)
    E(id="MZb", type="mirror", label="Last output steering 2", part_number="BB05-E02", beam=main,
      distance_mm=45, out_direction_deg=0)
    E(id=f"FC{n_out}", type="fiber_coupler", label=f"Output fiber {n_out}", part_number="PAF2-A4A", beam=main,
      distance_mm=45, focal_length_mm=f_fc, fiber_mfd_um=mfd)
    per = power_mw * 0.95 / n_out
    targets = [Target(element_id=f"FC{i}", kind="min_power_mw", value=round(0.7 * per, 2)) for i in range(1, n_out + 1)]
    return Design(
        name=f"fiber_distribution_{lam:g}nm_{n_out}x",
        description=f"{lam:g} nm fiber distribution: monitor pickoff + {n_out} equal-power PM fiber outputs",
        baseplate=Baseplate(width_mm=width, height_mm=ROW_H),
        sources=[Source(id="L1", label="Fiber launch", part_number="PAF2-A4A", position=(20, y0), direction_deg=0,
                        wavelength_nm=lam, power_mw=power_mw, waist_mm=waist_mm, polarization="H")],
        elements=els, targets=targets)


def compose(name: str, blocks: list[tuple[str, Design]], height: float = ROW_H) -> Design:
    """Lay blocks side by side (left to right, vertically centred) in one module-local Design."""
    sources, elements, targets = [], [], []
    x = 0.0
    for prefix, b in blocks:
        dy = (height - b.baseplate.height_mm) / 2
        s, e, t = place_design(b, prefix, (x, dy), None)
        sources += s
        elements += e
        targets += t
        x += b.baseplate.width_mm
    return Design(name=name, description=" + ".join(b.description.split(".")[0] for _, b in blocks)[:400],
                  baseplate=Baseplate(width_mm=x, height_mm=height),
                  sources=sources, elements=elements, targets=targets)


# ───────────────────────────── Sr-88+ apparatus ─────────────────────────────

def sr_ion_modules() -> list[tuple[str, str, str, Design]]:
    dp, sp, sas, tel = (load("aom_doublepass_fixed"), load("aom_singlepass_pickoff"), load("rb_sas"),
                        load("fiber_coupling_telescope"))
    return [
        ("cooling_422", "422 nm Doppler cooling & detection",
         "S1/2-P1/2 cooling laser: AOM double-pass for frequency/intensity control, then split into "
         "cooling, detection and spare fibers with a power-monitor pickoff.",
         compose("cooling_422", [("dp", retune(dp, 421.7)), ("dist", fiber_distribution(421.7, 2))])),
        ("pi_405", "405 nm photoionization (2nd step)",
         "Commercial 405 nm diode: telescope + fiber coupling to the trap.",
         compose("pi_405", [("fc", retune(tel, 405.0))])),
        ("raman_422", "422 nm Raman / Zeeman qubit beams",
         "Two independently switched AOM single-pass Raman arms with pickoff photodiodes for intensity servo.",
         compose("raman_422", [("arm1", retune(sp, 421.7)), ("arm2", retune(sp, 421.7))])),
        ("pi_461", "461 nm photoionization (1st step) + lock",
         "461 nm ECDL: saturated-absorption reference in a Sr cell, fiber coupled output.",
         compose("pi_461", [("sas", retune(sas, 460.9)), ("fc", retune(tel, 460.9))])),
        ("repump_1092", "1092 nm D3/2 repump",
         "1092 nm repump: AOM single-pass switch with pickoff monitor.",
         compose("repump_1092", [("sw", retune(sp, 1091.8))])),
        ("quench_1033", "1033 nm D5/2 quench",
         "1033 nm quench laser: AOM single-pass switch with pickoff monitor.",
         compose("quench_1033", [("sw", retune(sp, 1033.0))])),
        ("spam_674", "674 nm SPAM / optical qubit",
         "674 nm S1/2-D5/2 laser: AOM double-pass, then split into 4 fiber outputs with monitor.",
         compose("spam_674", [("dp", retune(dp, 674.0)), ("dist", fiber_distribution(674.0, 3))])),
    ]


ROWS = [["cooling_422", "pi_405"], ["raman_422"], ["pi_461"], ["repump_1092", "quench_1033"], ["spam_674"]]


def build_sr_apparatus() -> Design:
    mods = {m[0]: m for m in sr_ion_modules()}
    table = Baseplate(width_mm=1200, height_mm=ROW_H * len(ROWS), grid_mm=25.0)
    parts = []
    for r, row in enumerate(ROWS):
        x = 0.0
        for mid in row:
            _, title, desc, d = mods[mid]
            w = d.baseplate.width_mm
            parts.append((Module(id=mid, title=title, description=desc, region=(x, r * ROW_H, w, ROW_H)), d))
            x += w
            assert x <= table.width_mm, f"row {r} overflows: {x}"
    return merge_modules(
        "sr_ion_apparatus",
        "Sr-88+ trapped-ion laser system (after the PyOpticL sr88_apparatus): 422 nm cooling/detection, 422 nm "
        "Raman qubit beams, 461 + 405 nm photoionization, 1092 nm repump, 1033 nm quench and 674 nm SPAM, "
        "each a fiber-in/fiber-out module on a shared 1200 x 900 mm table.",
        table, parts)


# ───────────────────────────── tests ─────────────────────────────

def _check_merge_equivalence(parts: list[tuple[Module, Design]], merged: Design):
    mtr = trace(merged)
    msegs = {s.id: s for s in mtr.segments}
    mel = {e.id: e for e in mtr.elements}
    # every part traced standalone must match the merged trace, offset by its region origin
    for mod, d in parts:
        ox, oy = mod.region[0], mod.region[1]
        tr = trace(d)
        own = [s for s in mtr.segments if s.source_id.startswith(mod.id + ".")]
        assert len(own) == len(tr.segments), mod.id
        for e in tr.elements:
            me = mel[f"{mod.id}.{e.id}"]
            assert me.placed == e.placed
            if e.position:
                assert math.isclose(me.position[0], e.position[0] + ox, abs_tol=1e-4)
                assert math.isclose(me.position[1], e.position[1] + oy, abs_tol=1e-4)
            assert (me.power_out_mw is None) == (e.power_out_mw is None)
            if e.power_out_mw is not None:
                assert math.isclose(me.power_out_mw, e.power_out_mw, rel_tol=1e-6, abs_tol=1e-9)
            if e.coupling_efficiency is not None:
                assert math.isclose(me.coupling_efficiency, e.coupling_efficiency, rel_tol=1e-6)
        a = sorted((s.branch, round(s.power_mw, 5), round(s.start[0] + ox, 3), round(s.start[1] + oy, 3))
                   for s in tr.segments)
        b = sorted((s.branch[len(mod.id) + 1:], round(s.power_mw, 5), round(s.start[0], 3), round(s.start[1], 3))
                   for s in own)
        assert a == b, mod.id
    assert msegs  # non-empty


def test_merge_two_examples_traces_identically():
    dp, sas = load("aom_doublepass_fixed"), load("rb_sas")
    parts = [(Module(id="a", region=(0, 0, dp.baseplate.width_mm, dp.baseplate.height_mm)), dp),
             (Module(id="b", region=(100, 400, sas.baseplate.width_mm, sas.baseplate.height_mm)), sas)]
    merged = merge_modules("m", "", Baseplate(width_mm=700, height_mm=600), parts)
    assert {s.id for s in merged.sources} == {"a.L1", "b.L1"}
    assert all(e.group in ("a", "b") for e in merged.elements)
    assert any(e.beam == "a.L1.t.+1.+1.r" for e in merged.elements)
    assert any(e.at and math.isclose(e.at[0], 275.006) for e in merged.elements if e.group == "a")
    assert {t.element_id for t in merged.targets} >= {"a.FC1"}
    assert region_violations(merged) == []
    _check_merge_equivalence(parts, merged)
    rep = verify(merged, trace(merged))
    assert rep.passed, [c.message for c in rep.checks if c.severity == "error"]


def test_sr_apparatus_example_up_to_date_and_passes():
    built = build_sr_apparatus()
    stored = Design.model_validate_json(SR_EXAMPLE.read_text())
    assert stored.model_dump() == built.model_dump(), "run `uv run python tests/test_scale.py` to regenerate"
    assert len(stored.modules) >= 6 and 80 <= len(stored.elements) <= 200
    tr = trace(stored)
    rep = verify(stored, tr)
    assert rep.passed, [c.message for c in rep.checks if c.severity == "error"]
    assert not [c for c in rep.checks if c.severity == "warning"]
    assert all(e.placed for e in tr.elements)


def test_sr_apparatus_merge_equivalence():
    mods = {m[0]: m for m in sr_ion_modules()}
    stored = Design.model_validate_json(SR_EXAMPLE.read_text())
    parts = [(m, mods[m.id][3]) for m in stored.modules]
    _check_merge_equivalence(parts, stored)


def test_sr_apparatus_trace_verify_fast():
    d = Design.model_validate_json(SR_EXAMPLE.read_text())
    verify(d, trace(d))  # warm-up
    best = min(_timed(d) for _ in range(3))
    assert best < 1.0, f"trace+verify took {best * 1000:.0f} ms"


def _timed(d: Design) -> float:
    t0 = time.perf_counter()
    verify(d, trace(d))
    return time.perf_counter() - t0


if __name__ == "__main__":
    d = build_sr_apparatus()
    SR_EXAMPLE.write_text(d.model_dump_json(indent=1, exclude_none=True) + "\n")
    t0 = time.perf_counter()
    tr = trace(d)
    t1 = time.perf_counter()
    rep = verify(d, tr)
    t2 = time.perf_counter()
    print(f"wrote {SR_EXAMPLE}: {len(d.modules)} modules, {len(d.sources)} sources, {len(d.elements)} elements, "
          f"{len(tr.segments)} segments, {len(d.targets)} targets")
    print(f"trace {1000 * (t1 - t0):.1f} ms, verify {1000 * (t2 - t1):.1f} ms; passed={rep.passed} "
          f"score={rep.score:.1f}")
    for c in rep.checks:
        if c.severity != "info":
            print(f"  [{c.severity}] {c.id}: {c.message}")
    print("metrics:", {k: round(v, 2) for k, v in rep.metrics.items()})


# ───────────────────────────── hierarchical power budget ─────────────────────────────

def test_power_budget_shared_laser():
    from agents.hierarchical import FiberLink, Laser, ModuleSpec, budget_report, compute_budget, enforce_budget
    from optics.ir import VerifyReport

    def spec(i, lasers=(), p=1000.0):
        return ModuleSpec(id=i, title=i, purpose="", wavelength_nm=1064, laser_ids=list(lasers), input_power_mw=p,
                          input="", outputs=[], width_mm=400, height_mm=200)
    specs = [spec("dist", ["l1064"]), spec("tw1"), spec("tw2"), spec("tw3"), spec("orphan", p=50)]
    lasers = [Laser(id="l1064", model="3 W fiber amp", wavelength_nm=1064, power_mw=3000)]
    links = [FiberLink(from_module="dist", to_module=t, purpose="", power_mw=1900) for t in ("tw1", "tw2", "tw3")]
    b, links2 = compute_budget(specs, lasers, links)
    assert b["dist"]["input_mw"] == 3000
    assert math.isclose(sum(l.power_mw for l in links2), 0.9 * 3000)   # feeds scaled to the cap
    assert math.isclose(b["tw1"]["input_mw"], 900 * 0.7, abs_tol=0.1)
    assert b["tw1"]["label"] == "fed from dist (fiber)"
    assert b["orphan"]["unbudgeted"]
    d = enforce_budget(load("aom_singlepass_pickoff"), b["tw1"])
    assert math.isclose(sum(s.power_mw for s in d.sources), 630, abs_tol=0.01)
    assert d.sources[0].label.startswith("fed from dist")
    rep = budget_report(VerifyReport(passed=True, score=99, checks=[]), lasers, b, links2,
                        {"dist": 2600.0})
    assert rep.metrics["total_laser_mw"] == 3000 and rep.metrics["sum_of_module_inputs_mw"] == 3050
    assert [c for c in rep.checks if c.id == "power_budget" and c.severity == "warning"]  # the orphan's 50 mW
    b2, l2 = compute_budget(specs[:4], lasers, links)
    rep2 = budget_report(VerifyReport(passed=True, score=99, checks=[]), lasers, b2, l2, {"dist": 2600.0})
    assert not [c for c in rep2.checks if c.severity == "warning"] and rep2.score == 99
