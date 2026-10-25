"""Example designs validate, trace cleanly, and export to PyOpticL code that only uses real names."""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from optics.ir import Design
from optics.pyopticl_export import branch_to_index, to_pyopticl

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
EXAMPLES = sorted(p.stem for p in EXAMPLES_DIR.glob("*.json"))
EXPECTED = {"aom_doublepass", "aom_doublepass_fixed", "rb_sas", "fiber_coupling_telescope", "mach_zehnder", "aom_singlepass_pickoff"}

PYOPTICL = Path(os.environ.get(
    "PYOPTICL_REPO", Path(__file__).resolve().parents[3] / "repos" / "PyOpticL"))


def load(name: str) -> Design:
    return Design.model_validate_json((EXAMPLES_DIR / f"{name}.json").read_text())


# ───────────────────────────── examples ─────────────────────────────

def test_all_expected_examples_present():
    assert EXPECTED <= set(EXAMPLES)


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_validates(name):
    d = load(name)
    assert d.name == name
    assert d.description and d.targets
    ids = [s.id for s in d.sources] + [e.id for e in d.elements]
    assert len(ids) == len(set(ids)), "duplicate ids"
    for t in d.targets:
        assert t.element_id in ids
    for e in d.elements:
        assert e.part_number, f"{e.id} lacks a part number"
    # laser / fiber-launch housings render behind the source: keep >= 70 mm of plate behind it
    import math
    for s in d.sources:
        ux, uy = math.cos(math.radians(s.direction_deg)), math.sin(math.radians(s.direction_deg))
        bx, by = s.position[0] - 70 * ux, s.position[1] - 70 * uy
        assert -1e-6 <= bx <= d.baseplate.width_mm and -1e-6 <= by <= d.baseplate.height_mm, s.id


def _trace_available() -> bool:
    try:
        import optics.trace  # noqa: F401
        import optics.verify  # noqa: F401
    except ImportError:
        return False
    return True


# aom_doublepass deliberately leaves the return-pass 0th-order ghost unblocked: it is the
# "verifier catches it" demo; aom_doublepass_fixed is the same design with the ghost dumped.
EXPECTED_STRAY = {"aom_doublepass"}


@pytest.mark.skipif(not _trace_available(), reason="optics.trace/verify not available")
@pytest.mark.parametrize("name", EXAMPLES)
def test_example_traces_and_passes(name):
    from optics.trace import trace
    from optics.verify import verify

    d = load(name)
    tr = trace(d)
    rep = verify(d, tr)
    errors = [c for c in rep.checks if c.severity == "error"]
    if name in EXPECTED_STRAY:
        assert not rep.passed
        assert errors and all(c.id == "stray_beam" for c in errors), [c.message for c in errors]
    else:
        assert not errors, [c.message for c in errors]
        assert rep.passed
    for pe in tr.elements:
        assert pe.placed, f"{pe.id}: {pe.error}"
        x, y = pe.position
        assert 0 <= x <= d.baseplate.width_mm and 0 <= y <= d.baseplate.height_mm, pe.id


# ───────────────────────────── exporter ─────────────────────────────

def test_branch_to_index():
    ids = ["L1", "L2"]
    assert branch_to_index("L1", ids) == ("L1", 0b1)
    assert branch_to_index("L1.t", ids) == ("L1", 0b10)
    assert branch_to_index("L1.r", ids) == ("L1", 0b11)
    assert branch_to_index("L2.r.+1", ids) == ("L2", 0b111)
    assert branch_to_index("L1.t.+1.0.r", ids) == ("L1", 0b10101)


def _module_index(path: Path) -> tuple[set[str], dict[str, set[str]], dict[str, list[str]]]:
    """Top-level names, class -> __init__/method params, class -> base names for one source file."""
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    params: dict[str, set[str]] = {}
    bases: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        if isinstance(node, ast.ClassDef):
            bases[node.name] = [b.id for b in node.bases if isinstance(b, ast.Name)]
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    a = item.args
                    params[f"{node.name}.{item.name}"] = {x.arg for x in a.args + a.kwonlyargs}
    return names, params, bases


def _init_params(cls: str, params, bases) -> set[str] | None:
    while cls:
        if f"{cls}.__init__" in params:
            return params[f"{cls}.__init__"]
        nxt = bases.get(cls, [])
        cls = nxt[0] if nxt else None
    return set()  # no __init__ anywhere -> no keyword args allowed


@pytest.mark.skipif(not PYOPTICL.is_dir(), reason=f"PyOpticL repo not found at {PYOPTICL}")
@pytest.mark.parametrize("name", EXAMPLES)
def test_export_references_real_pyopticl_names(name):
    code = to_pyopticl(load(name))
    tree = ast.parse(code)
    pkg = PYOPTICL / "PyOpticL"
    lib_mods = {m: pkg / "library" / f"{m}.py" for m in ("optics", "thorlabs", "isomet")}
    module_files = {
        "PyOpticL.beam_path": pkg / "beam_path.py",
        "PyOpticL.layout": pkg / "layout.py",
        "PyOpticL.utils": pkg / "utils.py",
        "PyOpticL.library": pkg / "library" / "__init__.py",
    }
    imported: dict[str, tuple[str, str]] = {}  # local name -> (module, name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert not a.name.startswith("PyOpticL") or a.name == "PyOpticL", a.name
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("PyOpticL"):
            assert node.module in module_files, node.module
            names, _, _ = _module_index(module_files[node.module])
            for a in node.names:
                ok = a.name in names or (node.module == "PyOpticL.library" and a.name in lib_mods)
                assert ok, f"{node.module}.{a.name} does not exist"
                imported[a.asname or a.name] = (node.module, a.name)

    # every optics.X / thorlabs.X / isomet.X exists, and keyword args match its __init__
    idx = {m: _module_index(p) for m, p in lib_mods.items()}
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in lib_mods:
            names, _, _ = idx[node.value.id]
            assert node.attr in names, f"{node.value.id}.{node.attr} does not exist in PyOpticL"
            used.add(f"{node.value.id}.{node.attr}")
        if isinstance(node, ast.Call):
            f = node.func
            kws = {k.arg for k in node.keywords if k.arg}
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in lib_mods:
                _, params, bases = idx[f.value.id]
                allowed = _init_params(f.attr, params, bases)
                assert kws <= allowed, f"{f.value.id}.{f.attr}: unknown kwargs {kws - allowed}"
            elif isinstance(f, ast.Name) and f.id in imported:
                mod, real = imported[f.id]
                _, params, bases = _module_index(module_files[mod])
                if real in bases:  # a class
                    allowed = _init_params(real, params, bases)
                    assert kws <= allowed, f"{real}: unknown kwargs {kws - allowed}"
            elif isinstance(f, ast.Attribute) and f.attr == "add":
                _, bp_params, _ = _module_index(module_files["PyOpticL.beam_path"])
                _, lay_params, _ = _module_index(module_files["PyOpticL.layout"])
                allowed = bp_params["BeamPath.add"] | lay_params["Layout.add"]
                assert kws <= allowed, f".add(): unknown kwargs {kws - allowed}"
    assert used, "export used no PyOpticL library parts"


def test_export_marks_unsupported_types():
    code = to_pyopticl(load("rb_sas"))
    assert "TODO" in code and "CELL1" in code and "vapor_cell" in code
    assert "PyOpticL" in code.splitlines()[1]  # credit header
