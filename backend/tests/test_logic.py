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
