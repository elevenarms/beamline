import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Download, Sparkles, X } from "lucide-react";
import { useStore } from "../store";
import { useView } from "../scene/viewStore";
import { useConsole } from "../consoleStore";
import { useDemo } from "../demoStore";
import type { Design } from "../types";

type Style = "faithful" | "cinematic";
interface Result { style: Style; model?: string; data_url?: string; elapsed_s?: number; error?: string | null }
const STYLES: { id: Style; title: string; model: string }[] = [
  { id: "faithful", title: "Faithful", model: "Nano Banana 2" },
  { id: "cinematic", title: "Cinematic", model: "Nano Banana 2.1" },
];

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** iso view, overlays hidden, grab the WebGL canvas, downscale to ≤ 1600 px long side */
export async function captureCanvas(): Promise<string> {
  useView.getState().setPreset("iso");
  useDemo.setState({ capturing: true });
  await sleep(900);
  const src = document.querySelector(".viewport canvas") as HTMLCanvasElement | null;
  if (!src) throw new Error("no canvas");
  const scale = Math.min(1, 1600 / Math.max(src.width, src.height));
  const c = document.createElement("canvas");
  c.width = Math.round(src.width * scale);
  c.height = Math.round(src.height * scale);
  const ctx = c.getContext("2d")!;
  ctx.fillStyle = getComputedStyle(document.body).getPropertyValue("--canvas") || "#eef0f2";
  ctx.fillRect(0, 0, c.width, c.height);
  ctx.drawImage(src, 0, 0, c.width, c.height);
  useDemo.setState({ capturing: false });
  return c.toDataURL("image/png");
}

const issueLine = (name: string) =>
  `Vol. 1 · ${new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })} · ${name.replace(/_/g, " ")}`;

const MAST = "BEAMTEAM";
const MAST_FONT = (px: number) => `700 ${px}px "Times New Roman", Georgia, serif`;
const MAST_SPACING = 0.04; // em
let measureCtx: CanvasRenderingContext2D | null = null;
/** font size (px) at which the masthead (with its letter-spacing) spans `frac` of `width` */
function fitMastSize(width: number, frac = 0.88): number {
  measureCtx ??= document.createElement("canvas").getContext("2d");
  if (!measureCtx) return width * 0.13;
  measureCtx.font = MAST_FONT(100);
  const w100 = measureCtx.measureText(MAST).width + MAST.length * MAST_SPACING * 100;
  return (frac * width * 100) / w100;
}

function Masthead({ name }: { name: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [fs, setFs] = useState(48);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fit = () => setFs(fitMastSize(el.clientWidth));
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return (
    <div className="masthead" ref={ref}>
      <div className="mh-title" style={{ fontSize: fs, letterSpacing: `${MAST_SPACING}em`, marginRight: `-${MAST_SPACING}em` }}>{MAST}</div>
      <div className="mh-issue">{issueLine(name)}</div>
    </div>
  );
}

async function composite(r: Result, withMast: boolean, name: string): Promise<string> {
  const img = new Image();
  img.src = r.data_url!;
  await img.decode();
  const c = document.createElement("canvas");
  c.width = img.naturalWidth;
  c.height = img.naturalHeight;
  const ctx = c.getContext("2d")!;
  ctx.drawImage(img, 0, 0);
  if (withMast) {
    const W = c.width;
    const g = ctx.createLinearGradient(0, 0, 0, W * 0.32);
    g.addColorStop(0, "rgba(0,0,0,0.55)");
    g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, W * 0.32);
    ctx.fillStyle = "#ffffff";
    ctx.textAlign = "center";
    const fs = fitMastSize(W);
    ctx.font = MAST_FONT(fs);
    const ls = MAST_SPACING * fs;
    const c2 = ctx as CanvasRenderingContext2D & { letterSpacing?: string };
    if ("letterSpacing" in c2) {
      c2.letterSpacing = `${ls}px`;
      ctx.fillText(MAST, W / 2 + ls / 2, W * 0.06 + fs * 0.8); // trailing spacing compensated
      c2.letterSpacing = "0px";
    } else {
      ctx.fillText(MAST, W / 2, W * 0.06 + fs * 0.8);
    }
    ctx.font = `400 ${Math.round(W * 0.026)}px "IBM Plex Sans", sans-serif`;
    ctx.fillText(issueLine(name).toUpperCase(), W / 2, W * 0.215);
    ctx.fillRect(W * 0.08, W * 0.235, W * 0.84, Math.max(1, W * 0.002));
  }
  return c.toDataURL("image/png");
}

export default function CoverArt({ open, onClose }: { open: boolean; onClose: () => void }) {
  const design = useStore((s) => s.design);
  const [shot, setShot] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, Result | undefined>>({});
  const [t0, setT0] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [mast, setMast] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !design) return;
    let cancelled = false;
    setResults({}); setErr(null); setShot(null);
    (async () => {
      try {
        const png = await captureCanvas();
        if (cancelled) return;
        setShot(png);
        setT0(Date.now());
        const con = useConsole.getState();
        await Promise.all(STYLES.map(async (st) => {
          const id = `artist-${st.id}`;
          con.ingest({ type: "agent", agent_id: id, role: "artist", state: "running", title: `Cover artist · ${st.title}`, parent: null, model: st.model, thinking_level: null });
          const t = Date.now();
          let r: Result;
          try {
            const resp = await fetch("/api/render_cover", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ design: design as Design, screenshot: png, styles: [st.id] }),
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const j = (await resp.json()) as { images: Result[] };
            r = j.images?.[0] ?? { style: st.id, error: "no image returned" };
          } catch (e) {
            r = { style: st.id, error: (e as Error).message };
          }
          if (cancelled) return;
          setResults((x) => ({ ...x, [st.id]: r }));
          const el = r.elapsed_s ?? (Date.now() - t) / 1000;
          con.ingest({ type: "tool", agent_id: id, name: "render", summary: r.error ? `failed: ${r.error}` : `${r.model ?? st.model}  ${st.id}  ${el.toFixed(1)} s`, elapsed_ms: el * 1000 });
          con.ingest({ type: "agent", agent_id: id, role: "artist", state: r.error ? "error" : "done", title: `Cover artist · ${st.title}`, parent: null, model: r.model ?? st.model, thinking_level: null, elapsed_ms: el * 1000 });
        }));
      } catch (e) {
        useDemo.setState({ capturing: false });
        if (!cancelled) setErr((e as Error).message);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const t = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(t);
  }, [open]);

  if (!open || !design) return null;
  const elapsed = t0 ? (now - t0) / 1000 : 0;
  const download = async (r: Result) => {
    const url = await composite(r, mast, design.name);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${design.name}_${r.style}_cover.png`;
    a.click();
  };

  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal cover-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Cover art">
        <div className="modal-head">
          <Sparkles size={15} />
          <h3>Cover art</h3>
          <span className="muted" style={{ fontSize: 12 }}>{design.name}</span>
          <span className="spacer" />
          <label className="mast-toggle"><input type="checkbox" checked={mast} onChange={(e) => setMast(e.target.checked)} /> Masthead</label>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={15} /></button>
        </div>
        <div className="cover-body">
          {err && <div className="json-err">{err}</div>}
          {STYLES.map((st) => {
            const r = results[st.id];
            return (
              <div key={st.id} className="cover-card">
                <div className="cover-frame">
                  {r?.data_url ? (
                    <>
                      <img src={r.data_url} alt={`${st.title} cover render`} className="cover-img" />
                      {mast && <Masthead name={design.name} />}
                    </>
                  ) : r?.error ? (
                    <div className="cover-wait err">{r.error}</div>
                  ) : (
                    <div className="cover-wait shimmer">
                      {shot && <img src={shot} alt="" className="cover-ghost" />}
                      <span className="mono">{shot ? `rendering… ${elapsed.toFixed(1)} s` : "capturing view…"}</span>
                    </div>
                  )}
                </div>
                <div className="cover-meta">
                  <span><b>{st.title}</b> <span className="muted mono">{r?.model ?? st.model}{r?.elapsed_s ? ` · ${r.elapsed_s.toFixed(1)} s` : ""}</span></span>
                  <button className="btn small" disabled={!r?.data_url} onClick={() => r && download(r)}><Download size={12} /> PNG</button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
