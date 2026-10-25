"""grounding.pdf: API-hallucination rate of gemini-4-argon generating PyOpticL code,
zero-shot vs grounded. Data: experiments/argon_probe/runs/*.check.json (= FINDINGS.md table)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import style
from style import plt, C, COL_W
RUNS = os.path.abspath(os.path.join(style.ROOT, "..", "experiments", "argon_probe", "runs"))
order = [("e1a_zeroshot_aom_low", "AOM, low", 0), ("e1a_zeroshot_aom_high", "AOM, high", 0),
         ("e1c_zeroshot_sas_low", "SAS, low", 0),
         ("e1b_grounded_aom_low", "AOM, low", 1), ("e1d_grounded_sas_low", "SAS, low", 1),
         ("e1d_grounded_sas_high", "SAS, high", 1), ("e2c_fig2_sas_code", "Fig. 2a + SAS, high", 1)]
rows = []
for k, lab, g in order:
    d = json.load(open(os.path.join(RUNS, k + ".check.json")))
    rows.append((lab, g, d["n_refs_ok"], d["n_refs_bad"], d["hallucination_rate"]))
    print(k, d["n_refs_ok"], d["n_refs_bad"], d["hallucination_rate"])
fig, ax = plt.subplots(figsize=(COL_W, 1.9))
ys = list(range(len(rows)))[::-1]
for y, (lab, g, ok, bad, hr) in zip(ys, rows):
    col = C["green"] if g else C["red"]
    ax.barh(y, hr * 100, color=col, height=0.62)
    ax.text(max(hr * 100, 0) + 1.5, y, f"{hr*100:.1f}%  ({ok} ok / {bad} bad)", va="center", fontsize=6)
ax.set_yticks(ys, [r[0] for r in rows])
ax.set_xlim(0, 135); ax.set_xticks([0, 25, 50, 75, 100])
ax.set_xlabel("hallucinated API references (%)")
ax.axhline(3.5, color=C["light"], lw=0.8)
ax.text(128, 6.75, "zero-shot", ha="right", va="center", color=C["red"], fontsize=7); ax.set_ylim(-0.5, 7.1)
ax.text(128, 1.5, "grounded\n(~17k-token context\nof real designs)", ha="right", va="center", color=C["green"], fontsize=7)
style.save(fig, "grounding.pdf")
