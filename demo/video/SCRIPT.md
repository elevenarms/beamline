# Beamline — 60 s demo video

Output: `beamline_demo_60s.mp4` (1920×1080, H.264 + AAC, 59.93 s), captions `beamline_demo_60s.srt` (not burned in).

## Footage
All app footage is a **real screen recording of a LIVE run** (not the "Recorded runs" replay), captured with the
chrome-devtools MCP screencast at 1512×860 CSS px (3024×1610 device px), light theme, against http://localhost:8001
on 2026-10-25. Live flow: search "optical tweezers" → Gieseler et al. 2020, Fig. 5 (score 16) → Build this setup →
agents (3 vision, 2 synthesizers, verifier, autofix/repair) → fly-in → as-built misalignment → tuning → cover → build PDF.
The live run reported 1:23 to DONE in the app's own timer.
Extras clip (same session): Build kit (Parts BOM, 3D print baseplate turntable), Cover art modal
(Nano Banana renders, re-rendered live), `sr_ion_apparatus` example (121 elements, PASS 99).
Raw: `raw/main.mp4` (118 s), `raw/extras.mp4` (75 s).

Sped-up sections carry an on-screen speed badge (×5 agents, ×2 verify/fly-in, ×2.5 tuning). Cuts are 0.3 s crossfades.
Narration: Gemini TTS `gemini-3.1-flash-tts-preview`, voice "Charon", loudness-normalised to ≈ -16 LUFS.

## Narration (134 words) and timeline

| Video time | Footage (source, speed) | Narration |
|---|---|---|
| 0.0–2.7 | Title card | Laying out a laser-optics bench by hand takes weeks. Beamline does it in minutes. |
| 2.4–6.7 | main 0–4 s, 1× (app, search results) | (cont.) |
| 6.4–12.3 | main 4–9.6 s, 1× (Fig. 5 preview → Build this setup) | Search arXiv for optical tweezers, pick a real setup figure, and press build. |
| 12.0–20.4 | main 9.6–50 s, **×5** (figure flat above table, scan boxes, Agent Console streams) | Three Gemini vision agents read the figure in parallel, while synthesizer, verifier and repair agents stream their reasoning live. |
| 20.0–27.3 | main 50–64 s, **×2** (autofix, verify PASS) | Every design is checked with real physics: Gaussian beams, polarization, and stray-beam laser safety. |
| 27.0–33.3 | main 64–76 s, **×2** (parts fly onto bench, beams on) | Then the parts fly off the drawing onto the bench, and the lasers switch on. |
| 33.0–39.3 | main 76–91 s, **×2.5** (as-built misalignment, tuning tour, power meter) | The bench starts misaligned, and the tuner walks each mirror until the power meter climbs back. |
| 39.0–45.8 | main 93–96 s (build-document PDF w/ cover) → extras BOM → 3D-print baseplate, 1× | You get a cover render and a build document, with a bill of materials and a printable, keyed baseplate. |
| 45.5–52.8 | extras 65–72 s, 1× (sr_ion_apparatus, 121 elements) | And it scales: a trapped-ion apparatus with a hundred twenty-one optics, traced in milliseconds. |
| 52.5–56.8 | extras 48–52 s, 1× (Cover art modal) | Beamline. From paper to buildable bench in under three minutes. |
| 56.5–59.9 | End card: github.com/elevenarms/beamline · Gemini gemini-4-argon agents · Nano Banana renders | |

Notes / honesty: speed badges mark every non-real-time section; the 121-optic trace time shown in the app status bar is 20 ms
(DEMO.md measured 6.1 ms), so narration says "milliseconds". The tuning in this run went 5.28 → 9.00 mW.
