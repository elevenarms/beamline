import type { Bom, BomRow, Design } from "../types";
import { DEFAULT_BASEPLATE } from "../types";

// Offline stand-in for POST /api/bom: generic catalog lines per element type (prices are rough estimates).
const DEFAULTS: Record<string, [string, string, number]> = {
  mirror: ["BB1-E03", "Ø1\" broadband dielectric mirror", 85],
  lens: ["LA1433-B", "Ø1\" plano-convex lens, AR coated", 35],
  half_wave_plate: ["WPH10M-780", "Ø1\" zero-order λ/2 plate", 350],
  quarter_wave_plate: ["WPQ10M-780", "Ø1\" zero-order λ/4 plate", 350],
  pbs: ["PBS252", "10 mm polarizing beamsplitter cube", 260],
  beamsplitter: ["BS013", "10 mm 50:50 beamsplitter cube", 230],
  sampler: ["BSF10-B", "Ø1\" beam sampler", 60],
  dichroic: ["DMSP650", "Ø1\" short-pass dichroic mirror", 210],
  aom: ["AOM-110", "acousto-optic modulator (generic)", 1400],
  iris: ["ID12", "Ø12 mm iris diaphragm", 70],
  fiber_coupler: ["PAF2-11B", "FiberPort collimator/coupler", 420],
  photodiode: ["PDA36A2", "amplified Si photodetector", 380],
  beam_dump: ["LB2", "beam dump", 95],
  vapor_cell: ["GC25075-RB", "Rb reference cell", 690],
  isolator: ["IO-3D-780", "free-space optical isolator", 1600],
};
const MOUNT: [string, string, number] = ["KM100", "kinematic mount Ø1\"", 45];

export function mockBom(d: Design): Bom {
  const rows = new Map<string, BomRow>();
  const add = (pn: string, desc: string, price: number, id: string) => {
    const r = rows.get(pn) ?? { part_number: pn, description: desc, vendor: "Thorlabs", qty: 0, unit_price_usd: price, url: `https://www.thorlabs.com/thorproduct.cfm?partnumber=${pn}`, element_ids: [], price_note: "estimate" };
    r.qty += 1;
    r.element_ids.push(id);
    rows.set(pn, r);
  };
  for (const e of d.elements ?? []) {
    const def = DEFAULTS[e.type] ?? ["GENERIC", e.type, 50];
    add(e.part_number || def[0], e.label || def[1], def[2], e.id);
    if (["mirror", "lens", "half_wave_plate", "quarter_wave_plate", "sampler", "dichroic", "iris"].includes(e.type)) add(MOUNT[0], MOUNT[1], MOUNT[2], e.id);
  }
  const purchased = [...rows.values()];
  const n = (d.elements ?? []).length;
  const bp = { ...DEFAULT_BASEPLATE, ...(d.baseplate ?? {}) };
  const tiles = Math.max(1, Math.ceil(bp.width_mm / 250) * Math.ceil(bp.height_mm / 250));
  const hardware: BomRow[] = [
    { part_number: "SH25S050", description: "1/4\"-20 cap screw, 1/2\"", vendor: "Thorlabs", qty: 8 * tiles, unit_price_usd: 0.6, url: null, element_ids: [] },
    { part_number: "SH8S100", description: "8-32 cap screw, 1\"", vendor: "Thorlabs", qty: n, unit_price_usd: 0.5, url: null, element_ids: [] },
  ];
  const printed = Array.from({ length: tiles }, (_, i) => {
    const vol = (bp.width_mm * bp.height_mm * bp.thickness_mm) / tiles / 1000 * 0.9;
    return { name: tiles > 1 ? `baseplate_tile_${i + 1}` : "baseplate", file: `stl/baseplate_${i + 1}.stl`, volume_cm3: +vol.toFixed(1), est_print_h: +(vol * 0.32 / 12).toFixed(1), est_filament_g: Math.round(vol * 0.32 * 1.24), notes: `PLA, 20 % infill · ${n} keyed element sites (offline estimate)` };
  });
  const cost = (r: BomRow[]) => r.reduce((a, x) => a + (x.unit_price_usd ?? 0) * x.qty, 0);
  return {
    design: d.name, purchased, hardware, printed,
    plate: { width_mm: bp.width_mm, height_mm: bp.height_mm, thickness_mm: bp.thickness_mm, table_holes: 8 * tiles, element_sites: n, pin_holes: 2 * n, tiles },
    totals: {
      purchased_parts: purchased.reduce((a, r) => a + r.qty, 0), hardware_parts: hardware.reduce((a, r) => a + r.qty, 0), printed_parts: printed.length,
      est_cost_usd: Math.round(cost(purchased) + cost(hardware)), est_print_h: +printed.reduce((a, p) => a + p.est_print_h, 0).toFixed(1),
      est_filament_g: printed.reduce((a, p) => a + p.est_filament_g, 0), price_note: "offline estimate; list prices approximate, USD, verify with vendors",
    },
  };
}
