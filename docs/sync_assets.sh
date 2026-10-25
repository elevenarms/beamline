#!/usr/bin/env bash
# Copy / convert the latest BEAMTEAM assets into docs/assets/ for GitHub Pages.
# Re-run whenever the paper, video or figures change:  bash docs/sync_assets.sh
# Needs: uv (for pymupdf + pillow), ffmpeg (optional, for the muted teaser loop).
set -euo pipefail
DOCS="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DOCS/.." && pwd)"
A="$DOCS/assets"
mkdir -p "$A/img" "$A/fig" "$A/video"

# 1) Paper PDF
if [ -f "$ROOT/paper/main.pdf" ]; then
  cp -f "$ROOT/paper/main.pdf" "$A/beamline_paper.pdf"; echo "paper  -> assets/beamline_paper.pdf"
else
  echo "paper  : paper/main.pdf not found (skipped)"
fi
[ -f "$ROOT/paper/figures/FIGURES.md" ] && cp -f "$ROOT/paper/figures/FIGURES.md" "$A/fig/FIGURES.md"

# 2) Demo video + subtitles (+ a light muted teaser loop)
VID="$ROOT/demo/video/beamline_demo_60s.mp4"
if [ -f "$VID" ]; then
  cp -f "$VID" "$A/video/beamline_demo_60s.mp4"; echo "video  -> assets/video/beamline_demo_60s.mp4"
  if command -v ffmpeg >/dev/null; then
    ffmpeg -loglevel error -y -i "$VID" -an -vf "scale='min(1280,iw)':-2" -c:v libx264 -crf 30 \
      -preset veryfast -pix_fmt yuv420p -movflags +faststart "$A/video/teaser.mp4" \
      && echo "teaser -> assets/video/teaser.mp4"
  else
    cp -f "$VID" "$A/video/teaser.mp4"
  fi
  if command -v ffmpeg >/dev/null; then
    ffmpeg -loglevel error -y -ss 30 -i "$VID" -frames:v 1 -vf "scale='min(1600,iw)':-2" "$A/video/_poster.png" \
      && cwebp -quiet -q 80 "$A/video/_poster.png" -o "$A/img/video_poster.webp" && rm -f "$A/video/_poster.png" && echo "poster -> assets/img/video_poster.webp (frame @ 30 s)"
  fi
else
  echo "video  : demo/video/beamline_demo_60s.mp4 not found (skipped; page shows poster)"
fi
for s in "$ROOT"/demo/video/beamline_demo_60s*.srt; do
  [ -f "$s" ] || continue
  cp -f "$s" "$A/video/beamline_demo_60s.srt"
  # browsers need WebVTT for <track>
  { echo "WEBVTT"; echo; sed -E 's/([0-9]{2}:[0-9]{2}:[0-9]{2}),([0-9]{3})/\1.\2/g' "$s" | tr -d '\r'; } \
    > "$A/video/beamline_demo_60s.vtt"
  echo "srt    -> assets/video/beamline_demo_60s.{srt,vtt}"; break
done

# 3) Images: paper figures (PDF->PNG/WebP), covers, screenshots, build docs, Fig. 2a
uv run -q --with pymupdf --with pillow python - "$ROOT" "$A" <<'PY'
import sys, pathlib, io
import pymupdf as fitz
from PIL import Image
root, A = map(pathlib.Path, sys.argv[1:3])
MAXW, MAXKB = 1600, 300

def save_webp(img, out):
    img = img.convert("RGBA") if img.mode in ("P", "LA") else img
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, "white"); bg.paste(img, mask=img.split()[3]); img = bg
    img = img.convert("RGB")
    if img.width > MAXW:
        img = img.resize((MAXW, round(img.height * MAXW / img.width)), Image.LANCZOS)
    for q in (85, 78, 70, 62, 55, 48, 40):
        buf = io.BytesIO(); img.save(buf, "WEBP", quality=q, method=6)
        if buf.tell() <= MAXKB * 1024: break
    while buf.tell() > MAXKB * 1024 and img.width > 600:
        img = img.resize((int(img.width * .85), int(img.height * .85)), Image.LANCZOS)
        buf = io.BytesIO(); img.save(buf, "WEBP", quality=60, method=6)
    out.write_bytes(buf.getvalue())
    print(f"  {out.relative_to(A.parent)}  {buf.tell()//1024} KB")

def pdf_page(pdf, page=0, width=1600):
    doc = fitz.open(pdf); p = doc[page]
    zoom = width / p.rect.width
    pix = p.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png")))

figdir = root / "paper" / "figures"
if figdir.exists():
    for f in sorted(figdir.iterdir()):
        if f.suffix.lower() == ".pdf":
            save_webp(pdf_page(f), A / "fig" / (f.stem + ".webp"))
        elif f.suffix.lower() in (".png", ".jpg", ".jpeg"):
            if (figdir / (f.stem + ".pdf")).exists(): continue
            save_webp(Image.open(f), A / "fig" / (f.stem + ".webp"))

for f in sorted((root / "demo" / "covers").glob("*.png")):
    save_webp(Image.open(f), A / "img" / ("cover_" + f.stem + ".webp"))
for f in sorted((root / "web" / "screenshots").glob("*.png")):
    save_webp(Image.open(f), A / "img" / ("shot_" + f.stem + ".webp"))
for f in sorted((root / "demo" / "build_docs").glob("*.pdf")):
    n = len(fitz.open(f))
    for i in range(min(2, n)):
        save_webp(pdf_page(f, i, 1400), A / "img" / f"builddoc_{f.stem}_p{i+1}.webp")
fig2a = root / "demo" / "rb_sas_fig2a.png"
if fig2a.exists(): save_webp(Image.open(fig2a), A / "img" / "rb_sas_fig2a.webp")
for f in sorted((root / "demo" / "figures").glob("*.png")):
    save_webp(Image.open(f), A / "img" / ("bench_" + f.stem + ".webp"))
PY

# 4) Manifest read by index.html (so the page never requests files that don't exist yet)
has() { [ -f "$A/$1" ] && echo true || echo false; }
cat > "$A/manifest.json" <<JSON
{"paper": $(has beamline_paper.pdf), "video": $(has video/beamline_demo_60s.mp4), "teaser": $(has video/teaser.mp4), "vtt": $(has video/beamline_demo_60s.vtt), "poster": $(has img/video_poster.webp)}
JSON
echo "manifest -> $(cat "$A/manifest.json")"

echo "docs/ total:"; du -sh "$DOCS"; du -sh "$A/video" 2>/dev/null || true
