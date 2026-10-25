import type { Change, Design, Element } from "../types";

// Mirrors backend optics/diff.py: deterministic design-to-design change list (used for mock runs
// and as a fallback when an iteration arrives without a diff).
const MOVE = new Set(["distance_mm", "at"]);
const ROT = new Set(["angle_deg", "out_direction_deg"]);
const SKIP = new Set(["id", "label", "part_number", "group"]);

const eq = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

export function diffDesigns(a: Design | null | undefined, b: Design): Change[] {
  const out: Change[] = [];
  const before = new Map((a?.elements ?? []).map((e) => [e.id, e]));
  const after = new Map((b.elements ?? []).map((e) => [e.id, e]));
  for (const [id, e] of after) {
    const o = before.get(id);
    if (!o) {
      out.push({ op: "add", element_id: id, to: e.type, note: e.beam ? `on ${e.beam} @ ${e.distance_mm} mm` : e.at ? `at (${e.at[0]}, ${e.at[1]})` : null });
      continue;
    }
    const keys = new Set([...Object.keys(o), ...Object.keys(e)]) as Set<keyof Element>;
    for (const k of keys) {
      if (SKIP.has(k) || eq(o[k], e[k])) continue;
      const op: Change["op"] = MOVE.has(k) ? "move" : ROT.has(k) ? "rotate" : k === "beam" ? "retarget" : "param";
      out.push({ op, element_id: id, field: k, from: o[k] ?? null, to: e[k] ?? null });
    }
  }
  for (const [id, e] of before) if (!after.has(id)) out.push({ op: "remove", element_id: id, from: e.type });
  return out;
}

const UNIT: Record<string, string> = { distance_mm: " mm", angle_deg: "°", out_direction_deg: "°", focal_length_mm: " mm", aperture_mm: " mm", aom_frequency_mhz: " MHz", fast_axis_deg: "°", cutoff_nm: " nm", saturation_power_mw: " mW", small_signal_gain_db: " dB" };
const fmtV = (v: unknown, f?: string | null) => {
  if (v == null) return "auto";
  if (Array.isArray(v)) return `(${v.map((x) => (typeof x === "number" ? +x.toFixed(1) : x)).join(", ")})`;
  if (typeof v === "number") return `${+v.toFixed(3)}${f ? UNIT[f] ?? "" : ""}`;
  return String(v);
};

export const OP_GLYPH: Record<Change["op"], string> = { add: "+", remove: "−", move: "↔", rotate: "⟳", param: "≈", retarget: "⇢" };

export function changeText(c: Change): string {
  const g = OP_GLYPH[c.op] ?? "·";
  if (c.op === "add") return `${g} ${c.element_id} ${fmtV(c.to)}${c.note ? ` ${c.note}` : ""}`;
  if (c.op === "remove") return `${g} ${c.element_id} ${fmtV(c.from)}${c.note ? ` (${c.note})` : ""}`;
  const f = c.field ?? "";
  return `${g} ${c.element_id} ${f.replace(/_(mm|deg|mhz|nm|mw|db)$/, "")} ${fmtV(c.from, f)} → ${fmtV(c.to, f)}${c.note ? `  (${c.note})` : ""}`;
}
