// A compact client-side tracer + verifier used in mock / offline mode. It mirrors the contract
// semantics of backend/optics (placement, branch naming, Jones polarization, Gaussian q-parameter)
// closely enough that edits reflow live in the demo even if the backend is down.
import type {
  Check, Complex, Design, Element, ElementHit, PlacedElement, Segment, TraceResponse, Vec2,
} from "../types";
import { DEFAULT_BASEPLATE, TERMINATING } from "../types";

const D2R = Math.PI / 180;
const R2D = 180 / Math.PI;

type C = Complex;
const c = (re: number, im = 0): C => [re, im];
const cadd = (a: C, b: C): C => [a[0] + b[0], a[1] + b[1]];
const cmul = (a: C, b: C): C => [a[0] * b[0] - a[1] * b[1], a[0] * b[1] + a[1] * b[0]];
const cscale = (a: C, s: number): C => [a[0] * s, a[1] * s];
const cabs2 = (a: C) => a[0] * a[0] + a[1] * a[1];
const cexp = (phi: number): C => [Math.cos(phi), Math.sin(phi)];
const cconj = (a: C): C => [a[0], -a[1]];
const cinv = (a: C): C => {
  const d = cabs2(a) || 1e-30;
  return [a[0] / d, -a[1] / d];
};

type Jones = [C, C];

function normJones(j: Jones): Jones {
  const n = Math.sqrt(cabs2(j[0]) + cabs2(j[1]));
  if (n < 1e-12) return [c(1), c(0)];
  return [cscale(j[0], 1 / n), cscale(j[1], 1 / n)];
}

function polToJones(p: Design["sources"][number]["polarization"]): Jones {
  const s = Math.SQRT1_2;
  switch (p) {
    case undefined:
    case "H": return [c(1), c(0)];
    case "V": return [c(0), c(1)];
    case "D": return [c(s), c(s)];
    case "A": return [c(s), c(-s)];
    case "R": return [c(s), c(0, -s)];
    case "L": return [c(s), c(0, s)];
    default: {
      const a = Number(p) * D2R;
      return [c(Math.cos(a)), c(Math.sin(a))];
    }
  }
}

export function polarizationLabel(j: Jones): string {
  const [ex, ey] = normJones(j);
  const s1 = cabs2(ex) - cabs2(ey);
  const x = cmul(ex, cconj(ey));
  const s2 = 2 * x[0];
  const s3 = -2 * x[1];
  if (Math.abs(s3) > 0.97) return s3 > 0 ? "R" : "L";
  if (Math.abs(s3) < 0.05) {
    let ang = 0.5 * Math.atan2(s2, s1) * R2D;
    if (ang < -90) ang += 180;
    const near = (v: number) => Math.abs(ang - v) < 2;
    if (near(0)) return "H";
    if (near(90) || near(-90)) return "V";
    if (near(45)) return "D";
    if (near(-45)) return "A";
    return `linear ${Math.round(ang)}°`;
  }
  return "elliptical";
}

function waveplate(j: Jones, fastDeg: number, retard: number): Jones {
  const t = fastDeg * D2R;
  const co = Math.cos(t), si = Math.sin(t);
  // rotate into fast-axis frame
  const a = cadd(cscale(j[0], co), cscale(j[1], si));
  const b = cadd(cscale(j[0], -si), cscale(j[1], co));
  const b2 = cmul(b, cexp(retard));
  return [cadd(cscale(a, co), cscale(b2, -si)), cadd(cscale(a, si), cscale(b2, co))];
}

interface BeamState {
  branch: string;
  sourceId: string;
  pos: Vec2;
  dir: number; // deg
  lambda: number; // nm
  power: number;
  jones: Jones;
  q: C; // complex beam parameter at pos: (z - z_waist) + i zR, mm
  shift: number;
  last: string; // element or source id
  depth: number;
}

const dirVec = (deg: number): Vec2 => [Math.cos(deg * D2R), Math.sin(deg * D2R)];
const norm360 = (d: number) => ((d % 360) + 360) % 360;

function reflectDir(inDeg: number, normalDeg: number): number {
  const v = dirVec(inDeg), n = dirVec(normalDeg);
  const dot = v[0] * n[0] + v[1] * n[1];
  const r: Vec2 = [v[0] - 2 * dot * n[0], v[1] - 2 * dot * n[1]];
  return norm360(Math.atan2(r[1], r[0]) * R2D);
}

function bisectNormal(inDeg: number, outDeg: number): number {
  const a = dirVec(inDeg + 180), b = dirVec(outDeg);
  return norm360(Math.atan2(a[1] + b[1], a[0] + b[0]) * R2D);
}

function wOf(q: C, lambdaNm: number): number {
  const zr = q[1];
  const lam = lambdaNm * 1e-6;
  const w0 = Math.sqrt((zr * lam) / Math.PI);
  return w0 * Math.sqrt(1 + (q[0] / zr) ** 2);
}

function defaultAperture(type: Element["type"]): number {
  if (type === "fiber_coupler") return 6;
  if (type === "iris") return 2;
  return 12.7;
}

export function traceDesign(design: Design): TraceResponse {
  const plate = { ...DEFAULT_BASEPLATE, ...(design.baseplate ?? {}) };
  const elements = design.elements ?? [];
  const segments: Segment[] = [];
  const placed = new Map<string, PlacedElement>();
  for (const e of elements) placed.set(e.id, { id: e.id, type: e.type, placed: false, hits: [] });
  const branches: string[] = [];
  const queue: BeamState[] = [];
  let segN = 0;

  for (const s of design.sources) {
    const lam = s.wavelength_nm;
    const w0 = s.waist_mm ?? 0.5;
    const zr = (Math.PI * w0 * w0) / (lam * 1e-6);
    queue.push({
      branch: s.id, sourceId: s.id, pos: [...s.position] as Vec2, dir: s.direction_deg, lambda: lam,
      power: s.power_mw ?? 10, jones: polToJones(s.polarization), q: c(-(s.waist_offset_mm ?? 0), zr),
      shift: 0, last: s.id, depth: 0,
    });
  }

  const atElements = elements.filter((e) => e.at);

  const emit = (st: BeamState, len: number, endEl: string | null, reason: Segment["end_reason"]): Segment => {
    const d = dirVec(st.dir);
    const end: Vec2 = [st.pos[0] + d[0] * len, st.pos[1] + d[1] * len];
    const zr = st.q[1];
    const lam = st.lambda * 1e-6;
    const w0 = Math.sqrt((zr * lam) / Math.PI);
    const qEnd: C = [st.q[0] + len, zr];
    const seg: Segment = {
      id: `s${segN++}`, branch: st.branch, source_id: st.sourceId, start: st.pos, end,
      direction_deg: norm360(st.dir), length_mm: len, wavelength_nm: st.lambda, freq_shift_mhz: st.shift,
      power_mw: st.power, jones: normJones(st.jones), polarization_label: polarizationLabel(st.jones),
      waist_z_mm: -st.q[0], rayleigh_mm: zr, w0_mm: w0, w_start_mm: wOf(st.q, st.lambda), w_end_mm: wOf(qEnd, st.lambda),
      start_element: st.last, end_element: endEl, end_reason: reason,
    };
    segments.push(seg);
    st.pos = end;
    st.q = qEnd;
    return seg;
  };

  const exitDistance = (pos: Vec2, dir: number): number => {
    const [dx, dy] = dirVec(dir);
    const inside = pos[0] >= -1e-6 && pos[0] <= plate.width_mm + 1e-6 && pos[1] >= -1e-6 && pos[1] <= plate.height_mm + 1e-6;
    if (!inside) return 40;
    let t = Infinity;
    if (dx > 1e-9) t = Math.min(t, (plate.width_mm - pos[0]) / dx);
    if (dx < -1e-9) t = Math.min(t, -pos[0] / dx);
    if (dy > 1e-9) t = Math.min(t, (plate.height_mm - pos[1]) / dy);
    if (dy < -1e-9) t = Math.min(t, -pos[1] / dy);
    return Math.max(t, 0) + 25;
  };

  // nearest absolute-placed element hit within maxT along the ray
  const findAtHit = (st: BeamState, maxT: number, visited: Set<string>) => {
    let best: { el: Element; t: number; off: number } | null = null;
    const [dx, dy] = dirVec(st.dir);
    for (const el of atElements) {
      if (el.id === st.last || visited.has(el.id)) continue;
      const rx = el.at![0] - st.pos[0], ry = el.at![1] - st.pos[1];
      const t = rx * dx + ry * dy;
      if (t < 1e-3 || t > maxT) continue;
      const off = Math.abs(rx * dy - ry * dx);
      if (off > (el.aperture_mm ?? defaultAperture(el.type)) / 2 + 2) continue;
      if (!best || t < best.t) best = { el, t, off };
    }
    return best;
  };

  // returns child beams
  const interact = (st: BeamState, el: Element, seg: Segment, offset: number): BeamState[] => {
    const pe = placed.get(el.id)!;
    const w = seg.w_end_mm;
    const ap = el.aperture_mm ?? defaultAperture(el.type);
    const a = ap / 2;
    const clip = Math.min(1, Math.exp((-2 * Math.max(a - offset, 0) ** 2) / (w * w)));
    const hit: ElementHit = { segment_id: seg.id, power_in_mw: st.power, w_mm: w, clip_loss: clip, offset_mm: offset };
    pe.hits.push(hit);
    pe.placed = true;
    pe.position = [...st.pos] as Vec2;
    const inDir = st.dir;
    let axis = el.angle_deg ?? inDir;
    const out: BeamState[] = [];
    const base = (): BeamState => ({ ...st, pos: [...st.pos] as Vec2, last: el.id, depth: st.depth + 1, power: st.power * (1 - (el.type === "iris" ? clip : 0)) });

    switch (el.type) {
      case "mirror": {
        const normal = el.angle_deg ?? (el.out_direction_deg != null ? bisectNormal(inDir, el.out_direction_deg) : inDir + 180);
        axis = normal;
        const b = base();
        b.dir = reflectDir(inDir, normal);
        b.jones = [st.jones[0], cscale(st.jones[1], -1)];
        out.push(b);
        break;
      }
      case "lens": {
        const b = base();
        const f = el.focal_length_mm ?? 100;
        const inv = cinv(st.q);
        b.q = cinv([inv[0] - 1 / f, inv[1]]);
        out.push(b);
        break;
      }
      case "half_wave_plate":
      case "quarter_wave_plate": {
        const b = base();
        b.jones = waveplate(st.jones, el.fast_axis_deg ?? 0, el.type === "half_wave_plate" ? Math.PI : Math.PI / 2);
        out.push(b);
        break;
      }
      case "pbs":
      case "beamsplitter":
      case "sampler":
      case "dichroic": {
        // reflecting surface normal sits at axis + 135°, so a beam along the axis reflects to axis + 90°
        const rDir = reflectDir(inDir, axis + 135);
        const t = base(), r = base();
        t.branch = `${st.branch}.t`;
        r.branch = `${st.branch}.r`;
        r.dir = rDir;
        if (el.type === "pbs") {
          const pH = cabs2(st.jones[0]), pV = cabs2(st.jones[1]), tot = pH + pV || 1;
          t.power = st.power * (pH / tot);
          r.power = st.power * (pV / tot);
          t.jones = [c(1), c(0)];
          r.jones = [c(0), c(1)];
        } else if (el.type === "dichroic") {
          const below = st.lambda < (el.cutoff_nm ?? 700);
          const refl = (el.reflect ?? "below") === "below" ? below : !below;
          t.power = refl ? 0 : st.power;
          r.power = refl ? st.power : 0;
        } else {
          const R = el.split_ratio ?? (el.type === "sampler" ? 0.05 : 0.5);
          t.power = st.power * (1 - R);
          r.power = st.power * R;
          r.jones = [st.jones[0], cscale(st.jones[1], -1)];
        }
        if (t.power > 1e-6) out.push(t);
        if (r.power > 1e-6) out.push(r);
        break;
      }
      case "aom": {
        const f = el.aom_frequency_mhz ?? 80;
        const eff = el.aom_efficiency ?? 0.8;
        const order = el.aom_order ?? 1;
        const v = el.acoustic_velocity_m_s ?? 4200;
        const sepDeg = ((st.lambda * 1e-9 * f * 1e6) / v) * R2D;
        const z = base(), d = base();
        z.branch = `${st.branch}.0`;
        z.power = st.power * (1 - eff);
        d.branch = `${st.branch}.${order > 0 ? "+1" : "-1"}`;
        d.power = st.power * eff;
        d.dir = norm360(inDir + order * sepDeg);
        d.shift = st.shift + order * f;
        out.push(d, z);
        break;
      }
      case "iris":
        out.push(base());
        break;
      case "vapor_cell": {
        const b = base();
        b.power *= el.transmission ?? 1.0;
        out.push(b);
        break;
      }
      case "isolator": {
        const fwd = Math.cos((inDir - (el.angle_deg ?? inDir)) * D2R) > 0;
        if (fwd) {
          const b = base();
          b.power *= el.transmission ?? 0.9;
          out.push(b);
        }
        break;
      }
      case "fiber_coupler": {
        const f = el.focal_length_mm ?? 11;
        const lam = st.lambda * 1e-6;
        const wf = (lam * f) / (Math.PI * Math.max(w, 1e-6));
        const wm = ((el.fiber_mfd_um ?? 5) / 2) * 1e-3;
        const overlap = ((2 * wf * wm) / (wf * wf + wm * wm)) ** 2;
        const tilt = Math.abs(Math.sin((inDir - (axis + 180)) * D2R));
        const eta = overlap * (1 - clip) * Math.exp(-((tilt * 200) ** 2));
        pe.coupling_efficiency = eta;
        pe.power_out_mw = (pe.power_out_mw ?? 0) + st.power * eta;
        break;
      }
      case "photodiode":
      case "beam_dump":
        pe.power_out_mw = (pe.power_out_mw ?? 0) + st.power * (1 - clip);
        break;
    }
    pe.angle_deg = norm360(axis);
    return out;
  };

  let guard = 0;
  while (queue.length && guard++ < 96) {
    const st = queue.shift()!;
    if (!branches.includes(st.branch)) branches.push(st.branch);
    const onBeam = elements.filter((e) => e.beam === st.branch && e.distance_mm != null && !e.at);
    const visited = new Set<string>();
    let terminated = false;
    let k = 0;
    while (!terminated) {
      const next = onBeam[k];
      const maxT = next ? Math.max(next.distance_mm!, 0.01) : exitDistance(st.pos, st.dir);
      const atHit = findAtHit(st, next ? maxT - 1e-3 : maxT, visited);
      let el: Element;
      let len: number;
      let off = 0;
      if (atHit) {
        el = atHit.el; len = atHit.t; off = atHit.off; visited.add(el.id);
      } else if (next) {
        el = next; len = maxT; k++;
      } else {
        emit(st, len = maxT, null, "escaped");
        break;
      }
      const seg = emit(st, len, el.id, "element");
      const kids = interact(st, el, seg, off);
      if (TERMINATING.has(el.type) || kids.length === 0) { terminated = true; break; }
      const same = kids.find((b) => b.branch === st.branch);
      for (const b of kids) if (b !== same) { if (b.depth < 40) queue.push(b); }
      if (!same) { terminated = true; break; }
      Object.assign(st, same);
    }
    // anything left on this branch after a terminating/splitting element is unplaced
    for (const e of onBeam.slice(k)) {
      const pe = placed.get(e.id)!;
      if (!pe.placed) pe.error = `branch "${st.branch}" ends before ${e.id} (split or terminated upstream)`;
    }
  }

  for (const e of elements) {
    const pe = placed.get(e.id)!;
    if (pe.placed) continue;
    if (e.at) {
      pe.position = e.at;
      pe.angle_deg = e.angle_deg ?? e.out_direction_deg ?? 0;
      pe.placed = true;
      pe.error = "not illuminated by any beam";
    } else if (!pe.error) {
      pe.error = branches.includes(e.beam ?? "") ? "could not place" : `branch "${e.beam}" does not exist`;
    }
  }

  const trace = { segments, elements: elements.map((e) => placed.get(e.id)!), branches };
  return { trace, report: verifyDesign(design, trace) };
}

export function verifyDesign(design: Design, trace: TraceResponse["trace"]): TraceResponse["report"] {
  const plate = { ...DEFAULT_BASEPLATE, ...(design.baseplate ?? {}) };
  const checks: Check[] = [];
  const inputMw = design.sources.reduce((a, s) => a + (s.power_mw ?? 10), 0);

  for (const pe of trace.elements) {
    if (!pe.placed || (pe.error && pe.error !== "not illuminated by any beam")) {
      checks.push({ id: "unplaced", severity: "error", message: `${pe.id}: ${pe.error ?? "not placed"}`, element_id: pe.id });
    } else if (pe.error) {
      checks.push({ id: "unplaced", severity: "warning", message: `${pe.id}: ${pe.error}`, element_id: pe.id });
    }
    for (const h of pe.hits) {
      if (h.clip_loss > 0.01 && pe.type !== "iris") {
        checks.push({
          id: "clipping", severity: h.clip_loss > 0.1 ? "error" : "warning",
          message: `${pe.id} clips ${(h.clip_loss * 100).toFixed(1)}% of the beam (w = ${h.w_mm.toFixed(2)} mm)`,
          element_id: pe.id, segment_id: h.segment_id, value: h.clip_loss, limit: 0.01,
        });
      }
    }
    if (pe.position) {
      const [x, y] = pe.position;
      if (x < 0 || y < 0 || x > plate.width_mm || y > plate.height_mm) {
        checks.push({ id: "off_table", severity: "error", message: `${pe.id} sits off the baseplate at (${x.toFixed(0)}, ${y.toFixed(0)}) mm`, element_id: pe.id });
      }
    }
  }
  const pos = trace.elements.filter((p) => p.position && p.placed);
  for (let i = 0; i < pos.length; i++) {
    for (let j = i + 1; j < pos.length; j++) {
      const a = pos[i].position!, b = pos[j].position!;
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (d < 14 && pos[i].type !== "aom" && pos[j].type !== "aom") {
        checks.push({ id: "collision", severity: "warning", message: `${pos[i].id} and ${pos[j].id} are only ${d.toFixed(1)} mm apart`, element_id: pos[j].id, value: d, limit: 14 });
      }
    }
  }
  let stray = 0;
  for (const s of trace.segments) {
    if (s.end_reason === "escaped" && s.power_mw > 0.05) {
      stray += s.power_mw;
      checks.push({
        id: "stray_beam", severity: s.power_mw > 5 ? "error" : "warning",
        message: `${s.power_mw.toFixed(2)} mW on ${s.branch} leaves the table unblocked`, segment_id: s.id, value: s.power_mw, limit: 0.05,
      });
    }
  }
  let delivered = 0;
  for (const pe of trace.elements) if (pe.type === "fiber_coupler" || pe.type === "photodiode") delivered += pe.power_out_mw ?? 0;

  let targetsMet = true;
  for (const t of design.targets ?? []) {
    const pe = trace.elements.find((p) => p.id === t.element_id);
    if (t.kind === "min_power_mw") {
      const v = pe?.power_out_mw ?? 0;
      const ok = v >= Number(t.value);
      targetsMet &&= ok;
      checks.push({ id: "target", severity: ok ? "info" : "error", message: `${t.element_id} receives ${v.toFixed(2)} mW (target ≥ ${t.value} mW)`, element_id: t.element_id, value: v, limit: Number(t.value) });
    } else if (t.kind === "min_coupling") {
      const v = pe?.coupling_efficiency ?? 0;
      const ok = v >= Number(t.value);
      targetsMet &&= ok;
      checks.push({ id: "target", severity: ok ? "info" : "error", message: `${t.element_id} coupling ${(v * 100).toFixed(1)}% (target ≥ ${(Number(t.value) * 100).toFixed(0)}%)`, element_id: t.element_id, value: v, limit: Number(t.value) });
    } else {
      const seg = trace.segments.find((s) => s.end_element === t.element_id);
      const ok = seg?.polarization_label === t.value;
      targetsMet &&= !!ok;
      checks.push({ id: "target", severity: ok ? "info" : "error", message: `${t.element_id} polarization ${seg?.polarization_label ?? "—"} (target ${t.value})`, element_id: t.element_id });
    }
  }
  const nErr = checks.filter((c) => c.severity === "error").length;
  const nWarn = checks.filter((c) => c.severity === "warning").length;
  checks.push({ id: "summary", severity: "info", message: `${delivered.toFixed(2)} of ${inputMw.toFixed(1)} mW delivered to detectors/fibers` });
  const eff = inputMw > 0 ? delivered / inputMw : 0;
  const score = Math.max(0, Math.min(100, 55 + 45 * eff - 18 * nErr - 5 * nWarn - 20 * (stray / Math.max(inputMw, 1e-9))));
  return {
    passed: nErr === 0 && targetsMet,
    score: Math.round(score * 10) / 10,
    checks,
    metrics: {
      input_mw: inputMw, delivered_mw: delivered, stray_mw: stray, n_elements: trace.elements.length,
      n_segments: trace.segments.length, efficiency: eff,
    },
  };
}
