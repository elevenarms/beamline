"""Fig: verifier score vs. iteration for real runs (from `iteration` + `final` SSE events).

Each marker is one design the deterministic verifier scored, in emission order;
shape = how it was produced (LLM synthesizer/designer, deterministic autofix, LLM
repair). The line is the best-so-far score, which is what the pipeline keeps
(the `final` event's design is the best-scoring candidate).
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import style
from style import C, plt
import sse

RUNS = [("demo/reliability/rb_sas_1.sse", "Rb SAS #1", C["blue"]),
        ("demo/reliability/rb_sas_2.sse", "Rb SAS #2", C["cyan"]),
        ("demo/reliability/rb_sas_3.sse", "Rb SAS #3", C["purple"]),
        ("demo/live_cc_by_sas.sse", "CC-BY SAS fig.", C["brown"]),
        ("demo/console_reproduce_url_tweezers.sse", "tweezers A", C["green"]),
        ("demo/live_tweezers_check.sse", "tweezers B", C["orange"]),
        ("demo/console_design.sse", "goal-to-design (4 designers)", C["red"])]
MARK = {"synth": "o", "autofix": "^", "repair": "s", "designer": "D"}


def kind(it):
    lab = it["label"]
    if lab == "autofix": return "autofix"
    if lab.startswith("repair"): return "repair"
    if it["agent_id"].startswith("designer"): return "designer"
    return "synth"

fig, ax = plt.subplots(figsize=(style.COL_W, 2.5))
rows = []
for path, name, col in RUNS:
    ev = sse.read(os.path.join(style.ROOT, path))
    its = [e for e in ev if e.get("type") == "iteration"]
    final = [e for e in ev if e.get("type") == "final"][0]["report"]["score"]
    xs = list(range(1, len(its) + 1)); ys = [e["report"]["score"] for e in its]
    best, b = [], -1
    for y in ys:
        b = max(b, y); best.append(b)
    ax.step(xs + [len(its) + 1], best + [final], where="post", color=col, lw=1.1, alpha=0.9,
            label=f"{name} ({final:.0f})")
    for x, e, y in zip(xs, its, ys):
        k = kind(e)
        ax.scatter(x, y, marker=MARK[k], s=16, fc="white" if not e["report"]["passed"] else col,
                   ec=col, lw=0.8, zorder=3)
    ax.scatter(len(its) + 1, final, marker="*", s=40, color=col, zorder=4, ec="none")
    rows.append((name, [round(y, 1) for y in ys], round(final, 1)))
ax.set_xlabel("iteration (verifier call, in order)")
ax.set_ylabel("verifier score (0–100)")
ax.set_ylim(-4, 104); ax.set_xlim(0.6, 9.4)
ax.set_xticks(range(1, 10))
from matplotlib.lines import Line2D
kh = [Line2D([], [], ls="", marker=MARK[k], mfc="white", mec=C["ink"], ms=4, label=l)
      for k, l in [("synth", "synthesizer"), ("designer", "designer"), ("autofix", "autofix"), ("repair", "repair")]]
kh += [Line2D([], [], ls="", marker="*", color=C["ink"], ms=6, label="final")]
l1 = ax.legend(handles=kh, loc="lower left", bbox_to_anchor=(1.0, -0.02), fontsize=5.8, ncol=1, handletextpad=0.3, borderaxespad=0.2,
               title="filled = passed\nhollow = failed", title_fontsize=5.5)
ax.add_artist(l1)
ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.02), fontsize=5.8, handlelength=1.2, title="run (final)",
          title_fontsize=6)
style.save(fig, "scores_iterations.pdf")
for r in rows: print(r)
