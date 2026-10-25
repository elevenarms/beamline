"""Fig 10: plan view of the 121-element Sr+ ion apparatus, drawn from its trace."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import style
from style import plt, C, FULL_W, save, wavelength_color
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
BK = os.path.join(style.ROOT, "backend"); sys.path.insert(0, BK)
from optics.ir import Design
from optics.trace import trace
from optics.verify import verify

# distinct, still wavelength-ordered colours (the two IR lines would otherwise coincide)
_OVR = {405.0: "#6A2FB0", 421.7: "#3F4FC8", 460.9: "#3E8FD0", 674.0: "#D0443A", 1033.0: "#9A5B2E", 1091.8: "#5A1A1A"}
wavelength_color = lambda w, _f=wavelength_color: _OVR.get(round(float(w), 1), _f(w))
d = Design.model_validate_json(open(os.path.join(BK, "examples", "sr_ion_apparatus.json")).read())
tr = trace(d); rep = verify(d, tr)
W, H = d.baseplate.width_mm, d.baseplate.height_mm
fig, ax = plt.subplots(figsize=(FULL_W, FULL_W * H / W * 0.98))
ax.add_patch(Rectangle((0, 0), W, H, fc="#FAFAF7", ec="#999999", lw=0.6, zorder=0))
for m in d.modules:
    x, y, w, h = m.region
    ax.add_patch(Rectangle((x + 3, y + 3), w - 6, h - 6, fc="none", ec="#BBBBBB", lw=0.6, ls=(0, (3, 2)), zorder=1))
    ax.text(x + 8, y + h - 10, m.title, fontsize=6.5, va="top", ha="left", color="#444444", zorder=5,
            bbox=dict(fc="white", ec="none", alpha=0.8, pad=0.8))
pmax = max(s.power_mw for s in tr.segments)
for s in tr.segments:
    if s.power_mw <= 1e-6:
        continue
    lw = 0.5 + 1.6 * (s.power_mw / pmax) ** 0.5
    ax.plot([s.start[0], s.end[0]], [s.start[1], s.end[1]], color=wavelength_color(s.wavelength_nm),
            lw=lw, solid_capstyle="round", zorder=2, alpha=0.9)
MK = {"mirror": ("s", 2.6), "lens": ("|", 5), "fiber_coupler": ("D", 3.2), "photodiode": ("o", 3.2),
      "beam_dump": ("x", 3.5)}
types = {e.id: e.type for e in d.elements}
for pe in tr.elements:
    if not pe.placed or pe.position is None:
        continue
    mk, ms = MK.get(pe.type, ("o", 2.2))
    ax.plot(*pe.position, marker=mk, ms=ms, mfc="white" if mk not in ("|", "x") else "#333333",
            mec="#333333", mew=0.6, zorder=4, ls="none")
for s in d.sources:
    ax.plot(*s.position, marker=">", ms=4.5, color=wavelength_color(s.wavelength_nm), mec="#333333", mew=0.5, zorder=4)
ax.set_xlim(-5, W + 5); ax.set_ylim(-5, H + 5); ax.set_aspect("equal")
ax.set_xlabel("x (mm)"); ax.set_ylabel("y (mm)")
wls = sorted({s.wavelength_nm for s in d.sources})
handles = [Line2D([], [], color=wavelength_color(w), lw=1.6, label=f"{w:g} nm") for w in wls]
handles += [Line2D([], [], marker=MK[k][0], ls="none", mfc="white" if k not in ("lens", "beam_dump") else "#333",
                   mec="#333", ms=MK[k][1], label=k.replace("_", " ")) for k in MK]
ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=len(handles), fontsize=6.5,
          handlelength=1.4, columnspacing=1.0)
print(len(d.elements), "elements", len(d.sources), "sources", len(d.modules), "modules", len(tr.segments), "segments",
      "passed", rep.passed, "score", round(rep.score, 1), "delivered", round(rep.metrics.get("delivered_mw", 0), 1),
      "input", round(rep.metrics.get("input_mw", 0), 1), "wavelengths", wls,
      "unplaced", sum(not e.placed for e in tr.elements))
save(fig, "planview_apparatus.pdf")
