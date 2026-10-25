# BEAMTEAM — 60 s demo video

Output: `beamline_demo_60s.mp4` (1920×1080, H.264 + AAC, 59.9 s, ≈ -16 LUFS), captions `beamline_demo_60s.srt` (not burned in).
Re-cut on 2026-10-25 after the rename to **BEAMTEAM** and the misalignment/overlay UI fixes.

## Footage
All app footage is a **real screen recording of LIVE runs** (no "Recorded runs" replay), captured with the chrome-devtools
MCP screencast at 1512×860 CSS px (3024×1610 device px), light theme, against http://localhost:8001 (new build).

- `raw/main2.mp4` — live run #1: search "optical tweezers" → Gieseler et al. 2020, Fig. 5 (score 16) → Build this setup →
  … → build-document PDF (BEAMTEAM masthead, PASS 95). Used for: search results, figure pick, build PDF.
- `raw/main3.mp4` — live run #2 of the same figure (re-clicked "Build this setup"; Agent Console auto-opens, then closed at
  fly-in so the bench is visible). PASS 96, ~0:51 to fly-in. Used for: agents/console, verify, fly-in, "Aligning…" + tuning tour.
  (Run #1's fly-in/tuning were hidden behind the console, hence the second run.)
- `raw/extras2.mp4` — same session: Build kit (Parts BOM, 3D print baseplate turntable), Cover art modal (both Nano Banana
  renders generated live), `sr_ion_apparatus` loaded fresh (121 elements, PASS 99, no leftover overlays).

Sped-up sections carry an on-screen badge (×4 agents, ×2 verify and fly-in, ×2.5 tuning). Cuts are 0.3 s crossfades.
Narration: Gemini TTS `gemini-3.1-flash-tts-preview`, voice "Charon". Beats 1 and 9 regenerated with the name spoken
"Beam Team" (captions write BEAMTEAM); beats 2–8 reused unchanged.

## Narration (134 words) and timeline

| Video time | Footage (source, speed) | Narration |
|---|---|---|
| 0.0–2.7 | Title card "BEAMTEAM — from published figure to buildable optical bench" | Laying out a laser-optics bench by hand takes weeks. BEAMTEAM does it in minutes. |
| 2.4–6.7 | main2 2–6 s, 1× (app with arXiv results) | (cont.) |
| 6.4–12.3 | main2 46.5–52.1 s, 1× (Fig. 5 preview → Build this setup) | Search arXiv for optical tweezers, pick a real setup figure, and press build. |
| 12.0–20.3 | main3 2–34 s, **×4** (figure above table, scan boxes, Agent Console token streams) | Three Gemini vision agents read the figure in parallel, while synthesizer, verifier and repair agents stream their reasoning live. |
| 20.0–27.3 | main3 34–48 s, **×2** (synthesizers/repair → verify PASS) | Every design is checked with real physics: Gaussian beams, polarization, and stray-beam laser safety. |
| 27.0–33.3 | main3 48–60 s, **×2** (parts fly onto bench, beams on) | Then the parts fly off the drawing onto the bench, and the lasers switch on. |
| 33.0–39.3 | main3 60–75 s, **×2.5** ("Aligning…", tuning tour, power meter) | The bench starts misaligned, and the tuner walks each mirror until the power meter climbs back. |
| 39.0–45.8 | main2 168–171 s (build PDF, BEAMTEAM cover) → extras2 BOM → 3D-print baseplate, 1× | You get a cover render and a build document, with a bill of materials and a printable, keyed baseplate. |
| 45.5–52.8 | extras2 38–45 s, 1× (sr_ion_apparatus, 121 elements) | And it scales: a trapped-ion apparatus with a hundred twenty-one optics, traced in milliseconds. |
| 52.5–56.8 | extras2 29.3–33.3 s, 1× (Cover art modal, both renders) | BEAMTEAM. From paper to buildable bench in under three minutes. |
| 56.5–59.9 | End card: github.com/elevenarms/beamline · elevenarms.github.io/beamline · Gemini gemini-4-argon agents · Nano Banana renders; credits line (PyOpticL, Gieseler et al. 2020) | |

Notes: the PDF shot comes from live run #1 while the bench shots come from live run #2 of the same figure (both live).
Status bar shows the 121-element trace at 14 ms in this session (DEMO.md: 6.1 ms), so narration says "milliseconds".
