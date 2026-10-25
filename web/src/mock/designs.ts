import type { Design } from "../types";

// Hand-written demo fixtures. Traces/reports are computed by ./tracer.ts so edits stay live offline.

export const rbAomFiber: Design = {
  name: "rb_aom_fiber",
  description:
    "Rb-87 D2 (780 nm) source: isolator, polarization cleanup, saturated-absorption pickoff, PBS split, " +
    "+1-order AOM frequency shifter into fiber F1 and a reference fiber F2.",
  baseplate: { width_mm: 457.2, height_mm: 228.6, thickness_mm: 25.4, optical_height_mm: 12.7, grid_mm: 25.4 },
  sources: [
    { id: "L1", label: "780 nm ECDL", part_number: "Toptica DL pro", position: [20, 30], direction_deg: 0,
      wavelength_nm: 780, power_mw: 25, waist_mm: 0.6, polarization: 20 },
  ],
  elements: [
    { id: "ISO1", type: "isolator", label: "Optical isolator", part_number: "IO-3D-780-VLP", beam: "L1", distance_mm: 40, transmission: 0.9 },
    { id: "HWP1", type: "half_wave_plate", label: "λ/2 cleanup", part_number: "WPH05M-780", beam: "L1", distance_mm: 45, fast_axis_deg: 10 },
    { id: "M1", type: "mirror", label: "Fold mirror", part_number: "BB1-E03", beam: "L1", distance_mm: 45, out_direction_deg: 90 },
    { id: "M2", type: "mirror", label: "Fold mirror", part_number: "BB1-E03", beam: "L1", distance_mm: 70, out_direction_deg: 0 },
    { id: "S1", type: "sampler", label: "5% pickoff", part_number: "BSF10-B", beam: "L1", distance_mm: 40, split_ratio: 0.05 },
    { id: "VC1", type: "vapor_cell", label: "Rb reference cell", part_number: "GC25075-RB", beam: "L1.r", distance_mm: 40, transmission: 0.6 },
    { id: "PD1", type: "photodiode", label: "SAS photodiode", part_number: "PDA36A2", beam: "L1.r", distance_mm: 45 },
    { id: "HWP2", type: "half_wave_plate", label: "λ/2 split ratio", part_number: "WPH05M-780", beam: "L1.t", distance_mm: 25, fast_axis_deg: 11.25 },
    { id: "PBS1", type: "pbs", label: "PBS cube", part_number: "PBS252", beam: "L1.t", distance_mm: 25 },
    { id: "M3", type: "mirror", label: "Fold mirror", part_number: "BB1-E03", beam: "L1.t.r", distance_mm: 60, out_direction_deg: 0 },
    { id: "F2", type: "fiber_coupler", label: "Reference fiber", part_number: "PAF2-11B", beam: "L1.t.r", distance_mm: 120, focal_length_mm: 11 },
    { id: "LN1", type: "lens", label: "f = 150 mm", part_number: "LA1433-B", beam: "L1.t.t", distance_mm: 30, focal_length_mm: 150 },
    { id: "AOM1", type: "aom", label: "AOM 110 MHz", part_number: "AOMO 3110-120", beam: "L1.t.t", distance_mm: 60,
      aom_frequency_mhz: 110, aom_efficiency: 0.82, aom_order: 1, aperture_mm: 2 },
    { id: "IR1", type: "iris", label: "Order select", part_number: "ID12", beam: "L1.t.t.+1", distance_mm: 60, aperture_mm: 3 },
    { id: "M4", type: "mirror", label: "Fold mirror", part_number: "BB1-E03", beam: "L1.t.t.+1", distance_mm: 45, out_direction_deg: 270 },
    { id: "F1", type: "fiber_coupler", label: "Experiment fiber", part_number: "PAF2-A4B", beam: "L1.t.t.+1", distance_mm: 60, focal_length_mm: 4.5 },
  ],
  targets: [
    { element_id: "F1", kind: "min_power_mw", value: 8 },
    { element_id: "F2", kind: "min_coupling", value: 0.6 },
  ],
  notes: "Mock fixture (web/src/mock). 0th AOM order intentionally left undumped to demo the verifier.",
};

export const machZehnder: Design = {
  name: "mach_zehnder_532",
  description: "532 nm Mach–Zehnder interferometer with two output photodiodes.",
  baseplate: { width_mm: 355.6, height_mm: 254, thickness_mm: 25.4, optical_height_mm: 12.7, grid_mm: 25.4 },
  sources: [
    { id: "L1", label: "532 nm DPSS", position: [20, 50], direction_deg: 0, wavelength_nm: 532, power_mw: 10, waist_mm: 0.4, polarization: "V" },
  ],
  elements: [
    { id: "BS1", type: "beamsplitter", label: "50:50 BS", part_number: "BS013", beam: "L1", distance_mm: 65, split_ratio: 0.5 },
    { id: "M1", type: "mirror", beam: "L1.t", distance_mm: 150, out_direction_deg: 90 },
    { id: "M2", type: "mirror", beam: "L1.r", distance_mm: 125, out_direction_deg: 0 },
    { id: "BS2", type: "beamsplitter", label: "50:50 BS", part_number: "BS013", at: [235, 175], angle_deg: 0, split_ratio: 0.5 },
    { id: "PD1", type: "photodiode", at: [235, 235], angle_deg: 270 },
    { id: "PD2", type: "photodiode", at: [320, 175], angle_deg: 180 },
  ],
  targets: [{ element_id: "PD1", kind: "min_power_mw", value: 3 }],
};

export const srTwoColor: Design = {
  name: "sr_two_color",
  description: "Sr blue (461 nm) + red MOT (689 nm) beams combined on a dichroic into one fiber.",
  baseplate: { width_mm: 457.2, height_mm: 203.2, thickness_mm: 25.4, optical_height_mm: 12.7, grid_mm: 25.4 },
  sources: [
    { id: "B", label: "461 nm", position: [20, 40], direction_deg: 0, wavelength_nm: 461, power_mw: 30, waist_mm: 0.7, polarization: "H" },
    { id: "R", label: "689 nm", position: [20, 120], direction_deg: 0, wavelength_nm: 689, power_mw: 8, waist_mm: 0.7, polarization: "V" },
  ],
  elements: [
    { id: "HWPb", type: "half_wave_plate", beam: "B", distance_mm: 60, fast_axis_deg: 0 },
    { id: "Mb", type: "mirror", beam: "B", distance_mm: 160, out_direction_deg: 90 },
    { id: "HWPr", type: "half_wave_plate", beam: "R", distance_mm: 60, fast_axis_deg: 45 },
    { id: "DM1", type: "dichroic", label: "Dichroic 600 nm SP", at: [240, 120], angle_deg: 0, cutoff_nm: 600, reflect: "below" },
    { id: "L1", type: "lens", label: "f = 200 mm", at: [320, 120], focal_length_mm: 200 },
    { id: "FC1", type: "fiber_coupler", label: "Combined fiber", at: [430, 120], angle_deg: 180, focal_length_mm: 8 },
  ],
};

export const opticalAnd: Design = {
  name: "all_optical_and",
  description: "All-optical logic: inputs A and B combine on a 50:50 splitter; a saturable absorber thresholds the sum so OUT is lit only for A·B.",
  baseplate: { width_mm: 355.6, height_mm: 203.2, thickness_mm: 25.4, optical_height_mm: 12.7, grid_mm: 25.4 },
  sources: [
    { id: "A", label: "A", position: [70, 110], direction_deg: 0, wavelength_nm: 1550, power_mw: 10, waist_mm: 0.5, polarization: "H" },
    { id: "B", label: "B", position: [150, 70], direction_deg: 90, wavelength_nm: 1550, power_mw: 10, waist_mm: 0.5, polarization: "H" },
  ],
  elements: [
    { id: "BS1", type: "beamsplitter", label: "Combiner 50:50", at: [150, 110], angle_deg: 0, split_ratio: 0.5 },
    { id: "SA1", type: "saturable_absorber", label: "Threshold", at: [230, 110], transmission: 0.05, saturation_power_mw: 10 },
    { id: "OUT", type: "photodiode", label: "OUT", at: [310, 110], angle_deg: 180 },
    { id: "BD1", type: "beam_dump", at: [150, 180], angle_deg: 270 },
  ],
};

export const MOCK_EXAMPLES: { name: string; title: string; design: Design }[] = [
  { name: rbAomFiber.name, title: "Rb 780 nm · AOM → fiber (mock)", design: rbAomFiber },
  { name: machZehnder.name, title: "532 nm Mach–Zehnder (mock)", design: machZehnder },
  { name: srTwoColor.name, title: "Sr 461 + 689 nm combiner (mock)", design: srTwoColor },
  { name: opticalAnd.name, title: "All-optical AND gate (mock)", design: opticalAnd },
];

// ───────── big synthetic apparatus: tiles the fixtures above into labelled modules ─────────
function prefixModule(d: Design, id: string, title: string, dx: number, dy: number): Design {
  const p = (s: string) => `${id}_${s}`;
  const bp = d.baseplate!;
  return {
    ...d,
    modules: [{ id, title, region: [dx, dy, bp.width_mm, bp.height_mm], description: d.description }],
    sources: d.sources.map((s) => ({ ...s, id: p(s.id), group: id, position: [s.position[0] + dx, s.position[1] + dy] })),
    elements: (d.elements ?? []).map((e) => ({
      ...e,
      id: p(e.id),
      group: id,
      beam: e.beam ? p(e.beam) : e.beam,
      at: e.at ? [e.at[0] + dx, e.at[1] + dy] : e.at,
    })),
    targets: (d.targets ?? []).map((t) => ({ ...t, element_id: p(t.element_id) })),
  };
}

const TILES: [Design, string][] = [
  [rbAomFiber, "780 nm AOM / fiber"],
  [machZehnder, "532 nm interferometer"],
  [srTwoColor, "461 + 689 nm combiner"],
];

/** 4 × 3 grid of modules on a 1422 × 1120 mm table (~110 elements). */
export function bigApparatusModules(): Design[] {
  const out: Design[] = [];
  const colX = [20, 500, 880];
  let n = 0;
  for (let row = 0; row < 4; row++) {
    for (let col = 0; col < 3; col++) {
      const [d, title] = TILES[col];
      const id = String.fromCharCode(65 + n++); // A, B, C…
      const base = col === 0 ? { ...d, elements: [...(d.elements ?? []), { id: "BD0", type: "beam_dump" as const, label: "0-order dump", beam: "L1.t.t.0", distance_mm: 110 }] } : d;
      out.push(prefixModule(base, id, `${id} · ${title}`, colX[col], 20 + row * 275));
    }
  }
  return out;
}

export function mergeDesigns(name: string, parts: Design[], baseplate = { width_mm: 1422.4, height_mm: 1117.6, thickness_mm: 25.4, optical_height_mm: 12.7, grid_mm: 25.4 }): Design {
  return {
    name,
    description: `Synthetic large apparatus: ${parts.length} modules tiled from the mock fixtures (scale test).`,
    baseplate,
    modules: parts.flatMap((p) => p.modules ?? []),
    sources: parts.flatMap((p) => p.sources),
    elements: parts.flatMap((p) => p.elements ?? []),
    targets: parts.flatMap((p) => p.targets ?? []),
  };
}

export const bigApparatus: Design = mergeDesigns("mock_big_apparatus", bigApparatusModules());
MOCK_EXAMPLES.push({ name: bigApparatus.name, title: "Big apparatus · 12 modules (mock)", design: bigApparatus });
