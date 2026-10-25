export const fmt = (v: number | null | undefined, digits = 2, unit = ""): string => {
  if (v == null || !Number.isFinite(v)) return "—";
  const s = v.toFixed(digits);
  return unit ? `${s} ${unit}` : s;
};
export const mW = (v?: number | null) => {
  if (v == null || !Number.isFinite(v)) return "—";
  if (Math.abs(v) < 0.01 && v !== 0) return `${(v * 1000).toFixed(1)} µW`;
  return `${v.toFixed(v >= 100 ? 0 : v >= 10 ? 1 : 2)} mW`;
};
export const mm = (v?: number | null, d = 2) => fmt(v, d, "mm");
export const pct = (v?: number | null, d = 0) => (v == null ? "—" : `${(v * 100).toFixed(d)} %`);
export const deg = (v?: number | null, d = 1) => fmt(v, d, "°").replace(" °", "°");
export const mhz = (v?: number | null) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)} MHz`);
export const nm = (v?: number | null) => (v == null ? "—" : `${v.toFixed(Number.isInteger(v) ? 0 : 2)} nm`);
