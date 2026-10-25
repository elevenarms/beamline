"""Fig 6: trace+verify wall time vs element count (measured, median of 5)."""
import glob, json, os, statistics, sys, time
sys.path.insert(0, os.path.dirname(__file__))
import style
from style import plt, C, COL_W, save
BK = os.path.join(style.ROOT, "backend"); sys.path.insert(0, BK)
from optics.ir import Design, Module, Baseplate
from optics.trace import trace
from optics.verify import verify
from optics.merge import merge_modules

REPS = 5
def timeit(d):
    ts = []
    for _ in range(REPS):
        t0 = time.perf_counter(); tr = trace(d); rep = verify(d, tr); ts.append(time.perf_counter() - t0)
    return statistics.median(ts), min(ts), max(ts), rep, tr

def tiled(base, n, cols=4):
    w, h = base.baseplate.width_mm, base.baseplate.height_mm
    rows = (n + cols - 1) // cols
    parts = [(Module(id=f"m{i}", region=((i % cols) * w, (i // cols) * h, w, h)), base) for i in range(n)]
    table = base.baseplate.model_copy(update={"width_mm": min(n, cols) * w, "height_mm": rows * h})
    return merge_modules(f"tiled x{n}", "", table, parts)

out = {"reps": REPS, "examples": [], "tiled": []}
for f in sorted(glob.glob(os.path.join(BK, "examples", "*.json"))):
    d = Design.model_validate_json(open(f).read())
    med, lo, hi, rep, tr = timeit(d)
    out["examples"].append(dict(name=os.path.basename(f)[:-5], n_elements=len(d.elements),
                                n_segments=len(tr.segments), median_s=med, min_s=lo, max_s=hi, passed=rep.passed))
base = Design.model_validate_json(open(os.path.join(BK, "examples", "aom_doublepass_fixed.json")).read())
for n in [1, 2, 3, 5, 8, 12, 16, 24, 33]:
    d = tiled(base, n)
    med, lo, hi, rep, tr = timeit(d)
    out["tiled"].append(dict(copies=n, n_elements=len(d.elements), n_segments=len(tr.segments),
                             median_s=med, min_s=lo, max_s=hi, passed=rep.passed, score=rep.score))
    print(n, len(d.elements), len(tr.segments), f"{med*1000:.1f} ms", rep.passed, round(rep.score, 1))
import platform
out["machine"] = platform.platform() + " " + platform.processor()
json.dump(out, open(os.path.join(os.path.dirname(__file__), "scaling_data.json"), "w"), indent=1)

fig, ax = plt.subplots(figsize=(COL_W, 2.4))
T = out["tiled"]
x = [t["n_elements"] for t in T]; y = [t["median_s"] * 1e3 for t in T]
ax.errorbar(x, y, yerr=[[ (t["median_s"]-t["min_s"])*1e3 for t in T], [(t["max_s"]-t["median_s"])*1e3 for t in T]],
            fmt="o-", color=C["blue"], ms=3.5, capsize=1.5, lw=1, label="AOM double-pass tiled ×N (merge)")
E = out["examples"]
ax.scatter([e["n_elements"] for e in E], [e["median_s"] * 1e3 for e in E], marker="D", s=14,
           color=C["orange"], zorder=3, label="hand/agent examples")
for e in E:
    if e["name"] in ("sr_ion_apparatus", "optical_full_adder"):
        ax.annotate(e["name"].replace("_", " "), (e["n_elements"], e["median_s"] * 1e3),
                    xytext=(-6, 5), ha="right", textcoords="offset points", fontsize=6, color=C["orange"])
ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlabel("elements in design"); ax.set_ylabel("trace + verify time (ms)")
ax.grid(True, which="major", color=C["light"], lw=0.5)
ax.legend(loc="upper left")
save(fig, "scaling.pdf")
