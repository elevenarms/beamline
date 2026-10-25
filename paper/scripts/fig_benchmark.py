"""benchmark.pdf: 8-figure showcase benchmark (+1 goal-only design), reproduce and design modes.
Data: demo/figures/runs/summary.json (parsed from runs/*.sse); aborted-by-infra runs from
runs/aborted_reload/ are shown as such, not as failures."""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import style
from style import plt, C, COL_W
RUNS = os.path.join(style.ROOT, "demo", "figures", "runs")
S = json.load(open(os.path.join(RUNS, "summary.json")))
cat = {c["slug"]: c for c in json.load(open(os.path.join(style.ROOT, "demo", "figures", "catalog.json")))}
figs = ["raman_backscatter", "pump_probe_delay", "pdh_thin_disk_lock", "sr_ion_trap_lasers",
        "mot_lcvr_laser_system", "dual_trap_tweezers", "hom_tomography", "yb_ion_clock_laser",
        "maldi_ion_source_goal_only"]
short = {"raman_backscatter": "Raman", "pump_probe_delay": "pump-probe", "pdh_thin_disk_lock": "PDH lock",
         "sr_ion_trap_lasers": "Sr$^+$ lasers", "mot_lcvr_laser_system": "MOT/LCVR",
         "dual_trap_tweezers": "tweezers", "hom_tomography": "HOM", "yb_ion_clock_laser": "Yb$^+$ clock",
         "maldi_ion_source_goal_only": "MALDI*"}
def diff(f):
    return cat.get(f, {}).get("difficulty", "medium")  # MALDI: medium per RESULTS.md
fig, axes = plt.subplots(1, 2, figsize=(COL_W, 2.6), sharey=True, gridspec_kw=dict(wspace=0.08))
ys = list(range(len(figs)))[::-1]
for ax, mode, title in ((axes[0], "reproduce", "reproduce (figure)"), (axes[1], "design", "design (goal)")):
    for y, f in zip(ys, figs):
        r = S.get(f"{f}.{mode}.sse")
        aborted = os.path.exists(os.path.join(RUNS, "aborted_reload", f"{f}.{mode}.sse"))
        if r is None:
            if aborted:
                ax.text(2, y, "aborted (infra)", va="center", fontsize=5.5, color=C["grey"], style="italic")
            else:
                ax.text(2, y, "–", va="center", fontsize=6, color=C["grey"])
            continue
        t = float(r["wall_s"])
        if r.get("errors"):
            ax.barh(y, t, color="white", edgecolor=C["red"], hatch="////", lw=0.6, height=0.62)
            ax.text(t + 2, y, "error ×2" if f == "yb_ion_clock_laser" else "error", va="center", fontsize=5.5, color=C["red"])
            continue
        ok = r["passed"]
        ax.barh(y, t, color=C["green"] if ok else C["red"], alpha=0.85, height=0.62)
        ax.text(t + 2, y, f"{r['score']:.0f}", va="center", fontsize=5.5,
                color=C["ink"] if ok else C["red"])
    ax.set_title(title, fontsize=7.5); ax.set_xlim(0, 150); ax.set_xticks([0, 50, 100])
    ax.set_xlabel("wall time (s)")
axes[0].set_yticks(ys, [f"{short[f]} ({diff(f)[0]})" for f in figs])
from matplotlib.patches import Patch
axes[1].legend(handles=[Patch(color=C["green"], alpha=.85, label="pass"), Patch(color=C["red"], alpha=.85, label="fail"),
                        Patch(facecolor="white", edgecolor=C["red"], hatch="////", label="pipeline error")],
               loc="lower right", fontsize=5.5, handlelength=1.2)
style.save(fig, "benchmark.pdf")
