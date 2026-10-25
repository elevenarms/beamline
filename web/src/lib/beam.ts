import type { Segment, Vec2 } from "../types";

export const beamRadius = (s: Segment, z: number) =>
  s.w0_mm * Math.sqrt(1 + ((z - s.waist_z_mm) / Math.max(s.rayleigh_mm, 1e-9)) ** 2);

/** opacity from power, log-scaled: 0.01 mW → ~0.2, 10 mW+ → ~0.75 */
export const powerOpacity = (p: number) => {
  const t = (Math.log10(Math.max(p, 1e-4)) + 2) / 3; // -2..1 → 0..1
  return 0.18 + 0.57 * Math.max(0, Math.min(1, t));
};

/** polygon outline (table frame) of the Gaussian envelope of one segment */
export function envelope(s: Segment, exaggeration: number, minR: number, n = 24): Vec2[] {
  const [x0, y0] = s.start;
  const dx = (s.end[0] - x0) / (s.length_mm || 1), dy = (s.end[1] - y0) / (s.length_mm || 1);
  const nx = -dy, ny = dx;
  const left: Vec2[] = [], right: Vec2[] = [];
  for (let i = 0; i <= n; i++) {
    const z = (s.length_mm * i) / n;
    const r = Math.max(beamRadius(s, z) * exaggeration, minR);
    const cx = x0 + dx * z, cy = y0 + dy * z;
    left.push([cx + nx * r, cy + ny * r]);
    right.push([cx - nx * r, cy - ny * r]);
  }
  return [...left, ...right.reverse()];
}

/** project a table point onto a segment → distance z from the start */
export function zAlong(s: Segment, p: Vec2): number {
  const dx = s.end[0] - s.start[0], dy = s.end[1] - s.start[1];
  const L2 = dx * dx + dy * dy || 1;
  const t = ((p[0] - s.start[0]) * dx + (p[1] - s.start[1]) * dy) / L2;
  return Math.max(0, Math.min(1, t)) * s.length_mm;
}

export const SHORT: Record<string, string> = {
  mirror: "Mirror", lens: "Lens", half_wave_plate: "λ/2 plate", quarter_wave_plate: "λ/4 plate", pbs: "PBS",
  beamsplitter: "Beamsplitter", sampler: "Pickoff", dichroic: "Dichroic", aom: "AOM", iris: "Iris",
  fiber_coupler: "Fiber coupler", photodiode: "Photodiode", beam_dump: "Beam dump", vapor_cell: "Vapor cell",
  isolator: "Isolator",
};
