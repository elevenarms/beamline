// Mirrors backend/optics/ir.py — the fixed contract. Units: mm, deg, nm, mW, MHz.
// Table frame: origin at baseplate lower-left, +x right, +y up, optics in z = 0 plane.

export type ElementType =
  | "mirror"
  | "lens"
  | "half_wave_plate"
  | "quarter_wave_plate"
  | "pbs"
  | "beamsplitter"
  | "sampler"
  | "dichroic"
  | "aom"
  | "iris"
  | "fiber_coupler"
  | "photodiode"
  | "beam_dump"
  | "vapor_cell"
  | "isolator"
  | "soa"
  | "sfg_crystal"
  | "saturable_absorber";

export const ELEMENT_TYPES: ElementType[] = [
  "mirror", "lens", "half_wave_plate", "quarter_wave_plate", "pbs", "beamsplitter", "sampler",
  "dichroic", "aom", "iris", "fiber_coupler", "photodiode", "beam_dump", "vapor_cell", "isolator",
  "soa", "sfg_crystal", "saturable_absorber",
];

export const TERMINATING = new Set<ElementType>(["fiber_coupler", "photodiode", "beam_dump"]);
export const SPLITTING = new Set<ElementType>(["pbs", "beamsplitter", "sampler", "dichroic"]);

export type PolarizationSpec = "H" | "V" | "D" | "A" | "R" | "L" | number;
export type Vec2 = [number, number];

export interface Baseplate {
  width_mm: number;
  height_mm: number;
  thickness_mm: number;
  optical_height_mm: number;
  grid_mm: number;
}

export const DEFAULT_BASEPLATE: Baseplate = {
  width_mm: 300,
  height_mm: 150,
  thickness_mm: 25.4,
  optical_height_mm: 12.7,
  grid_mm: 25.4,
};

export interface Source {
  id: string;
  label?: string;
  part_number?: string | null;
  position: Vec2;
  direction_deg: number;
  wavelength_nm: number;
  power_mw?: number;
  waist_mm?: number;
  waist_offset_mm?: number;
  polarization?: PolarizationSpec;
  enabled?: boolean;
  group?: string | null;
}

export interface Element {
  id: string;
  type: ElementType;
  label?: string;
  part_number?: string | null;
  beam?: string | null;
  distance_mm?: number | null;
  at?: Vec2 | null;
  angle_deg?: number | null;
  out_direction_deg?: number | null;
  aperture_mm?: number | null;
  focal_length_mm?: number | null;
  fast_axis_deg?: number | null;
  split_ratio?: number | null;
  cutoff_nm?: number | null;
  reflect?: "below" | "above" | null;
  aom_frequency_mhz?: number | null;
  aom_efficiency?: number | null;
  aom_order?: 1 | -1 | null;
  acoustic_velocity_m_s?: number | null;
  fiber_mfd_um?: number | null;
  transmission?: number | null;
  saturation_power_mw?: number | null;
  small_signal_gain_db?: number | null;
  nl_efficiency_per_w?: number | null;
  group?: string | null;
}

export interface Target {
  element_id: string;
  kind: "min_power_mw" | "min_coupling" | "polarization";
  value: number | string;
}

export interface Module {
  id: string;
  title?: string;
  region: [number, number, number, number]; // x, y, w, h (mm, table frame)
  description?: string;
}

export interface LogicSpec {
  inputs: string[];
  outputs: string[];
  threshold_mw: number;
}

export interface Design {
  name: string;
  description?: string;
  modules?: Module[];
  logic?: LogicSpec | null;
  baseplate?: Baseplate;
  sources: Source[];
  elements?: Element[];
  targets?: Target[];
  notes?: string;
}

// ───────────── trace result ─────────────

export type Complex = [number, number];

export interface Segment {
  id: string;
  branch: string;
  source_id: string;
  start: Vec2;
  end: Vec2;
  direction_deg: number;
  length_mm: number;
  wavelength_nm: number;
  freq_shift_mhz: number;
  power_mw: number;
  jones: [Complex, Complex];
  polarization_label: string;
  waist_z_mm: number;
  rayleigh_mm: number;
  w0_mm: number;
  w_start_mm: number;
  w_end_mm: number;
  start_element?: string | null;
  end_element?: string | null;
  end_reason: "element" | "escaped" | "absorbed" | "max_depth";
}

export interface ElementHit {
  segment_id: string;
  power_in_mw: number;
  w_mm: number;
  clip_loss: number;
  offset_mm: number;
}

export interface PlacedElement {
  id: string;
  type: ElementType;
  placed: boolean;
  position?: Vec2 | null;
  angle_deg?: number | null;
  hits: ElementHit[];
  coupling_efficiency?: number | null;
  power_out_mw?: number | null;
  error?: string | null;
}

export interface TraceResult {
  segments: Segment[];
  elements: PlacedElement[];
  branches: string[];
}

// ───────────── verify report ─────────────

export interface Check {
  id: string;
  severity: "error" | "warning" | "info";
  message: string;
  element_id?: string | null;
  segment_id?: string | null;
  value?: number | null;
  limit?: number | null;
}

export interface VerifyReport {
  passed: boolean;
  score: number;
  checks: Check[];
  metrics: Record<string, number>;
}

// ───────────── API ─────────────

export interface ExampleInfo {
  name: string;
  title: string;
}

export interface TraceResponse {
  trace: TraceResult;
  report: VerifyReport;
}

export type Stage = "plan" | "design" | "verify" | "repair" | "extract" | "done";

export type AgentEvent =
  | { type: "status"; stage: Stage | string; message: string }
  | { type: "candidate"; index: number; design: Design; report: VerifyReport; trace: TraceResult }
  | { type: "extraction"; graph: Record<string, unknown> }
  | { type: "final"; design: Design; report: VerifyReport; trace: TraceResult; summary?: { objective_before: number; objective_after: number; steps: number } }
  | { type: "modules"; modules: Module[]; table?: Partial<Baseplate>; links?: FiberLink[]; title?: string }
  | { type: "module_done"; module_id: string; design: Design; report?: VerifyReport; trace?: TraceResult }
  | { type: "module_failed"; module_id: string; message: string }
  | { type: "match"; rows: MatchRow[]; summary: { matched: number; in_figure: number } }
  | { type: "error"; message: string }
  | AgentStateEvent
  | { type: "llm_call"; agent_id: string; call_id: string; model: string; thinking_level: string; prompt_tokens: number; output_tokens: number; thought_tokens: number; latency_ms: number; ttft_ms?: number | null; finish_reason: string }
  | { type: "thought"; agent_id: string; text: string }
  | { type: "tool"; agent_id: string; name: string; summary: string; elapsed_ms: number }
  | IterationEvent
  | { type: "figure"; url: string; citation?: string }
  | { type: "tokens"; agent_id: string; call_id?: string; kind: "output" | "thought"; text: string; n_tokens_so_far?: number; tps?: number }
  | TuneStart
  | TuneStep
  | TuneDone;

export interface TuneStart { type: "tune_start"; order: string[]; objective: string; baseline: { objective: number; delivered_mw: number; score: number } }
export interface TuneStep {
  type: "tune_step"; element_id: string; field: string; value: number; objective: number;
  metrics: { delivered_mw: number; coupling: number | null; score: number }; best_so_far: boolean; patch: Partial<Element>;
}
export interface TuneDone { type: "tune_done"; element_id: string; field: string; from: number; to: number; gain: number }

export interface PaperFigure { id: string; url: string; caption: string; setup_score: number }
export interface Paper {
  arxiv_id: string; title: string; authors: string[]; year: number | null; abs_url: string; license: string | null; figures: PaperFigure[];
}

export interface AgentStateEvent {
  type: "agent";
  agent_id: string;
  role: string;
  state: "queued" | "running" | "done" | "error" | "cancelled";
  title: string;
  parent?: string | null;
  model?: string | null;
  thinking_level?: string | null;
  elapsed_ms?: number | null;
  message?: string | null;
}

export interface Change {
  op: "add" | "remove" | "move" | "rotate" | "param" | "retarget";
  element_id: string;
  field?: string | null;
  from?: unknown;
  to?: unknown;
  note?: string | null;
}

export interface IterationEvent {
  type: "iteration";
  agent_id: string;
  seq: number;
  label: string;
  design: Design;
  trace: TraceResult;
  report: VerifyReport;
  parent_seq?: number | null;
  diff?: Change[];
}

export interface FiberLink {
  from_module: string;
  to_module: string;
  purpose?: string;
}

export interface MatchRow {
  figure_label: string;
  figure_type: string;
  design_id: string | null;
  status: "matched" | "missing" | "extra";
}

// ───────── build kit (BOM + printed baseplate) ─────────
export interface BomRow {
  part_number: string; description: string; vendor: string; qty: number; unit_price_usd: number | null;
  url: string | null; element_ids: string[]; price_note?: string;
}
export interface PrintedPart { name: string; file: string; volume_cm3: number; est_print_h: number; est_filament_g: number; notes: string }
export interface Bom {
  design?: string;
  purchased: BomRow[];
  hardware: BomRow[];
  printed: PrintedPart[];
  plate?: { width_mm: number; height_mm: number; thickness_mm: number; table_holes: number; element_sites: number; pin_holes: number; tiles: number };
  totals: { purchased_parts: number; hardware_parts: number; printed_parts: number; est_cost_usd: number; est_print_h: number; est_filament_g: number; price_note: string };
  stl_urls?: Record<string, string>;
}
