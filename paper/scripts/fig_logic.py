"""logic_truth.pdf: all-optical half adder (PPLN SFG) truth table + SFG AND gate.
Powers come from running backend/logic.py truth_table() on the example designs."""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import style
from style import plt, C, COL_W, wavelength_color
BACK = os.path.join(style.ROOT, "backend"); sys.path.insert(0, BACK)
import logic

ha = os.path.join(BACK, "examples", "alloptical_half_adder.json")
an = os.path.join(BACK, "examples", "alloptical_and_sfg.json")
rows_ha = logic.truth_table(ha, ["A", "B"], ["SUM", "CARRY"])
rows_an = logic.truth_table(an, ["A", "B"], ["OUT"])
thr_ha = logic.threshold_mw(logic.load(ha)); thr_an = logic.threshold_mw(logic.load(an))
out = {"half_adder": rows_ha, "and_sfg": rows_an, "thr_ha": thr_ha, "thr_and": thr_an}
json.dump(out, open(os.path.join(os.path.dirname(__file__), "logic_truth.json"), "w"), indent=1)

labels = [f"{r['inputs']['A']}{r['inputs']['B']}" for r in rows_ha]
fig, (a1, a2) = plt.subplots(1, 2, figsize=(COL_W, 1.75), gridspec_kw=dict(width_ratios=[1.6, 1], wspace=0.45))
import numpy as np
x = np.arange(4); w = 0.38
ir, red = C["purple"], wavelength_color(631)
s = [r["powers_mw"]["SUM"] for r in rows_ha]; c = [r["powers_mw"]["CARRY"] for r in rows_ha]
a1.bar(x - w/2, s, w, color=C["grey"], label="SUM (residual IR)")
a1.bar(x + w/2, c, w, color=red, label="CARRY (631 nm SFG)")
a1.axhline(thr_ha, color=C["ink"], lw=0.6, ls="--")
a1.text(-0.55, thr_ha + 6, f"threshold {thr_ha:g} mW", ha="left", va="bottom", fontsize=6)
for i, r in enumerate(rows_ha):
    for dx, k in ((-w/2, "SUM"), (w/2, "CARRY")):
        p = r["powers_mw"][k]
        a1.text(i + dx, p + 4, f"{p:.0f}" if p >= 1 else "0", ha="center", va="bottom", fontsize=5.5)
a1.set_xticks(x, labels); a1.set_xlabel("inputs A B"); a1.set_ylabel("photodiode power (mW)")
a1.set_title("(a) half adder (one PPLN)", loc="left")
a1.set_ylim(0, max(c) * 1.28)
a1.legend(loc="upper left", fontsize=6, handlelength=1)

o = [r["powers_mw"]["OUT"] for r in rows_an]
a2.bar(x, o, 0.55, color=red)
a2.axhline(thr_an, color=C["ink"], lw=0.6, ls="--")
for i, p in enumerate(o):
    a2.text(i, p + 0.8, f"{p:.1f}" if p >= 0.05 else "0", ha="center", va="bottom", fontsize=5.5)
a2.set_xticks(x, labels); a2.set_xlabel("inputs A B"); a2.set_ylabel("OUT power (mW)")
a2.set_title("(b) SFG AND", loc="left"); a2.set_ylim(0, max(o) * 1.25)
style.save(fig, "logic_truth.pdf")
for r in rows_ha + rows_an: print(r["inputs"], r["powers_mw"], r["outputs"], r["passed"])
