// Wavelength (nm) → sRGB hex. Visible range follows Bruton's approximation; UV clamps to violet, IR to deep red.
export function wavelengthToColor(nm: number, onDark = false): string {
  let r = 0, g = 0, b = 0;
  const w = Math.max(400, Math.min(nm, 760));
  if (w < 440) { r = -(w - 440) / 60; b = 1; }
  else if (w < 490) { g = (w - 440) / 50; b = 1; }
  else if (w < 510) { g = 1; b = -(w - 510) / 20; }
  else if (w < 580) { r = (w - 510) / 70; g = 1; }
  else if (w < 645) { r = 1; g = -(w - 645) / 65; }
  else { r = 1; }
  let f = 1;
  if (w < 420) f = 0.55 + 0.45 * (w - 400) / 20;
  else if (w > 700) f = 0.6 + 0.4 * (760 - w) / 60;
  if (nm > 760) f = onDark ? 0.95 : 0.62; // IR → deep red (full saturation on dark)
  if (onDark && w > 700) f = Math.max(f, 0.95);
  // slightly darken for legibility on a light background; full intensity on dark
  const k = onDark ? 1 : 0.88;
  const to = (v: number) => Math.round(255 * Math.pow(Math.max(0, v * f), 0.8) * k).toString(16).padStart(2, "0");
  return `#${to(r)}${to(g)}${to(b)}`;
}

export function bandName(nm: number): string {
  if (nm < 400) return "UV";
  if (nm > 760) return "NIR";
  return "VIS";
}
