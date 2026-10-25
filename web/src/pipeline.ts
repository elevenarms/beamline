import { create } from "zustand";
import type { Design, TuneDone } from "./types";
import { useStore } from "./store";
import { useConsole } from "./consoleStore";
import { usePip } from "./panels/PaperPip";
import { captureCanvas } from "./panels/CoverArt";

// Final-output chain after a paper build: (fly-in → beams) → capture + faithful cover ∥ tuning tour → build document.
// Also owns the 3:00 run clock.

export type ClockStage = "search" | "figure" | "synth" | "verified" | "flyin" | "tuning" | "cover" | "pdf";
export const CLOCK_STAGES: { id: ClockStage; label: string }[] = [
  { id: "search", label: "search" },
  { id: "figure", label: "reading figure" },
  { id: "synth", label: "synthesizing" },
  { id: "verified", label: "verified" },
  { id: "flyin", label: "fly-in" },
  { id: "tuning", label: "tuning" },
  { id: "cover", label: "cover" },
  { id: "pdf", label: "PDF" },
];

interface PipelineState {
  // run clock
  clockT0: number | null;
  clockEnd: number | null;
  budgetS: number;
  backendElapsed: { s: number; at: number } | null;
  marks: Partial<Record<ClockStage, number>>;
  // outputs
  citation: string;
  license: string | null;
  figureUrl: string | null;
  coverUrl: string | null;
  coverBusy: boolean;
  tuneDones: TuneDone[];
  tuneSummary: Record<string, unknown> | null;
  tuneFinished: boolean;
  docUrl: string | null;
  docBusy: boolean;
  docErr: string | null;
  startClock: (citation: string, figureUrl: string | null, license?: string | null) => void;
  mark: (s: ClockStage) => void;
  budget: (elapsed_s: number, deadline_s?: number) => void;
  startCover: (onCaptured?: () => void) => Promise<void>;
  onTuneDone: (d: TuneDone) => void;
  onTuneFinal: (summary: Record<string, unknown> | null) => void;
  buildDoc: (force?: boolean) => Promise<void>;
}


export const usePipeline = create<PipelineState>((set, get) => ({
  clockT0: null,
  clockEnd: null,
  budgetS: 180,
  backendElapsed: null,
  marks: {},
  citation: "",
  license: null,
  figureUrl: null,
  coverUrl: null,
  coverBusy: false,
  tuneDones: [],
  tuneSummary: null,
  tuneFinished: false,
  docUrl: null,
  docBusy: false,
  docErr: null,

  startClock: (citation, figureUrl, license = null) => {
    const old = get().docUrl;
    if (old?.startsWith("blob:")) URL.revokeObjectURL(old);
    set({ clockT0: performance.now(), clockEnd: null, budgetS: 180, backendElapsed: null, marks: { search: 0 }, citation, figureUrl, license, coverUrl: null, coverBusy: false, tuneDones: [], tuneSummary: null, tuneFinished: false, docUrl: null, docBusy: false, docErr: null });
  },
  mark: (s) => {
    const t0 = get().clockT0;
    if (t0 == null || get().marks[s] != null) return;
    set((st) => ({ marks: { ...st.marks, [s]: performance.now() - t0 } }));
  },
  // the backend's deadline covers synthesis only; the run clock budget stays 3:00 end to end
  budget: (elapsed_s) => set({ backendElapsed: { s: elapsed_s, at: performance.now() } }),

  startCover: async (onCaptured) => {
    const design = useStore.getState().design;
    if (!design || get().coverBusy) { onCaptured?.(); return; }
    set({ coverBusy: true });
    const con = useConsole.getState();
    const id = "artist-faithful";
    try {
      let png: string;
      try { png = await captureCanvas(); } finally { onCaptured?.(); }
      con.ingest({ type: "agent", agent_id: id, role: "artist", state: "running", title: "Cover artist · faithful", parent: null, model: "Nano Banana 2", thinking_level: null });
      const t = performance.now();
      const r = await fetch("/api/render_cover", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ design, screenshot: png, styles: ["faithful"] }) });
      let url = png; // fallback: the captured view itself
      let model = "capture";
      if (r.ok) {
        const j = (await r.json()) as { images: { data_url?: string; model?: string; error?: string | null }[] };
        if (j.images?.[0]?.data_url) { url = j.images[0].data_url!; model = j.images[0].model ?? "Nano Banana 2"; }
      }
      const el = performance.now() - t;
      con.ingest({ type: "tool", agent_id: id, name: "render", summary: `${model}  faithful  ${(el / 1000).toFixed(1)} s${r.ok ? "" : `  (HTTP ${r.status}, using the captured view)`}`, elapsed_ms: el });
      con.ingest({ type: "agent", agent_id: id, role: "artist", state: "done", title: "Cover artist · faithful", parent: null, model, thinking_level: null, elapsed_ms: el });
      set({ coverUrl: url });
    } catch (e) {
      con.ingest({ type: "agent", agent_id: id, role: "artist", state: "error", title: "Cover artist · faithful", parent: null, model: null, thinking_level: null, message: String(e) });
    } finally {
      set({ coverBusy: false });
      get().mark("cover");
      if (get().tuneFinished) get().buildDoc();
    }
  },

  onTuneDone: (d) => set((s) => ({ tuneDones: [...s.tuneDones, d] })),
  onTuneFinal: (summary) => {
    set({ tuneSummary: summary, tuneFinished: true });
    if (!get().coverBusy && get().clockT0 != null) get().buildDoc();
  },

  buildDoc: async (force = false) => {
    const st = get();
    const design = useStore.getState().design;
    if (!design || st.docBusy) return;
    if (!force && st.docUrl) return;
    set({ docBusy: true, docErr: null });
    if (!get().coverUrl && force) await get().startCover();
    const con = useConsole.getState();
    const id = "publisher";
    con.ingest({ type: "agent", agent_id: id, role: "synth", state: "running", title: "Publisher · build document", parent: null, model: null, thinking_level: null });
    const t = performance.now();
    let url: string;
    let note = "";
    try {
      const body = {
        design, cover_data_url: get().coverUrl, citation: get().citation, license: get().license ?? undefined, figure_url_or_data: get().figureUrl,
        tune_summary: get().tuneDones.length || get().tuneSummary ? { ...(get().tuneSummary ?? {}), changes: get().tuneDones } : undefined,
      };
      const r = await fetch("/api/build_doc", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      url = URL.createObjectURL(await r.blob());
    } catch (e) {
      // offline / endpoint not deployed: a printable HTML build sheet instead of the PDF
      url = URL.createObjectURL(new Blob([fallbackDoc(design, get().coverUrl, get().citation, get().tuneDones, useStore.getState().report?.metrics ?? {})], { type: "text/html" }));
      note = `  (${(e as Error).message}; printable HTML fallback)`;
    }
    const el = performance.now() - t;
    con.ingest({ type: "tool", agent_id: id, name: "build_doc", summary: `build document ready  ${(el / 1000).toFixed(1)} s${note}`, elapsed_ms: el });
    con.ingest({ type: "agent", agent_id: id, role: "synth", state: "done", title: "Publisher · build document", parent: null, model: null, thinking_level: null, elapsed_ms: el });
    set({ docUrl: url, docBusy: false });
    usePip.getState().showDoc(url, design.name);
    get().mark("pdf");
    if (get().clockT0 != null && get().clockEnd == null) set({ clockEnd: performance.now() });
  },
}));

function esc(s: string) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}

function fallbackDoc(d: Design, cover: string | null, citation: string, tunes: TuneDone[], metrics: Record<string, number>): string {
  const rows = (d.elements ?? []).map((e) => `<tr><td>${esc(e.id)}</td><td>${esc(e.type)}</td><td>${esc(e.label ?? "")}</td><td>${esc(e.part_number ?? "")}</td></tr>`).join("");
  const tr = tunes.map((t) => `<tr><td>${esc(t.element_id)}</td><td>${esc(t.field)}</td><td>${t.from.toFixed(3)} → ${t.to.toFixed(3)}</td><td>${(t.gain * 100).toFixed(1)} %</td></tr>`).join("");
  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(d.name)} build document</title>
<style>body{font:13px/1.5 "IBM Plex Sans",system-ui,sans-serif;color:#1b1f24;margin:32px;max-width:760px}h1{font:700 30px "Times New Roman",serif;margin:0}h2{font-size:14px;text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid #ccc;padding-bottom:3px;margin-top:24px}
table{border-collapse:collapse;width:100%;font-size:12px}td,th{border-bottom:1px solid #e3e3e3;padding:3px 6px;text-align:left}img{max-width:100%;border:1px solid #ddd}.muted{color:#666}</style></head><body>
<h1>BEAMTEAM · build document</h1><div class="muted">${esc(d.name)} · ${new Date().toLocaleString()}</div>
${citation ? `<p class="muted">Reproduced from: ${esc(citation)}</p>` : ""}
${cover ? `<img src="${cover}" alt="cover">` : ""}
<h2>Summary</h2><p>${esc(d.description ?? "")}</p><p>Delivered ${(metrics.delivered_mw ?? 0).toFixed(2)} mW of ${(metrics.input_mw ?? 0).toFixed(1)} mW input.</p>
<h2>Components</h2><table><tr><th>ID</th><th>Type</th><th>Label</th><th>Part</th></tr>${rows}</table>
${tr ? `<h2>Alignment</h2><table><tr><th>Element</th><th>Field</th><th>Change</th><th>Gain</th></tr>${tr}</table>` : ""}
<p class="muted">Offline build sheet (the PDF service was unavailable). Print to PDF from the browser.</p></body></html>`;
}
