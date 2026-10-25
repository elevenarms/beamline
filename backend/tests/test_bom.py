"""Build kit: BOM rows, watertight printable plate STLs, hole counts, tiling."""
import io
import json
import zipfile
from pathlib import Path

import pytest
import trimesh

from optics.bom import TILE_MAX, build_bom, build_kit, kit_zip, plate_genus
from optics.ir import Design
from optics.trace import trace

EX = Path(__file__).resolve().parent.parent / "examples"


def load(name):
    return Design.model_validate_json((EX / f"{name}.json").read_text())


@pytest.mark.parametrize("name", ["aom_doublepass_fixed", "rb_sas"])
def test_kit_stls_watertight_and_holes_match(name, tmp_path):
    d = load(name)
    bom, out = build_kit(d, out_dir=tmp_path)
    placed = [e for e in trace(d).elements if e.placed]
    assert bom["plate"]["element_sites"] == len(placed)
    assert bom["plate"]["pin_holes"] <= 2 * len(placed)
    genus, expected = plate_genus(d)
    assert genus == expected == bom["plate"]["table_holes"] + len(placed)   # every through hole present
    for p in bom["printed"]:
        m = trimesh.load(out / p["file"])
        assert m.is_watertight, p["name"]
        assert max(m.extents[:2]) <= TILE_MAX + 1e-6
        assert p["volume_cm3"] > 0 and p["est_print_h"] > 0 and p["est_filament_g"] > 0
    hw = {r["part_number"]: r["qty"] for r in bom["hardware"]}
    assert hw["SH8S100"] == len(placed) and hw["DOWEL-2x8"] == bom["plate"]["pin_holes"]
    assert hw["SH25S050"] == bom["plate"]["table_holes"]


def test_bom_rows_and_defaults():
    d = load("aom_doublepass_fixed")
    bom = build_bom(d)
    rows = {r["part_number"]: r for r in bom["purchased"]}
    for e in d.elements:
        assert any(e.id in r["element_ids"] for r in bom["purchased"]), e.id
    assert all(r["qty"] >= 1 for r in bom["purchased"])
    assert bom["totals"]["est_cost_usd"] > 1000
    # default kit when no part number: mirror -> BB1 + KM100 (+ thorlabs url)
    d2 = Design.model_validate({"name": "x", "sources": [{"id": "L", "position": [80, 75],
                                "direction_deg": 0, "wavelength_nm": 780}],
                                "elements": [{"id": "M", "type": "mirror", "beam": "L", "distance_mm": 50,
                                              "out_direction_deg": 90},
                                             {"id": "D", "type": "beam_dump", "beam": "L", "distance_mm": 40}]})
    r2 = {r["part_number"]: r for r in build_bom(d2)["purchased"]}
    assert {"BB1-E03", "KM100", "LB1"} <= set(r2)
    assert r2["KM100"]["url"].endswith("partnumber=KM100") and r2["KM100"]["unit_price_usd"]


def test_large_plate_is_tiled():
    d = load("sr_ion_apparatus")
    bom = build_bom(d)
    assert bom["plate"]["tiles"] > 1 and len(bom["printed"]) == bom["plate"]["tiles"]
    assert bom["plate"]["joint_bolts"] > 0
    assert any(r["part_number"] == "M3x25+NUT" for r in bom["hardware"])


def test_zip_contents():
    d = load("aom_doublepass_fixed")
    z = zipfile.ZipFile(io.BytesIO(kit_zip(d)))
    names = z.namelist()
    root = f"{d.name}_kit/"
    for f in ("BOM.csv", "bom.json", "README.md", "pyopticl_design.py"):
        assert root + f in names
    assert any(n.startswith(root + "stl/") and n.endswith(".stl") for n in names)
    assert json.loads(z.read(root + "bom.json"))["design"] == d.name
