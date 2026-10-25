"""Fig. 9: gallery of real artifacts (2x3). All panels are unmodified (cropped/downscaled) project artifacts,
except (c), which is drawn directly from optics.trace on backend/examples/sr_ion_apparatus.json."""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
import style
from style import plt, C, wavelength_color
import numpy as np
from PIL import Image
from matplotlib.patches import Rectangle
from optics.ir import Design
from optics.trace import trace
from optics.verify import verify

R = style.ROOT
SS = os.path.join(R, "web", "screenshots")
MAXW = 1100

def load(path, crop=None, maxw=MAXW):
    im = Image.open(path).convert("RGB")
    if crop: im = im.crop(crop)
    if im.width > maxw:
        im = im.resize((maxw, round(im.height * maxw / im.width)), Image.LANCZOS)
    return np.asarray(im)

def side_by_side(paths, h=700, gap=12):
    ims = [Image.open(p).convert("RGB") for p in paths]
    ims = [im.resize((round(im.width * h / im.height), h), Image.LANCZOS) for im in ims]
    W = sum(im.width for im in ims) + gap * (len(ims) - 1)
    out = Image.new("RGB", (W, h), "white"); x = 0
    for im in ims: out.paste(im, (x, 0)); x += im.width + gap
    return np.asarray(out)

fig, axs = plt.subplots(2, 3, figsize=(style.FULL_W, 3.55), gridspec_kw=dict(wspace=0.06, hspace=0.22))
axs = axs.ravel()
panels = []

# (a) paper figure: dual-trap tweezers (Ashraf & Pullarkat, arXiv:2411.16256, CC BY 4.0)
panels.append((load(os.path.join(R, "demo/figures/dual_trap_tweezers.png")), "paper figure (arXiv:2411.16256)"))
# (b) fly-in: figure lifted above the bench while parts drop into place
panels.append((load(os.path.join(SS, "flyin_mid.png"), crop=(880, 110, 2200, 930)), "fly-in onto the bench"))
panels.append((None, "sr_ion_apparatus"))
# (d) token-stream console
panels.append((load(os.path.join(SS, "token_streams.png"), crop=(0, 975, 1420, 1590)), "agent console, live token streams"))
# (e) covers: faithful (gemini-3.1-flash-image) + cinematic (gemini-nano-banana-2.1)
panels.append((side_by_side([os.path.join(R, "demo/covers/gemini-3.1-flash-image_1.png"),
                             os.path.join(R, "demo/covers/gemini-nano-banana-2.1_1.png")]),
               "cover art: faithful | cinematic"))
# (f) build kit, 3D-print tab
panels.append((load(os.path.join(SS, "build_kit_print.png"), crop=(396, 104, 2636, 1524)), "build kit: printable baseplate tiles"))

info = {}
for i, (ax, (img, title)) in enumerate(zip(axs, panels)):
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_visible(False)
    if img is not None:
        ax.imshow(img, interpolation="lanczos")
        for s in ax.spines.values(): s.set_visible(True); s.set_linewidth(0.4); s.set_color("#999999")
    else:
        d = Design.model_validate(json.load(open(os.path.join(R, "backend/examples/sr_ion_apparatus.json"))))
        tr = trace(d); rep = verify(d, tr)
        for m in d.modules:
            x, y, w, h = m.region
            ax.add_patch(Rectangle((x, y), w, h, fc="#F4F4F4", ec="#BBBBBB", lw=0.4, zorder=0))
        for sgm in tr.segments:
            (x0, y0), (x1, y1) = sgm.start, sgm.end
            ax.plot([x0, x1], [y0, y1], color=wavelength_color(sgm.wavelength_nm), lw=0.5, zorder=2,
                    solid_capstyle="round")
        pts = np.array([e.position for e in tr.elements if e.placed and e.position is not None])
        ax.scatter(pts[:, 0], pts[:, 1], s=1.2, c="#333333", lw=0, zorder=3)
        ax.set_aspect("equal"); ax.autoscale(); ax.margins(0.02)
        bp = d.baseplate
        n_el = len(d.elements)
        info = dict(elements=n_el, placed=int(len(pts)), modules=len(d.modules), segments=len(tr.segments),
                    score=rep.score, passed=rep.passed)
        title = f"{n_el}-element apparatus ({len(d.modules)} modules), traced"
        for s in ax.spines.values(): s.set_visible(True); s.set_linewidth(0.4); s.set_color("#999999")
    ax.set_title(f"({'abcdef'[i]}) {title}", fontsize=7, loc="left", pad=2.5)

print("panel c:", info)
style.save(fig, "gallery.pdf")
