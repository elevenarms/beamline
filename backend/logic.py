"""Optical logic: evaluate polarization-encoded "directed logic" designs as Boolean circuits.

Each input bit is a half-wave plate (element id = bit name): fast_axis_deg 0 = bit 0 (H stays H),
45 = bit 1 (H -> V). PBSs route the rail by polarization, so the light ends up on exactly one
photodiode path per input combination. An output bit is 1 when its photodiode absorbs more than
THRESHOLD x the total source power.

    evaluate(design_path, {"A": 1, "B": 0}) -> {"SUM": 1, "CARRY": 0}
    truth_table(design_path, ["A", "B"], ["SUM", "CARRY"]) -> list of rows

CLI:  uv run python -m logic examples/optical_half_adder.json
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path
from typing import Callable

from optics.ir import Design, VerifyReport
from optics.trace import trace
from optics.verify import verify

THRESHOLD = 0.20  # fraction of total source power

# Known example circuits: inputs, outputs and the Boolean function each output should compute.
CIRCUITS: dict[str, dict] = {
    "optical_nand": {
        "inputs": ["A", "B"],
        "outputs": {"NAND": lambda a, b: int(not (a and b)), "AND": lambda a, b: a & b},
    },
    "optical_half_adder": {
        "inputs": ["A", "B"],
        "outputs": {"SUM": lambda a, b: a ^ b, "CARRY": lambda a, b: a & b},
    },
    "optical_full_adder": {
        "inputs": ["A", "B", "CIN"],
        "outputs": {"SUM": lambda a, b, c: a ^ b ^ c,
                    "COUT": lambda a, b, c: (a & b) | (c & (a ^ b))},
    },
}


def load(design_path: str | Path) -> Design:
    return Design.model_validate_json(Path(design_path).read_text())


def set_inputs(design: Design, inputs: dict[str, int]) -> Design:
    """Copy of the design with each input HWP's fast axis set to 0 deg (bit 0) or 45 deg (bit 1)."""
    d = design.model_copy(deep=True)
    by_id = {e.id: e for e in d.elements}
    for name, bit in inputs.items():
        el = by_id.get(name)
        if el is None or el.type != "half_wave_plate":
            raise KeyError(f"input {name!r} is not a half_wave_plate in {d.name}")
        el.fast_axis_deg = 45.0 if bit else 0.0
    return d


def run(design: Design, inputs: dict[str, int]) -> tuple[dict[str, float], VerifyReport]:
    """Trace with the given inputs; return photodiode powers (mW) and the verify report."""
    d = set_inputs(design, inputs)
    tr = trace(d)
    powers = {e.id: (e.power_out_mw or 0.0) for e in tr.elements if e.type == "photodiode"}
    return powers, verify(d, tr)


def evaluate(design_path: str | Path | Design, inputs: dict[str, int],
             outputs: list[str] | None = None) -> dict[str, int]:
    design = design_path if isinstance(design_path, Design) else load(design_path)
    powers, _ = run(design, inputs)
    p_in = sum(s.power_mw for s in design.sources)
    if outputs is None:
        spec = CIRCUITS.get(design.name)
        outputs = list(spec["outputs"]) if spec else [k for k in powers if k != "REF"]
    return {o: int(powers.get(o, 0.0) > THRESHOLD * p_in) for o in outputs}


def truth_table(design_path: str | Path | Design, inputs: list[str], outputs: list[str]) -> list[dict]:
    """One row per input combination: {"inputs", "outputs", "powers_mw", "passed", "errors"}."""
    design = design_path if isinstance(design_path, Design) else load(design_path)
    p_in = sum(s.power_mw for s in design.sources)
    rows = []
    for bits in itertools.product((0, 1), repeat=len(inputs)):
        ins = dict(zip(inputs, bits))
        powers, rep = run(design, ins)
        rows.append({
            "inputs": ins,
            "outputs": {o: int(powers.get(o, 0.0) > THRESHOLD * p_in) for o in outputs},
            "powers_mw": {o: powers.get(o, 0.0) for o in outputs},
            "passed": rep.passed,
            "errors": [c.message for c in rep.checks if c.severity == "error"],
        })
    return rows


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    design = load(argv[0])
    spec = CIRCUITS.get(design.name)
    if spec:
        inputs, funcs = spec["inputs"], spec["outputs"]
    else:
        inputs = [e.id for e in design.elements if e.type == "half_wave_plate" and "(HWP)" in e.label]
        funcs = {e.id: None for e in design.elements if e.type == "photodiode" and e.id != "REF"}
    outputs = list(funcs)
    print(f"{design.name}: inputs {inputs} -> outputs {outputs}  (1 = PD > {THRESHOLD:.0%} of source power)")
    print("  " + "  ".join(inputs) + "  |  " + "  ".join(f"{o:>14}" for o in outputs) + "  | verify")
    ok_all = True
    for row in truth_table(design, inputs, outputs):
        cells = []
        for o in outputs:
            f: Callable | None = funcs[o]
            got = row["outputs"][o]
            mark = "" if f is None else (" ✓" if got == f(*row["inputs"].values()) else " ✗")
            ok_all &= mark != " ✗"
            cells.append(f"{got} ({row['powers_mw'][o]:5.2f} mW){mark}")
        ok_all &= row["passed"]
        bits = "  ".join(str(v).rjust(len(k)) for k, v in row["inputs"].items())
        print(f"  {bits}  |  " + "  ".join(f"{c:>14}" for c in cells)
              + f"  | {'pass' if row['passed'] else 'FAIL ' + '; '.join(row['errors'])}")
    print("all correct" if ok_all else "MISMATCH")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
