"""Fig: per-agent Gantt timeline of two real tweezers reproduce-from-figure runs.

The SSE streams carry no wall-clock timestamps; each `agent` done event carries its
own measured elapsed_ms and the `done` status carries the stage timings
(extract_s, synth_s, repair_s, total_s). Agents in a stage start together (they are
launched in parallel), so stage start = cumulative sum of earlier stage timings.
TTFT and token counts come from the `llm_call` events; tool ticks/scores from
`tool` / `iteration` events (tools run after the LLM call returns, <2 ms each).
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import style
from style import C, plt
import sse
from matplotlib.patches import Rectangle

RUNS = [("demo/console_reproduce_url_tweezers.sse", "(a) run A"),
        ("demo/live_tweezers_check.sse", "(b) run B")]
ROLE_COL = {"vision": C["blue"], "merge": C["grey"], "synth": C["green"],
            "repair": C["orange"], "matcher": C["grey"]}
DET_ROLES = {"merge", "matcher"}


def parse(path):
    ev = sse.read(os.path.join(style.ROOT, path))
    done = [e for e in ev if e.get("type") == "status" and e.get("stage") == "done"][0]
    T = done["timings"]
    agents, order = {}, []
    for e in ev:
        if e.get("type") == "agent":
            a = agents.setdefault(e["agent_id"], dict(role=e["role"], title=e["title"], tools=[], its=[]))
            if e["agent_id"] not in order:
                order.append(e["agent_id"])
            if e["state"] == "done":
                a["dur"] = (e["elapsed_ms"] or 0) / 1000
        elif e.get("type") == "llm_call":
            agents[e["agent_id"]]["llm"] = e
        elif e.get("type") == "tool":
            agents[e["agent_id"]]["tools"].append(e)
        elif e.get("type") == "iteration":
            agents[e["agent_id"]]["its"].append((e["label"], e["report"]["score"], e["report"]["passed"]))
    # stage starts from measured stage timings
    t_syn = T["extract_s"]; t_rep = t_syn + T["synth_s"]
    rep_t = t_rep
    for aid in order:
        a = agents[aid]
        r = a["role"]
        if r == "vision": a["t0"] = 0.0
        elif r in ("merge",): a["t0"] = T["extract_s"]
        elif r == "synth": a["t0"] = t_syn
        elif r == "repair":
            a["t0"] = rep_t; rep_t += a["dur"]
        elif r == "matcher": a["t0"] = T["total_s"]
    return agents, order, T, done["message"]


def draw(ax, path, label):
    agents, order, T, msg = parse(path)
    n = len(order)
    for i, aid in enumerate(order):
        a = agents[aid]; y = n - 1 - i
        col = ROLE_COL[a["role"]]
        det = a["role"] in DET_ROLES
        w = max(a["dur"], 0.35)  # deterministic stages take <1 ms: draw a visible sliver
        if det:
            ax.add_patch(Rectangle((a["t0"], y - 0.3), w, 0.6, fc=style.DET, ec=style.DET_EDGE, lw=0.6))
        else:
            ttft = a["llm"]["ttft_ms"] / 1000
            ax.add_patch(Rectangle((a["t0"], y - 0.3), ttft, 0.6, fc=col, alpha=0.35, ec="none"))
            ax.add_patch(Rectangle((a["t0"] + ttft, y - 0.3), a["dur"] - ttft, 0.6, fc=col, alpha=0.85, ec="none"))
        # tool ticks at end of agent
        tend = a["t0"] + a["dur"]
        if a["tools"]:
            ax.plot([tend, tend], [y - 0.42, y + 0.42], color=C["ink"], lw=0.9)
        # annotation text right of the bar
        bits = []
        if "llm" in a:
            bits.append(f"{a['dur']:.1f} s, {a['llm']['output_tokens']} out tok")
        if a["its"]:
            bits.append(" > ".join(f"{lab.replace('synthesized design', 'synth')}: {s:.0f}" + ("" if p else " (fail)")
                                         for lab, s, p in a["its"]))
        elif a["tools"] and det:
            bits.append(a["tools"][-1]["summary"].split(":")[0] if a["role"] == "matcher" else "vote + scale to mm")
        if a["role"] == "matcher":
            bits = [a["tools"][0]["summary"].replace("match: ", "")]
        ax.text(tend + 1.0, y, "   ".join(bits), va="center", ha="left", fontsize=6, color=C["ink"])
    names = []
    for aid in order:
        names.append(aid.replace("vision-", "Vision ").replace("synth-", "Synth ").replace("repair-", "Repair ")
                     .replace("merge", "Merge").replace("matcher", "Matcher"))
    ax.set_yticks(range(n)); ax.set_yticklabels(names[::-1])
    ax.set_ylim(-0.7, n + 0.2)
    # stage boundaries
    b = [T["extract_s"], T["extract_s"] + T["synth_s"], T["total_s"]]
    for x in b:
        ax.axvline(x, color=C["grey"], lw=0.5, ls=(0, (2, 2)), zorder=0)
    for x0, x1, name in [(0, b[0], f"extract {T['extract_s']} s"), (b[0], b[1], f"synthesize {T['synth_s']} s"),
                         (b[1], b[2], f"repair {T['repair_s']} s")]:
        ax.text((x0 + x1) / 2, n - 0.3, name, ha="center", va="bottom", fontsize=6.5, color=C["grey"])
    final = msg.split("—")[-1].strip().replace("passed=True", "PASS").replace("passed=False", "FAIL")
    ax.set_title(f"{label}: total {T['total_s']} s, final {final}", loc="left", fontsize=7.5, pad=10)
    return T["total_s"]


fig, axes = plt.subplots(2, 1, figsize=(style.FULL_W, 4.3), sharex=True,
                         gridspec_kw=dict(height_ratios=[8, 9], hspace=0.35))
for ax, (p, lab) in zip(axes, RUNS):
    draw(ax, p, lab)
axes[-1].set_xlabel("time since figure received (s)")
axes[-1].set_xlim(0, 160)
for ax in axes:
    ax.spines["left"].set_visible(False); ax.tick_params(axis="y", length=0)
# legend
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
h = [Patch(fc=C["blue"], alpha=0.85, label="vision agent (LLM)"),
     Patch(fc=C["green"], alpha=0.85, label="synthesizer (LLM)"),
     Patch(fc=C["orange"], alpha=0.85, label="repair agent (LLM)"),
     Patch(fc="#999999", alpha=0.35, label="time to first token"),
     Patch(fc=style.DET, ec=style.DET_EDGE, lw=0.6, label="deterministic code"),
     Line2D([], [], color=C["ink"], lw=0.9, label="trace + verify (+ autofix) tools")]
fig.legend(handles=h, loc="lower center", ncol=6, bbox_to_anchor=(0.5, -0.04), fontsize=6.3,
           handlelength=1.2, columnspacing=1.0)
style.save(fig, "timeline_tweezers.pdf")
