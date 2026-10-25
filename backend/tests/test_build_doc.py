"""Build document PDF: compiles fast and small, with and without a cover."""
import base64
import json
import shutil
import time
from pathlib import Path

import pytest

from optics.build_doc import build_document, plan_svg, wavelength_color
from optics.ir import Design
from optics.trace import trace

ROOT = Path(__file__).resolve().parents[2]
EX = ROOT / "backend" / "examples"
pytestmark = pytest.mark.skipif(not shutil.which("typst") and not Path("/opt/homebrew/bin/typst").exists(),
                                reason="typst not installed")


def _pages(pdf: bytes) -> int:
    return pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages") or pdf.count(b"/Type/Page") - pdf.count(b"/Type/Pages")


def test_aom_doublepass_pdf_fast_and_small():
    d = Design.model_validate_json((EX / "aom_doublepass_fixed.json").read_text())
    t = time.perf_counter()
    pdf = build_document(d, tune_summary={"objective_before": 2.5, "objective_after": 4.05, "steps": 75,
                                          "changes": [{"element_id": "HWP1", "field": "fast_axis_deg",
                                                       "from": -7.7, "to": 9.4, "gain": 0.25}]})
    assert time.perf_counter() - t < 2.0
    assert pdf.startswith(b"%PDF") and len(pdf) <= 8 * 1024 * 1024


def test_reproduce_final_with_cover():
    final = None
    for line in (ROOT / "demo" / "live_tweezers_check.sse").read_text().splitlines():
        if line.startswith("data:"):
            ev = json.loads(line[5:])
            if ev["type"] == "final":
                final = ev
    d = Design.model_validate(final["design"])
    cover = (ROOT / "demo" / "covers" / "half_adder_faithful.png").read_bytes()
    t = time.perf_counter()
    pdf = build_document(d, cover_png=cover, citation="Gieseler et al., arXiv:2004.05246")
    assert time.perf_counter() - t < 2.0
    assert pdf.startswith(b"%PDF") and len(pdf) <= 8 * 1024 * 1024


def test_hostile_text_is_safe():
    d = Design.model_validate_json((EX / "mach_zehnder.json").read_text())
    d.description = '#panic("x") ]] *bold* $math$ <tag> "quotes" \\ backslash'
    d.elements[0].label = "#let x = 1 ]"
    assert build_document(d).startswith(b"%PDF")


def test_plan_svg_and_colors():
    d = Design.model_validate_json((EX / "aom_doublepass_fixed.json").read_text())
    svg = plan_svg(d, trace(d))
    assert svg.startswith("<svg") and svg.count("<line") >= len(trace(d).segments) // 2
    c = wavelength_color(532)
    r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
    assert g > r and g > b                       # 532 nm is green
    assert wavelength_color(1064) == "#8c2d5a"  # infrared tone


def test_endpoint():
    from fastapi.testclient import TestClient

    import server
    c = TestClient(server.app)
    d = json.loads((EX / "aom_doublepass_fixed.json").read_text())
    png = (ROOT / "demo" / "covers" / "half_adder_faithful.png").read_bytes()
    r = c.post("/api/build_doc", json={"design": d, "citation": "test",
                                        "cover_data_url": "data:image/png;base64," + base64.b64encode(png).decode(),
                                        "figure_url_or_data": "https://evil.example.com/x.png"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
