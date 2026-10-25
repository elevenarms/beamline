"""POST /api/build_doc -> the build document PDF (inline).

Body: {"design": Design, "cover_data_url"?: "data:image/...;base64,...", "tune_summary"?: {...},
       "citation"?: str, "license"?: str, "figure_url_or_data"?: data URL or https URL}
Remote figures are fetched only from arxiv.org / export.arxiv.org / upload.wikimedia.org (<= 10 MB, 5 s).
"""
from __future__ import annotations

import base64
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from .ir import Design

router = APIRouter()
ALLOWED_HOSTS = {"arxiv.org", "export.arxiv.org", "upload.wikimedia.org"}
MAX_BYTES = 10 * 1024 * 1024


class BuildDocBody(BaseModel):
    design: Design
    cover_data_url: str | None = None
    tune_summary: dict[str, Any] | None = None
    citation: str | None = None
    license: str | None = None
    figure_url_or_data: str | None = None


def _data_url(s: str | None) -> bytes | None:
    if not s or not s.startswith("data:") or "," not in s:
        return None
    head, payload = s.split(",", 1)
    try:
        return base64.b64decode(payload) if ";base64" in head else urllib.parse.unquote_to_bytes(payload)
    except Exception:
        return None


def _figure(s: str | None) -> bytes | None:
    if not s:
        return None
    if s.startswith("data:"):
        return _data_url(s)
    u = urllib.parse.urlparse(s)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(s, headers={"User-Agent": "beamline"}), timeout=5) as r:
            data = r.read(MAX_BYTES + 1)
        return data if len(data) <= MAX_BYTES else None
    except Exception:
        return None


@router.post("/api/build_doc")
def build_doc_endpoint(body: BuildDocBody) -> Response:
    from .build_doc import build_document

    try:
        pdf = build_document(body.design, cover_png=_data_url(body.cover_data_url), tune_summary=body.tune_summary,
                             citation=body.citation, figure_png=_figure(body.figure_url_or_data), license=body.license)
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in body.design.name) or "design"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}_build.pdf"'})
