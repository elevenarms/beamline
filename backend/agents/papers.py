"""arXiv paper search -> optical-setup figures (for "reproduce from a paper figure").

search_papers(q, limit): ONE arXiv API call, then the arXiv HTML render (arxiv.org/html/<id>) and abs page of
the top hits fetched in parallel; <figure> images + captions are scored for "optical setup"-ness.
fetch_image(url): allowlisted, https-only, size-capped image download.
Results are cached in-process for 10 minutes. Polite User-Agent per arXiv's API terms.
"""
from __future__ import annotations

import asyncio
import re
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

UA = "beamline-hackathon (contact: none)"
API = "https://export.arxiv.org/api/query"
TIMEOUT = 8.0
CACHE_TTL = 600.0
MAX_FIGS = 4
MAX_IMAGE_BYTES = 15 * 1024 * 1024
ALLOWED_HOSTS = {"arxiv.org", "export.arxiv.org", "upload.wikimedia.org"}
RASTER = (".png", ".jpg", ".jpeg", ".gif", ".webp")
ATOM = {"a": "http://www.w3.org/2005/Atom"}

_cache: dict[tuple[str, int], tuple[float, list[dict]]] = {}

POSITIVE = {
    "setup": 3.0, "set-up": 3.0, "set up": 2.0, "schematic": 3.0, "optical layout": 4.0, "layout": 1.5,
    "experimental apparatus": 4.0, "apparatus": 2.5, "beam path": 3.5, "laser system": 3.5, "optical": 1.0,
    "aom": 2.0, "acousto-optic": 2.0, "pbs": 2.0, "polarizing beam": 2.0, "beam splitter": 1.5, "beamsplitter": 1.5,
    "fiber": 1.0, "fibre": 1.0, "lens": 1.0, "mirror": 1.0, "objective": 1.0, "tweezer": 1.5, "cavity": 1.0,
    "waveplate": 1.5, "wave plate": 1.5, "photodiode": 1.5, "dichroic": 1.5, "telescope": 1.0, "breadboard": 2.0,
    "spectroscopy setup": 2.0, "optical setup": 4.0, "experimental setup": 4.0, "sketch": 1.5, "diagram": 1.0,
    "laser": 0.5, "beam": 0.5, "isolator": 1.0, "vapor cell": 1.5, "vapour cell": 1.5,
}
NEGATIVE = {
    "plot": 2.0, "spectrum": 1.5, "spectra": 1.5, "data": 1.5, "simulation": 2.0, "simulated": 2.0,
    "histogram": 2.0, "as a function of": 2.0, "versus": 1.5, " vs": 1.0, "measured": 1.0, "fit": 1.0,
    "error bars": 2.0, "dependence": 1.5, "results": 1.0, "comparison": 1.0, "photograph": 0.5, "image of": 0.5,
    "trajectory": 1.0, "phase diagram": 2.0, "band structure": 2.0,
}


def setup_score(caption: str) -> float:
    c = " " + caption.lower() + " "
    pos = sum(w for k, w in POSITIVE.items() if k in c)
    neg = sum(w for k, w in NEGATIVE.items() if k in c)
    # the first sentence of a caption names the figure; weight it double
    first = c.split(". ")[0]
    pos += 0.5 * sum(w for k, w in POSITIVE.items() if k in first and w >= 2.5)
    return round(max(0.0, pos - neg), 2)


class _FigureParser(HTMLParser):
    """Collect top-level <figure> elements: first raster <img> src + <figcaption> text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.figs: list[dict[str, Any]] = []
        self.depth = 0
        self.cur: dict[str, Any] | None = None
        self.in_cap = 0
        self.skip = 0   # inside <math> / annotation: keep alttext only

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "figure":
            if self.depth == 0:
                self.cur = {"id": a.get("id") or "", "imgs": [], "caption": [], "cls": a.get("class") or ""}
            self.depth += 1
        elif self.cur is not None:
            if tag == "img" and a.get("src"):
                self.cur["imgs"].append((a["src"], a.get("width"), a.get("height")))
            elif tag == "figcaption":
                self.in_cap += 1
            elif tag == "math":
                if self.in_cap and a.get("alttext"):
                    self.cur["caption"].append(" " + a["alttext"] + " ")
                self.skip += 1

    def handle_endtag(self, tag):
        if tag == "figure" and self.depth:
            self.depth -= 1
            if self.depth == 0 and self.cur is not None:
                self.figs.append(self.cur)
                self.cur = None
        elif tag == "figcaption" and self.in_cap:
            self.in_cap -= 1
        elif tag == "math" and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if self.cur is not None and self.in_cap and not self.skip:
            self.cur["caption"].append(data)


def parse_figures(html: str, base_url: str) -> list[dict]:
    p = _FigureParser()
    try:
        p.feed(html)
    except Exception:  # noqa: BLE001
        pass
    out = []
    for f in p.figs:
        if "ltx_table" in f["cls"]:
            continue
        imgs = [s for s, _, _ in f["imgs"] if urlparse(s).path.lower().endswith(RASTER)]
        if not imgs:
            continue
        caption = re.sub(r"\s+", " ", "".join(f["caption"])).strip()
        if not caption:
            continue
        out.append({"id": f["id"] or f"fig{len(out) + 1}", "url": urljoin(base_url, imgs[0]),
                    "caption": caption[:1200], "setup_score": setup_score(caption)})
    return out


def _parse_atom(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall("a:entry", ATOM):
        raw_id = (e.findtext("a:id", "", ATOM) or "").rsplit("/abs/", 1)[-1]
        if not raw_id:
            continue
        base_id = re.sub(r"v\d+$", "", raw_id)
        title = re.sub(r"\s+", " ", e.findtext("a:title", "", ATOM) or "").strip()
        published = e.findtext("a:published", "", ATOM) or ""
        authors = [a.findtext("a:name", "", ATOM) for a in e.findall("a:author", ATOM)]
        out.append({"arxiv_id": base_id, "title": title, "authors": [a for a in authors if a][:8],
                    "year": int(published[:4]) if published[:4].isdigit() else None,
                    "abs_url": f"https://arxiv.org/abs/{base_id}"})
    return out


_LICENSE_RE = re.compile(r'href="(https?://(?:creativecommons\.org/(?:licenses|publicdomain)/[^"]+|'
                         r'arxiv\.org/licenses/[^"]+))"')


def _license_from_abs(html: str) -> str | None:
    m = re.search(r'<a[^>]*rel="license"[^>]*href="([^"]+)"', html) or \
        re.search(r'<a[^>]*href="([^"]+)"[^>]*rel="license"', html) or _LICENSE_RE.search(html)
    if not m:
        return None
    url = m.group(1)
    cc = re.search(r"creativecommons\.org/(licenses|publicdomain)/([a-z\-]+)/([\d.]+)?", url)
    if cc:
        kind = cc.group(2).upper()
        return "CC0 1.0" if kind == "ZERO" else f"CC {kind} {cc.group(3) or ''}".strip()
    if "nonexclusive-distrib" in url:
        return "arXiv non-exclusive distribution"
    if "assumed-1991-2003" in url:
        return "arXiv (assumed, 1991-2003)"
    return url


async def _paper_figures(client: httpx.AsyncClient, paper: dict) -> dict | None:
    pid = paper["arxiv_id"]

    async def get(url: str) -> httpx.Response | None:
        try:
            r = await client.get(url, timeout=TIMEOUT, follow_redirects=True)
            return r if r.status_code == 200 else None
        except Exception:  # noqa: BLE001
            return None

    html_r, abs_r = await asyncio.gather(get(f"https://arxiv.org/html/{pid}"), get(paper["abs_url"]))
    if html_r is None or "html" not in html_r.headers.get("content-type", ""):
        return None
    base = str(html_r.url)   # resolve exactly like a browser would (srcs are relative to the page URL)
    figs = parse_figures(html_r.text, base)
    if not figs:
        return None
    figs.sort(key=lambda f: f["setup_score"], reverse=True)
    lic = _license_from_abs(abs_r.text) if abs_r is not None else None
    return {**paper, "license": lic, "figures": figs[:MAX_FIGS]}


async def search_papers(q: str, limit: int = 6) -> list[dict]:
    q = q.strip()
    limit = max(1, min(limit, 12))
    key = (q.lower(), limit)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    terms = " AND ".join(f"all:{w}" for w in re.findall(r"[\w\-]+", q)) or "all:optics"
    params = {"search_query": terms, "start": 0, "max_results": limit * 3, "sortBy": "relevance"}
    async with httpx.AsyncClient(headers={"User-Agent": UA}) as client:
        r = await client.get(API, params=params, timeout=15.0)
        r.raise_for_status()
        papers = _parse_atom(r.text)
        results = await asyncio.gather(*(_paper_figures(client, p) for p in papers))
    found = [p for p in results if p]
    # papers whose best figure looks most like a setup first (arXiv relevance breaks ties)
    found.sort(key=lambda p: -max(f["setup_score"] for f in p["figures"]))
    found = found[:limit]
    _cache[key] = (time.time(), found)
    return found


class FetchError(ValueError):
    pass


async def fetch_image(url: str) -> tuple[bytes, str]:
    """Download an allowlisted https image (<= 15 MB). Returns (bytes, mime)."""
    u = urlparse(url)
    if u.scheme != "https" or (u.hostname or "").lower() not in ALLOWED_HOSTS:
        raise FetchError(f"image host not allowed: {u.hostname} (allowed: {', '.join(sorted(ALLOWED_HOSTS))}; https only)")
    async with httpx.AsyncClient(headers={"User-Agent": UA}, follow_redirects=True) as client:
        async with client.stream("GET", url, timeout=20.0) as r:
            if (urlparse(str(r.url)).hostname or "").lower() not in ALLOWED_HOSTS:
                raise FetchError("redirected to a host that is not allowed")
            if r.status_code != 200:
                raise FetchError(f"image fetch failed: HTTP {r.status_code}")
            mime = r.headers.get("content-type", "").split(";")[0].strip().lower()
            if not mime.startswith("image/") or mime == "image/svg+xml":
                raise FetchError(f"not a raster image: {mime or 'unknown content type'}")
            if int(r.headers.get("content-length") or 0) > MAX_IMAGE_BYTES:
                raise FetchError("image larger than 15 MB")
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > MAX_IMAGE_BYTES:
                    raise FetchError("image larger than 15 MB")
    return bytes(buf), mime
