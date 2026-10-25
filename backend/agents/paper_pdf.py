"""Same-origin proxy for arXiv PDFs so the web app can show the source paper in a small embedded viewer
(arxiv.org may refuse to be framed by another origin).  GET /api/papers/pdf/{arxiv_id}
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

# New-style (2004.05246, 2004.05246v2) and old-style (physics/0307095) arXiv identifiers only.
_ID = re.compile(r"^(\d{4}\.\d{4,5}(v\d+)?|[a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?)$")
_CACHE = Path(tempfile.gettempdir()) / "beamline_pdf_cache"
_MAX_BYTES = 40 * 1024 * 1024
_UA = {"User-Agent": "beamline-hackathon (contact: none)"}


@router.get("/api/papers/pdf/{arxiv_id:path}")
async def paper_pdf(arxiv_id: str) -> FileResponse:
    if not _ID.match(arxiv_id):
        raise HTTPException(400, "not an arXiv identifier")
    _CACHE.mkdir(exist_ok=True)
    path = _CACHE / (arxiv_id.replace("/", "_") + ".pdf")
    if not path.exists():
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_UA) as client:
            async with client.stream("GET", f"https://arxiv.org/pdf/{arxiv_id}") as r:
                if r.url.host not in ("arxiv.org", "export.arxiv.org"):
                    raise HTTPException(502, "unexpected redirect")
                if r.status_code != 200 or "pdf" not in r.headers.get("content-type", ""):
                    raise HTTPException(502, f"arXiv returned {r.status_code}")
                data = bytearray()
                async for chunk in r.aiter_bytes():
                    data += chunk
                    if len(data) > _MAX_BYTES:
                        raise HTTPException(413, "PDF too large")
        tmp = path.with_suffix(".part")
        tmp.write_bytes(bytes(data))
        tmp.replace(path)
    # inline so the browser's PDF viewer renders it inside an <iframe>
    return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": "inline"})
