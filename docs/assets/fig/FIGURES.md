# BEAMTEAM paper figures

All figures are vector PDFs and share one style (`paper/scripts/style.py`: sans-serif, muted palette, beams coloured by wavelength). Column width is 3.4 in and full width is 7.0 in.

To regenerate a figure, run this from `backend/`:

```
uv run --with matplotlib --with pillow python ../paper/scripts/<script>.py
```

Every number below is read from a project artifact or measured by running the backend code. Raw measurements are kept next to the scripts in `scaling_data.json`, `tuning_data.json` and `logic_truth.json`.

---

## 1. `architecture.pdf` (full width), from `fig_architecture.py`

**Caption.** BEAMTEAM architecture. Gemini LLM agents are blue rounded boxes and deterministic code is grey; stacked boxes are parallel instances. There are three entry paths:
- **Reproduce from a paper figure:** paper search and figure fetch, then 3 parallel vision agents, a consensus merge with mm scaling, and 2 parallel synthesizers.
- **Goal to design:** a planner, then $N{=}4$ parallel designers (best-of-$N$).
- **Hierarchical:** an architect, then $M$ parallel module agents, then a merge under a shared laser power budget.

The reproduce and goal paths share a verify–repair loop: deterministic trace/verify/autofix plus an LLM repair agent (at most 3 rounds). The verified design then goes to a deterministic tuner, an image-model cover artist (Nano Banana 2 / 2.1), a Typst publisher, and a build-kit generator (BOM + STL baseplate tiles).

**Source.** `CONTRACT.md`, `backend/agents/{reproduce,design,hierarchical,common,cover}.py`, `backend/optics/{tune,build_doc,bom}.py`.

## 2. `timeline_tweezers.pdf` (full width), from `fig_timeline.py` (uses `sse.py`)

**Caption.** Per-agent timeline of two live reproduce-from-figure runs on the dual-trap optical-tweezers figure (Gieseler et al., arXiv:2004.05246, Fig. 5), using gemini-4-argon throughout.
- **(a)** Three parallel vision passes (23.3–28.1 s) agree 3/3 on 16 parts. The two parallel synthesizers score 0 and 86, and one repair round raises the score to 96. Total wall time is 89.2 s (28.1 s extract + 41.5 s synthesize + 19.6 s repair), with 14/14 figure components matched.
- **(b)** Deterministic autofix lifts synthesizer 2 from 35 to 80. Both repair rounds regress to 45 and are rejected, so the best design (80, PASS) is kept at 118.4 s, inside the 123 s budget.

Light segments show time to first token. Ticks mark the deterministic trace/verify/autofix calls, each under 4 ms.

**Source.** `demo/console_reproduce_url_tweezers.sse` (a) and `demo/live_tweezers_check.sse` (b), using the `agent`, `llm_call`, `tool`, `iteration`, `match` and `status:done` events.

**Notes.**
- The SSE streams have no wall-clock timestamps. Bar lengths are each agent's own `elapsed_ms`, and stage starts are the running sums of the per-stage times in `done`.
- Neither stream contains tune, cover or PDF events, so there is no downstream tail.

## 3. `scores_iterations.pdf` (column), from `fig_scores.py`

**Caption.** Verifier score (0–100) for every design scored in seven live runs. Each line is the best score so far, which is the design the pipeline keeps. Marker shape shows the origin (LLM synthesizer/designer, deterministic autofix, or LLM repair), and hollow markers failed verification.
- Autofix alone produces large jumps: 35→80, 35→65, 65→95, 60→90 and 68→93.
- Repair adds 5–10 points: 86→96 and 90→95.
- Regressing repairs are discarded: tweezers B scored 45 and 45, and CC-BY SAS scored 0.
- Final scores: Rb SAS 96/95/95, CC-BY SAS 86, tweezers 96 and 80, and goal→design (4 parallel designers) 93.

**Source.** `iteration` and `final` events in these files:
- `demo/reliability/rb_sas_{1,2,3}.sse`
- `demo/live_cc_by_sas.sse`
- `demo/console_reproduce_url_tweezers.sse`
- `demo/live_tweezers_check.sse`
- `demo/console_design.sse`

**Note.** The benchmark runs in `demo/figures/runs/*.sse` contain only `candidate` events, so they are left out.

## 4. `benchmark.pdf` (column), from `fig_benchmark.py`

**Caption.** Stress test on 8 open-access published setup figures. Bars show wall time and labels give the verifier score; green is PASS and red is FAIL.
- **Reproduce mode: 4/8 PASS.** Raman back-scatter 96 (46 s), pump–probe 100 (55 s), PDH lock 95 (41 s) and the 22-element dual-trap tweezers 96 (80 s).
- **Reproduce failures:** Sr$^+$ 0 (104 s), MOT/LCVR 0 (90 s) and HOM 18 (119 s). The dense Yb$^+$ figure hit the 60 s vision-extraction deadline twice.
- **Goal-design mode: all 4 completed runs PASS.** PDH 99.6 (52 s), Sr$^+$ 74.7 (68 s), tweezers 99.5 (84 s, 58 elements) and goal-only MALDI 99.2 (50 s, 32 elements).
- **Excluded:** the MOT design run was aborted by a dev-server reload. It is an infrastructure fault and is not counted.

**Source.** `demo/figures/runs/summary.json` (parsed from `runs/*.sse`), `catalog.json`, `runs/aborted_reload/`, `runs/failed_attempts/` and `RESULTS.md`.

**Note.** `DEMO.md` quotes "3/8 reproduce pass". The 4th pass, Raman, passes verify but its physics is wrong: the 532 nm line goes through to the CCD (see `RESULTS.md`). Say "4/8 pass verification, 3/8 physically correct", or use whichever count the text adopts.

## 5. `grounding.pdf` (column), from `fig_grounding.py`

**Caption.** Share of PyOpticL API references in gemini-4-argon goal→code output that do not exist.

| Condition | Run | Invalid | Valid / invalid refs |
|---|---|---|---|
| Zero-shot | AOM, low thinking | 94.7 % | 1 / 18 |
| Zero-shot | AOM, high thinking | 98.1 % | 1 / 52 |
| Zero-shot | SAS, low thinking | 97.7 % | 1 / 42 |
| Grounded (~17k tokens of real designs + signature digest) | 4 runs | 0 % | 135/0, 140/0, 130/0, 129/0 (the last is figure 2a + grounding) |

**Source.** `experiments/argon_probe/FINDINGS.md` table, cross-checked against `experiments/argon_probe/runs/*.check.json` and `runs/calls.jsonl`.

## 6. `scaling.pdf` (column), from `fig_scaling.py` (writes `scaling_data.json`)

**Caption.** Deterministic trace + verify wall time against design size, median of 5 runs (bars show min–max).
- **Blue:** `aom_doublepass_fixed` (11 elements) tiled $N=1$–33 times with the module merger. That gives 11–363 elements and 16–528 beam segments. Every tiled design passes verification (score 97.9). Time rises from 0.4 ms to 104.6 ms, an empirical log–log slope of about 1.6.
- **Orange:** the 13 example designs (5–121 elements) take at most 0.84 ms each, except the 121-element Sr$^+$ apparatus at 9.6 ms.

**Source.** Measured on macOS arm64 by timing `optics.trace` + `optics.verify`, with `optics.merge.merge_modules` used for tiling.

**Note.** The measurements ran while other jobs were active, so absolute times have about ±2× load noise (an earlier run gave 188 ms at 363 elements). `DEMO.md` quotes 6.1 ms for the 121-element apparatus on an idle machine.

## 7. `tuning.pdf` (column), from `fig_tuning.py` (writes `tuning_data.json`)

**Caption.** Deterministic re-alignment after a seeded random misalignment (seed 1: waveplates 8–25°, lens distances 8–20 %, mirrors 0.2–0.8°). Panel (a) shows the best-so-far tuning objective against trial. Panel (b) shows delivered power as a percentage of the as-designed value.

| Example | Delivered power before → after | % of design | Objective | Trials |
|---|---|---|---|---|
| `fiber_coupling_telescope` | 1.09 → 9.82 mW | 11 % → 102 % (9.64 mW) | 0.75 → 3.20 | 63 |
| `aom_doublepass_fixed` | 3.73 → 12.06 mW | 32 % → 102 % (11.80 mW) | 2.50 → 4.05 | 75 |
| `rb_sas` | 18.32 → 18.00 mW (design 18.07 mW) | essentially unchanged | 2.77 → 3.18 | 67 |

For `rb_sas`, the misalignment degraded only the target and polarization terms, which is why panel (a) plots the objective.

**Source.** `optics.tune.detune(seed=1)` followed by `optics.tune.tune(objective="auto", max_steps=160)`.

## 8. `logic_truth.pdf` (column), from `fig_logic.py` (writes `logic_truth.json`)

**Caption.**
- **(a)** All-optical half adder on a single PPLN crystal. The inputs are A = 1064 nm at 218.5 mW and B = 1550 nm at 150 mW.
  - SUM (residual IR) is 0, 150.0, 218.5 and 21.1 mW for inputs 00/01/10/11.
  - CARRY (631 nm sum-frequency light) is 0 except at 11, where it is 347.4 mW.
  - With a 40 mW threshold all four rows are correct and the design passes verify.
- **(b)** Sum-frequency AND gate with 50 mW per input: OUT = 35.3 mW only for input 11, and 0 otherwise (threshold 0.5 mW).

**Source.** `logic.truth_table` in `backend/logic.py`, run on `backend/examples/alloptical_half_adder.json` and `alloptical_and_sfg.json`.

## 9. `gallery.pdf` (full width), from `fig_gallery.py`

**Caption.** Artifacts produced by BEAMTEAM:
- **(a)** An open-access setup figure: dual-trap optical tweezers, arXiv:2411.16256, CC BY 4.0.
- **(b)** The fly-in, where the figure floats above the bench as its parts are placed.
- **(c)** The 121-element, 7-module Sr$^+$ ion-trap apparatus traced by the deterministic tracer (134 beam segments, verify score 99.2, PASS).
- **(d)** The agent console streaming tokens from parallel agents.
- **(e)** Journal-cover renders: faithful (gemini-3.1-flash-image) and cinematic (gemini-nano-banana-2.1).
- **(f)** The build kit's printable keyed baseplate tiles.

**Source.**
- (a) `demo/figures/dual_trap_tweezers.png`
- (b) `web/screenshots/flyin_mid.png`
- (c) a live `optics.trace` + `optics.verify` run on `backend/examples/sr_ion_apparatus.json`
- (d) `web/screenshots/token_streams.png`
- (e) `demo/covers/gemini-3.1-flash-image_1.png` and `demo/covers/gemini-nano-banana-2.1_1.png`
- (f) `web/screenshots/build_kit_print.png`

**Note.** Panel (a) is arXiv:2411.16256, a different paper from the arXiv:2004.05246 tweezers figure used in Fig. 2 and the 73 s paper-URL run.

## 10. `planview_apparatus.pdf` (full width), from `fig_planview.py`

**Caption.** Plan view of the hierarchical Sr$^+$ ion-trap laser apparatus, drawn directly from the deterministic trace.
- **Size:** 121 elements, 11 sources, 134 beam segments and 6 wavelengths (405, 421.7, 460.9, 674, 1033 and 1091.8 nm).
- **Layout:** the 1200 × 900 mm table is split into 7 module regions (dashed):
  - 422 nm cooling/detection
  - 405 nm photoionization
  - 422 nm Raman beams
  - 461 nm photoionization + lock
  - 1092 nm repump
  - 1033 nm quench
  - 674 nm SPAM/qubit
- **Encoding:** beam colour shows wavelength and line width scales with √power.
- **Result:** the design passes verification (score 99.2), with all elements placed and 236.9 of 280.0 mW input delivered.

**Source.** `backend/examples/sr_ion_apparatus.json` → `optics.trace` + `optics.verify`.

**Note.** This figure uses its own wavelength-ordered palette instead of `style.wavelength_color`, because 1033 nm and 1092 nm would otherwise both come out dark red.
