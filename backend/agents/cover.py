"""Journal-cover-style renders of the current design with Nano Banana image models.

POST /api/render_cover {"design": Design, "screenshot": "data:image/png;base64,...", "styles": ["faithful","cinematic"]}
-> {"images": [{"style", "model", "data_url", "elapsed_s", "error"}]}

The live 3D canvas screenshot is the composition reference; the prompt describes the setup from the IR so
beam colours and parts match. Classic cover-art *style* only — no masthead, logos or text (we never imitate
a journal's branding).
"""
from __future__ import annotations

import asyncio
import base64
import time
from collections import Counter

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.llm import _api_key  # reuse the key loader; never log the key
from optics.ir import Design

router = APIRouter()

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
STYLES = {
    # Nano Banana 2 keeps the reference layout faithfully (product-hero look).
    "faithful": ("gemini-3.1-flash-image", "Keep EXACTLY the same optical layout, component positions and beam paths as "
                 "the reference image; isolated hero shot of the breadboard on a deep dark background."),
    # Nano Banana 2.1 is more atmospheric but drifts from the layout.
    "cinematic": ("gemini-nano-banana-2.1", "Follow the reference layout closely; place it in a dim atmospheric physics lab "
                  "with faint haze so the beams glow, equipment racks softly out of focus behind."),
}


def _beam_color(nm: float) -> str:
    if nm < 380:
        return f"{nm:.0f} nm ultraviolet (render as faint violet glow)"
    if nm < 450:
        return f"{nm:.0f} nm violet-blue"
    if nm < 495:
        return f"{nm:.0f} nm blue"
    if nm < 570:
        return f"{nm:.0f} nm green"
    if nm < 590:
        return f"{nm:.0f} nm yellow"
    if nm < 620:
        return f"{nm:.0f} nm orange"
    if nm < 750:
        return f"{nm:.0f} nm red"
    return f"{nm:.0f} nm near-infrared (render as deep crimson)"


def build_prompt(design: Design, style_hint: str) -> str:
    wavelengths = sorted({s.wavelength_nm for s in design.sources})
    parts = Counter(e.type.replace("_", " ") for e in design.elements)
    inventory = ", ".join(f"{n} {t}{'s' if n > 1 and not t.endswith('s') else ''}" for t, n in parts.most_common(10))
    return (
        "Create a dramatic scientific journal cover illustration in the classic style of iconic high-impact physics "
        f"magazine cover art, depicting this tabletop laser-optics experiment: {design.name.replace('_', ' ')}. "
        f"{design.description[:300]} "
        f"Optics on a black optical breadboard with a regular grid of mounting holes: {inventory}. "
        f"Laser beams: {'; '.join(_beam_color(w) for w in wavelengths)} — render beams as luminous glowing light paths "
        "with subtle scattering haze. Photoreal polished optics with reflections and caustics, precise kinematic "
        f"mounts, low dramatic camera angle, shallow depth of field, cinematic rim lighting, rich contrast. {style_hint} "
        "Portrait 3:4 composition with empty space at the top for a masthead. "
        "Absolutely no text, no letters, no numbers, no logos, no watermarks."
    )


class CoverBody(BaseModel):
    design: Design
    screenshot: str | None = None  # data URL of the live canvas
    styles: list[str] = ["faithful", "cinematic"]


async def _render(client: httpx.AsyncClient, style: str, design: Design, ref: tuple[str, str] | None) -> dict:
    model, hint = STYLES[style]
    parts: list[dict] = []
    if ref:
        parts.append({"inlineData": {"mimeType": ref[0], "data": ref[1]}})
    parts.append({"text": build_prompt(design, hint)})
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"], "imageConfig": {"aspectRatio": "3:4"}}}
    t0 = time.perf_counter()
    try:
        r = await client.post(API.format(model=model), headers={"x-goog-api-key": _api_key()}, json=body)
        data = r.json()
        if "error" in data:
            raise RuntimeError(data["error"].get("message", "image model error"))
        for p in data["candidates"][0]["content"]["parts"]:
            if "inlineData" in p:
                mime = p["inlineData"].get("mimeType", "image/png")
                return {"style": style, "model": model, "elapsed_s": time.perf_counter() - t0, "error": None,
                        "data_url": f"data:{mime};base64,{p['inlineData']['data']}"}
        raise RuntimeError("model returned no image")
    except Exception as e:  # one style failing must not sink the other
        return {"style": style, "model": model, "elapsed_s": time.perf_counter() - t0, "data_url": None,
                "error": f"{type(e).__name__}: {e}"}


@router.post("/api/render_cover")
async def render_cover(body: CoverBody) -> dict:
    styles = [s for s in body.styles if s in STYLES] or ["faithful"]
    ref = None
    if body.screenshot:
        if not body.screenshot.startswith("data:image/") or ";base64," not in body.screenshot:
            raise HTTPException(400, "screenshot must be a base64 image data URL")
        header, b64 = body.screenshot.split(",", 1)
        if len(b64) > 14_000_000:
            raise HTTPException(413, "screenshot too large")
        base64.b64decode(b64[:100] + "==", validate=False)  # cheap sanity check
        ref = (header[5:].split(";")[0], b64)
    async with httpx.AsyncClient(timeout=120) as client:
        images = await asyncio.gather(*(_render(client, s, body.design, ref) for s in styles))
    return {"images": list(images)}
