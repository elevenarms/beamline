# Showcase figures: stress-test results

Run on 2026-10-25, 12:00–12:20 PDT. Figures, licenses and design goals are in `catalog.json`. Raw SSE streams are in `runs/`, and the parsed summary is in `runs/summary.json`.

**Infra note:** 10 early runs against `:8000` were cut off after 7–80 s with no `final` or `error` event. The cause was `uvicorn --reload` restarting whenever another builder saved a backend file. Those runs are marked **aborted (infra)** and are kept in `runs/aborted_reload/`. They are not counted as failures. The reruns used a non-reloading server (a private `:8011`, then the coordinator's `:8001`). That gives 14 completed runs: 8 reproduce attempts (Yb tried twice) and 4 design runs, plus 2 more reproduce runs that finished on `:8000` before the reloads hit.

## Results

| Figure | Diff. | Reproduce: time / score / pass / #el | Design: time / score / pass / #el | Notable failures |
|---|---|---|---|---|
| raman_backscatter (CC BY 4.0) | easy | 46 s / 96 / **pass** / 12 | – | Sample modelled as a `mirror`. The long-pass "filter" is a `dichroic` with `cutoff 500, reflect below`, so the **532 nm laser line goes through to the CCD** (12.5 mW). It passes, but the physics is wrong. |
| pump_probe_delay (CC0) | easy | 55 s / 100 / **pass** / 8 | – | First synth: `stray beam … Laser.t (50 mW) leaves the table`. Repair round 1 then scored 0: `mirror M_pump1: out_direction_deg 0.0 equals the incoming direction`. Fixed in round 2. |
| pdh_thin_disk_lock (CC BY 4.0) | medium | 41 s / 95 / **pass** / 9 | 52 s / 100 / **pass** / 14 | Clean in both modes. The resonator is not modelled (no cavity element), so the seed "returns" via fold optics. |
| sr_ion_trap_lasers (CC BY 4.0) | medium | 104 s / **0** / fail / 27 (7 sources) | 68 s / 75 / pass / 21 | Reproduce: 9 × `laser safety: unterminated beam on L_422.t.r.+1.t (9.72 mW) leaves the table`. Every AOM order and sampler port was left open, and `time budget reached, stopping repair` came before any repair. Design: `beam L_422.t passes through DM_WEST's mount without interacting`, plus `HWP_422 and DM_WEST footprints overlap`. |
| mot_lcvr_laser_system (CC BY 4.0) | medium | 90 s / **0** / fail / 22 | aborted (infra) | `M3: branch 'ECDL2.+1' absorbed at BD2 before this element was reached`, then 14 cascaded `branch 'ECDL2.+1.t' never existed`. The dump was put on the diffracted order and the optics were then placed on it. The aborted try made TA1/TA2 `soa` with 50 mW seeds against 120 mW fiber targets, and its labels contained paragraphs of reasoning. |
| dual_trap_tweezers (CC BY 4.0) | hard | 80 s / 96 / **pass** / 22 | 84 s / 99.5 / **pass** / 58 | Reproduce: the topology is right (L1/L2 → HWP → PBS1 → 2 TTM arms → PBS2 → L3/L4 → DM → obj), but the QPDs pick off the **forward** beam rather than back-scatter. Focal lengths from the notes were ignored (L3/L4 250/500 became 125/125, L5/L6 250 became 150), and 3 W became 100 mW. Design: built as 4 modules with **4 separate sources** (3000 + 1800 + 900 + 40 mW) joined by "fiber launches", so it is not one beam path. |
| hom_tomography (CC BY 4.0, 3D render) | hard | 119 s / **18** / fail / 41 | – | Vision took 75.6 s and the server log shows `LLM merge failed ()`. Result: `FC_out1: 16.3% clipped (beam radius 3.15 mm)` and `unmet: FC_out1: 0.011 mW`. Sources were modelled as fiber inputs, and the time budget ran out before repair. |
| yb_ion_clock_laser (CC BY 4.0, dense) | hard | **error** ×2: `LLMError: all vision extraction passes failed: ` at 60 s | – | `EXTRACT_HARD_S = 60` cancels all 3 vision passes on a dense figure. The error text is empty because nothing raised; the passes were just cancelled. |
| maldi_ion_source (goal only, no figure) | medium | – | 50 s / 99 / **pass** / 32 | 3 modules with 3 sources (153 mW total input), linked by fiber couplers. The MALDI "target" is `FC_target`, a fiber coupler, instead of a focused spot on a sample. |

## Failure patterns to fix in the prompts and pipeline

1. **Stray ports and the time budget on multi-laser figures.** On sr_ion_trap the synth left every AOM 0/±1 order and every sampler `.r` port unterminated (9 `stray_beam` errors). The 75 s budget was then used up before a single repair round (`time budget reached, stopping repair`). The same thing happened on HOM and MOT. Suggested fixes:
   - Add a deterministic post-pass that auto-appends `beam_dump`s to unterminated branches before verify.
   - Add a prompt rule: "every splitter/AOM output port must end in a terminating element".
   - Scale the time budget with the number of sources.
2. **Branch-topology errors around AOMs and dumps.** The model puts the dump on `.+1` and then places downstream optics on `ECDL2.+1` (`absorbed at BD2 before this element was reached`). It also invents branches (`'L1.t.r.r.t' never existed`, `'VisIllum.t' never existed`), and one error cascades into about 15. Suggested fixes:
   - Feed the list of existing branches and the AOM-order convention into synth.
   - On a missing branch, have the repair prompt suggest the nearest existing branch name.
3. **No "sample" or retro-scatter primitive, so the physics gets faked.** Raman puts the laser line on the CCD. Tweezers QPDs detect the forward beam. MALDI and tweezers designs end on `fiber_coupler`s. The verifier scores all of these ≥95. Suggested fixes:
   - Add a `sample`/`scatterer` element that terminates the beam and optionally re-emits a weak, shifted beam backwards.
   - Or add a verifier check for "detector receives the excitation wavelength through a filter".
4. **Hierarchical design produces disconnected modules.** The tweezers and MALDI designs have one source per module (input 5740 mW for a 3 W laser). The merge should chain module outputs into the next module's input instead of adding new sources.
5. **Notes are not respected.** Numeric parameters given in the notes (focal lengths, 3 W) were replaced with "convenient" values. Echo the parsed parameters into the synth prompt as hard constraints, and add a diff check.
6. **Dense or 3D figures.** The 60 s vision deadline kills dense ComponentLibrary figures (Yb+). Raise `EXTRACT_HARD_S` or tile the image. Also surface `TimeoutError` text instead of an empty string.

## Demo recommendation

- **dual_trap_tweezers (reproduce)**: a hard, 22-element figure with a correct split/recombine topology that passes at 96 in about 80 s. It is impressive and has been reliable once.
- **pdh_thin_disk_lock**: passes in both reproduce (95, 41 s) and design (100, 52 s). It is the safe fallback.
- Avoid Yb+, HOM, MOT and sr_ion reproduce live. Run them on `:8001`, never on the reloading `:8000`.
