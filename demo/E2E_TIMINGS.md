# End-to-end timings (paper search → build document PDF), live, 2026-10-25

Both runs: production build served by the non-reloading backend on :8001, query "optical tweezers",
figure = Gieseler et al. 2020 (arXiv:2004.05246) Fig. 5, one click on "Build this setup", then no input.
Pipeline: figure fetch → 3 vision agents → consensus + mm scaling → 2 synthesizers → verify/autofix/repair →
fly-in → as-built misalignment → tuning tour (2×) ‖ cover render (Nano Banana 2) → Typst build document.

| Run | Time | How measured | Evidence |
|---|---|---|---|
| A (~13:05 PDT) | search 2.0 s; PDF shown at 99.9 s after search start (≈1:37 on the in-app run clock, which starts at "Build this setup") | Chrome DevTools automation: `performance.now()` from Search click until the build-document `blob:` iframe appeared; in-app clock read 1:22 at verify PASS 95 | coordinator session log; screenshots taken during the run (verify PASS 95, scrubber synth 0 → 25 → autofix 50 → repair 95 → final 95) |
| B (~13:25 PDT) | in-app run clock reached DONE at 1:23 | app's run-clock HUD, recorded on video | `demo/video/SCRIPT.md`; raw screen recording kept locally (`demo/video/raw/main.mp4`, not committed, 118 s) — DONE frame visible in `beamline_demo_60s.mp4` at ≈49 s |

Budget: 3:00 end to end. Both runs finished within it (≈1:23–1:40 depending on where the clock starts).
