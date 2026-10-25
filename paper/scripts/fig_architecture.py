"""Fig. 1: Beamline system architecture (LLM agents vs deterministic code).
Agent roles/names follow CONTRACT.md and backend/agents/*.py (reproduce.py, design.py, hierarchical.py, cover.py)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import style
from style import plt, C, LLM, LLM_EDGE, DET, DET_EDGE
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

W, H = style.FULL_W, 4.05
fig = plt.figure(figsize=(W, H))
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
FS = 6.3

def box(x, y, w, h, text, kind="det", stack=0, fs=FS, bold_first=True):
    fc, ec = (LLM, LLM_EDGE) if kind == "llm" else (DET, DET_EDGE) if kind == "det" else ("white", "#999999")
    pad = 0.0
    style_ = "round,pad=0,rounding_size=0.07" if kind == "llm" else "square,pad=0"
    for k in range(stack, 0, -1):
        d = 0.045 * k
        ax.add_patch(FancyBboxPatch((x + d, y - d), w, h, boxstyle=style_, fc=fc, ec=ec, lw=0.6, zorder=2))
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=style_, fc=fc, ec=ec, lw=0.8,
                                ls="-" if kind != "io" else (0, (2, 1.5)), zorder=3))
    lines = text.split("\n")
    if bold_first and len(lines) > 1:
        n = len(lines) - 1
        ax.text(x + w/2, y + h - 0.13, lines[0], ha="center", va="center",
                fontsize=fs, weight="bold", zorder=4, color=C["ink"])
        ax.text(x + w/2, y + (h - 0.22)/2 + 0.01, "\n".join(lines[1:]), ha="center", va="center",
                fontsize=fs-0.8, zorder=4, color="#333333", linespacing=1.0)
    else:
        ax.text(x + w/2, y + h/2, text, ha="center", va="center", fontsize=fs, weight="bold", zorder=4)
    return (x, y, w, h)

def arrow(p, q, rad=0.0, color="#444444", ls="-", lw=0.8):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=6, lw=lw, color=color, ls=ls,
                                 connectionstyle=f"arc3,rad={rad}", zorder=1.5, shrinkA=0, shrinkB=0))

def line(pts, color="#444444"):
    xs, ys = zip(*pts); ax.plot(xs, ys, color=color, lw=0.8, zorder=1.5, solid_capstyle="butt")

R = lambda b: (b[0] + b[2], b[1] + b[3]/2)
L = lambda b: (b[0], b[1] + b[3]/2)
T = lambda b: (b[0] + b[2]/2, b[1] + b[3])
B = lambda b: (b[0] + b[2]/2, b[1])

def lane(y, text, x=0.05):
    ax.text(x, y, text, fontsize=6.6, style="italic", color=C["blue"], weight="bold", va="bottom")

bh = 0.5
# ── lane 1: reproduce from a paper figure ──
y1 = 3.12; lane(y1 + bh + 0.08, "Reproduce from a paper figure  (/api/reproduce_url)")
s  = box(0.05, y1, 0.74, bh, "Paper search\narXiv API + HTML\nfigure ranking", "det")
f  = box(0.93, y1, 0.66, bh, "Figure fetch\nallowlisted URL", "det")
v  = box(1.73, y1, 0.74, bh, "Vision agents\n×3 parallel\ncomponent graph", "llm", stack=2)
m  = box(2.66, y1, 0.80, bh, "Consensus merge\n+ mm scaling\n(merge, scale)", "det")
sy = box(3.60, y1, 0.70, bh, "Synthesizers\n×2 parallel\ngraph to Design", "llm", stack=1)
for a, b_ in [(s, f), (f, v), (m, sy)]: arrow(R(a), L(b_))
arrow((R(v)[0] + 0.09, R(v)[1]), L(m))

# ── lane 2: design from a goal ──
y2 = 2.12; lane(y2 + bh + 0.08, "Design from a goal  (/api/design)", x=0.93)
g  = box(0.05, 1.10, 0.74, 1.52, "Goal (text)", "io")
p  = box(0.93, y2, 0.66, bh, "Planner\nrequirements,\nmodules, targets", "llm")
d  = box(1.73, y2, 0.74, bh, "Designers\n×N parallel\n(N = 4, ≤ 6)", "llm", stack=2)
arrow((R(g)[0], y2 + bh/2), L(p)); arrow(R(p), L(d))

# ── shared verify / repair block ──
vx, vw = 4.52, 1.12
ax.add_patch(FancyBboxPatch((vx - 0.06, 2.02), vw + 0.12, 1.72, boxstyle="round,pad=0,rounding_size=0.05",
                            fc="none", ec="#BBBBBB", lw=0.6, ls=(0, (3, 2)), zorder=0.5))
ax.text(vx + vw/2, 2.05, "verify–repair loop", ha="center", va="bottom", fontsize=5.8, color="#777777", style="italic")
t  = box(vx, y1, vw, bh, "Deterministic tools\ntrace · verify · autofix\n(optics/*.py)", "det")
rp = box(vx, y2, vw, bh, "Repair agent\n≤ 3 rounds,\nreads verify report", "llm")
arrow((R(sy)[0] + 0.05, R(sy)[1]), L(t))
arrow((R(d)[0] + 0.09, R(d)[1] + 0.05), (vx, y1 + 0.12), rad=0.0)
ax.text(3.35, 2.55, "best-of-N\ncandidates", fontsize=5.4, color="#555555", ha="center", va="center", rotation=0)
arrow((vx + 0.35, y1), (vx + 0.35, y2 + bh), color=C["red"])
arrow((vx + vw - 0.35, y2 + bh), (vx + vw - 0.35, y1), color=C["green"])
ax.text(vx + 0.31, (y1 + y2 + bh)/2, "FAIL\nchecks", fontsize=5.2, color=C["red"], ha="right", va="center")
ax.text(vx + vw - 0.31, (y1 + y2 + bh)/2, "patched\ndesign", fontsize=5.2, color=C["green"], ha="left", va="center")

# ── lane 3: hierarchical ──
y3 = 1.10; lane(y3 + bh + 0.08, "Hierarchical apparatus  (architect + modules)", x=0.93)
ar = box(0.93, y3, 0.66, bh, "Architect\nmodules, lasers,\nfiber links", "llm")
mo = box(1.73, y3, 1.44, bh, "Module agents  ×M parallel\n2 candidates + verify/repair\nper module", "llm", stack=2)
mb = box(3.36, y3, 0.94, bh, "Merge + power\nbudget\n(compute/enforce)", "det")
tv = box(vx, y3, vw, bh, "trace · verify\nwhole apparatus", "det")
arrow((R(g)[0], y3 + bh/2), L(ar)); arrow(R(ar), L(mo)); arrow((R(mo)[0] + 0.09, R(mo)[1]), L(mb)); arrow(R(mb), L(tv))

# ── result ──
dz = box(5.86, 1.10, 1.09, 2.20, "Verified Design\nJSON IR + trace\n+ verify report\n(score, PASS)", "io", bold_first=False)
arrow((vx + vw, y1 + 0.12), (5.86, y1 + 0.12))
arrow(R(tv), (5.86, R(tv)[1]))
mt = box(5.86, 3.44, 1.09, 0.38, "Matcher\nfigure parts vs design", "det", fs=5.9)
arrow((6.40, 3.30), (6.40, 3.44))

# ── downstream ──
y4 = 0.08; lane(y4 + bh + 0.1, "Downstream")
line([(6.40, 1.10), (6.40, 0.82), (0.42, 0.82)]); arrow((0.42, 0.82), (0.42, y4 + bh))
tu = box(0.05, y4, 1.20, bh, "Tuner\ncoordinate-descent\nalignment (tune.py)", "det")
cv = box(1.55, y4, 1.62, bh, "Cover artist\nNano Banana 2 (faithful) /\n2.1 (cinematic), image model", "llm")
pu = box(3.47, y4, 1.55, bh, "Publisher\nTypst build document\n(PDF)", "det")
bk = box(5.32, y4, 1.63, bh, "Build kit\nBOM (part numbers) +\nkeyed baseplate STLs", "det")
arrow(R(tu), L(cv))
line([(1.25, y4 + bh*0.8), (1.40, y4 + bh*0.8), (1.40, 0.67), (6.13, 0.67)])
arrow((4.25, 0.67), (4.25, y4 + bh)); arrow((6.13, 0.67), (6.13, y4 + bh))

# legend
lx, ly = 2.45, 3.86
ax.add_patch(FancyBboxPatch((lx, ly), 0.22, 0.12, boxstyle="round,pad=0,rounding_size=0.03", fc=LLM, ec=LLM_EDGE, lw=0.8))
ax.text(lx + 0.28, ly + 0.06, "LLM agent (Gemini)", fontsize=6, va="center")
ax.add_patch(FancyBboxPatch((lx + 1.35, ly), 0.22, 0.12, boxstyle="square,pad=0", fc=DET, ec=DET_EDGE, lw=0.8))
ax.text(lx + 1.63, ly + 0.06, "deterministic code", fontsize=6, va="center")
ax.add_patch(FancyBboxPatch((lx + 2.75, ly), 0.22, 0.12, boxstyle="square,pad=0", fc=LLM, ec=LLM_EDGE, lw=0.6))
ax.add_patch(FancyBboxPatch((lx + 2.72, ly + 0.03), 0.22, 0.12, boxstyle="square,pad=0", fc=LLM, ec=LLM_EDGE, lw=0.6))
ax.text(lx + 3.03, ly + 0.06, "parallel instances", fontsize=6, va="center")

style.save(fig, "architecture.pdf")
