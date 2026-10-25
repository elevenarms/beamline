"""Optical logic designs compute the right Boolean functions and trace cleanly for every input combo."""
from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from logic import CIRCUITS, evaluate, load, run, truth_table

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.mark.parametrize("name", ["optical_nand", "optical_half_adder", "optical_full_adder"])
def test_truth_table_and_verify(name):
    path = EXAMPLES / f"{name}.json"
    spec = CIRCUITS[name]
    outputs = list(spec["outputs"])
    rows = truth_table(path, spec["inputs"], outputs)
    assert len(rows) == 2 ** len(spec["inputs"])
    for row in rows:
        bits = tuple(row["inputs"].values())
        expected = {o: f(*bits) for o, f in spec["outputs"].items()}
        assert row["outputs"] == expected, (bits, row["powers_mw"])
        assert row["passed"] and not row["errors"], (bits, row["errors"])


def test_nand_explicit():
    p = EXAMPLES / "optical_nand.json"
    for a, b in itertools.product((0, 1), repeat=2):
        assert evaluate(p, {"A": a, "B": b})["NAND"] == int(not (a and b))


def test_half_adder_one_plus_one_is_binary_ten():
    out = evaluate(EXAMPLES / "optical_half_adder.json", {"A": 1, "B": 1})
    assert (out["CARRY"], out["SUM"]) == (1, 0)


@pytest.mark.parametrize("name", list(CIRCUITS))
def test_no_stray_light_or_warnings_any_combo(name):
    d = load(EXAMPLES / f"{name}.json")
    ins = CIRCUITS[name]["inputs"]
    for bits in itertools.product((0, 1), repeat=len(ins)):
        _, rep = run(d, dict(zip(ins, bits)))
        assert rep.metrics["stray_mw"] == 0.0
        assert not [c for c in rep.checks if c.severity == "warning"], bits


# ───────────────────── nonlinear all-optical gates (inputs = source enables) ─────────────────────

@pytest.mark.parametrize("name", ["alloptical_nand", "alloptical_and_sfg"])
def test_alloptical_truth_tables(name):
    spec = CIRCUITS[name]
    rows = truth_table(EXAMPLES / f"{name}.json", spec["inputs"], list(spec["outputs"]))
    for row in rows:
        bits = tuple(row["inputs"].values())
        assert row["outputs"] == {o: f(*bits) for o, f in spec["outputs"].items()}, (bits, row["powers_mw"])
        assert row["passed"], (bits, row["errors"])


def test_alloptical_nand_levels():
    p = EXAMPLES / "alloptical_nand.json"
    d = load(p)
    lvl = {bits: run(d, dict(zip("AB", bits)))[0]["OUT"] for bits in itertools.product((0, 1), repeat=2)}
    assert lvl[(0, 1)] == pytest.approx(lvl[(1, 0)], rel=1e-6)    # symmetric inputs
    assert lvl[(1, 1)] < 0.15 < min(lvl[(0, 1)], lvl[(0, 0)])      # threshold sits between the levels
    assert lvl[(0, 1)] / lvl[(1, 1)] > 2.5                           # >= ~4 dB extinction after the SA


def test_alloptical_sfg_outputs_red_only_for_11():
    d = load(EXAMPLES / "alloptical_and_sfg.json")
    for bits in itertools.product((0, 1), repeat=2):
        assert evaluate(d, dict(zip("AB", bits)))["OUT"] == (bits[0] & bits[1])


def test_source_and_hwp_inputs_mix():
    from logic import set_inputs
    d = set_inputs(load(EXAMPLES / "alloptical_nand.json"), {"A": 0, "B": 1})
    assert [s.enabled for s in d.sources if s.id in "AB"] == [False, True]
    with pytest.raises(KeyError):
        set_inputs(d, {"NOPE": 1})
