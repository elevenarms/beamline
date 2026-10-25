"""Shared figure style for the BEAMTEAM paper."""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FIG = os.path.join(ROOT, "paper", "figures")
COL_W, FULL_W = 3.4, 7.0

# muted palette
C = dict(blue="#4C72B0", orange="#DD8452", green="#55A868", red="#C44E52",
         purple="#8172B3", brown="#937860", pink="#DA8BC3", grey="#8C8C8C",
         yellow="#CCB974", cyan="#64B5CD", ink="#222222", light="#E8E8E8")
LLM = "#DCE6F2"      # LLM agent fill
LLM_EDGE = C["blue"]
DET = "#EDEDED"      # deterministic code fill
DET_EDGE = "#555555"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "lines.linewidth": 1.2, "pdf.fonttype": 42, "ps.fonttype": 42,
    "savefig.dpi": 300, "figure.dpi": 150, "legend.frameon": False,
})

def wavelength_color(nm):
    """Approximate visible colour for a wavelength in nm; IR -> dark red, UV -> violet."""
    try:
        w = float(nm)
    except (TypeError, ValueError):
        return C["grey"]
    if w < 380: return "#7A3DB8"
    if w > 780: return "#8B1A1A"
    if w < 440: r, g, b = -(w-440)/60, 0, 1
    elif w < 490: r, g, b = 0, (w-440)/50, 1
    elif w < 510: r, g, b = 0, 1, -(w-510)/20
    elif w < 580: r, g, b = (w-510)/70, 1, 0
    elif w < 645: r, g, b = 1, -(w-645)/65, 0
    else: r, g, b = 1, 0, 0
    # mute slightly
    m = lambda x: 0.15 + 0.75*x
    return (m(r), m(g), m(b))

def save(fig, name):
    path = os.path.join(FIG, name)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.02)
    print("wrote", path)
