"""Fig 7: detune -> deterministic tune recovery (measured with optics.tune)."""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import style
from style import plt, C, COL_W, save
BK = os.path.join(style.ROOT, "backend"); sys.path.insert(0, BK)
from optics.ir import Design
from optics.trace import trace
from optics.verify import verify
from optics.tune import tune, detune

CASES = [("rb_sas", 1, C["blue"]), ("fiber_coupling_telescope", 1, C["orange"]), ("aom_doublepass_fixed", 1, C["green"])]
SEED = int(os.environ.get("SEED", 1))
res = {}
for name, seed, col in CASES:
    d0 = Design.model_validate_json(open(os.path.join(BK, "examples", name + ".json")).read())
    ref = verify(d0, trace(d0)).metrics.get("delivered_mw", 0.0)
    dd = detune(d0, SEED)
    ev = []
    async def emit(e): ev.append(e)
    asyncio.run(tune(dd, emit))
    base = ev[0]["baseline"]; fin = ev[-1]
    best_obj, best_mw = base["objective"], base["delivered_mw"]
    obj, mw = [best_obj], [best_mw]
    for e in ev:
        if e["type"] == "tune_step":
            if e["best_so_far"]:
                best_obj, best_mw = e["objective"], e["metrics"].get("delivered_mw", best_mw)
            obj.append(best_obj); mw.append(best_mw)
    res[name] = dict(ref_mw=ref, detuned_mw=base["delivered_mw"], tuned_mw=fin["report"].metrics.get("delivered_mw", 0.0),
                     obj_before=fin["summary"]["objective_before"], obj_after=fin["summary"]["objective_after"],
                     steps=fin["summary"]["steps"], obj=obj, mw=mw, color=col, seed=SEED)
    print(name, {k: v for k, v in res[name].items() if k not in ("obj", "mw", "color")})
json.dump({k: {kk: vv for kk, vv in v.items() if kk != "color"} for k, v in res.items()},
          open(os.path.join(os.path.dirname(__file__), "tuning_data.json"), "w"), indent=1)

fig, (a1, ax) = plt.subplots(2, 1, figsize=(COL_W, 3.3), sharex=True, gridspec_kw=dict(hspace=0.12))
for name, r in res.items():
    a1.step(range(len(r["obj"])), r["obj"], where="post", color=r["color"], label=name.replace("_", " "))
    a1.plot(len(r["obj"]) - 1, r["obj"][-1], "o", color=r["color"], ms=3)
    y = [100 * m / r["ref_mw"] for m in r["mw"]]
    ax.step(range(len(y)), y, where="post", color=r["color"])
    ax.plot(len(y) - 1, y[-1], "o", color=r["color"], ms=3)
a1.set_ylabel("tuning objective")
a1.legend(loc="lower right")
a1.grid(True, color=C["light"], lw=0.5)
ax.axhline(100, color=C["grey"], lw=0.6, ls="--")
ax.text(1, 103, "as-designed", fontsize=6, color=C["grey"])
ax.set_xlabel("tuning trial (trace + verify evaluations)")
ax.set_ylabel("delivered power\n(% of design)")
ax.grid(True, color=C["light"], lw=0.5)
for a, l in ((a1, "(a)"), (ax, "(b)")):
    a.text(-0.2, 1.0, l, transform=a.transAxes, fontsize=8, fontweight="bold", va="top")
save(fig, "tuning.pdf")
