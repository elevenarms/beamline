import type { AgentEvent, Design, ExampleInfo, TraceResponse } from "./types";
import { traceDesign } from "./mock/tracer";
import { MOCK_EXAMPLES } from "./mock/designs";
import { mockAgentStream } from "./mock/agent";
import { mockPyOpticL } from "./mock/export";

// Mock mode: ?mock=1 forces it; otherwise we fall back automatically when /api is unreachable.
const params = new URLSearchParams(window.location.search);
let forcedMock = params.get("mock") === "1";
let backendDown = false;
const listeners = new Set<(m: boolean) => void>();

export function isMock() {
  return forcedMock || backendDown;
}
export function onMockChange(fn: (m: boolean) => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
function setBackendDown(v: boolean) {
  if (backendDown === v) return;
  backendDown = v;
  listeners.forEach((f) => f(isMock()));
}
export function setForcedMock(v: boolean) {
  forcedMock = v;
  listeners.forEach((f) => f(isMock()));
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new HttpError(r.status, body.slice(0, 400) || r.statusText);
  }
  return r.json() as Promise<T>;
}

export class HttpError extends Error {
  constructor(public status: number, msg: string) {
    super(`HTTP ${status}: ${msg}`);
  }
}

// network / proxy failures (backend not running) → fall back to mock; real 4xx from backend → surface
function isOffline(e: unknown) {
  if ((e as Error)?.name === "AbortError") return false;
  if (e instanceof HttpError) return e.status >= 500 || e.status === 404;
  return true;
}

async function withFallback<T>(real: () => Promise<T>, mock: () => T | Promise<T>): Promise<T> {
  if (forcedMock) return mock();
  try {
    const v = await real();
    setBackendDown(false);
    return v;
  } catch (e) {
    if (isOffline(e)) {
      setBackendDown(true);
      return mock();
    }
    throw e;
  }
}

export function listExamples(): Promise<ExampleInfo[]> {
  return withFallback(
    async () => {
      const real = await json<ExampleInfo[]>("/api/examples");
      // always offer the bundled mock fixtures too, flagged with a prefix
      return [...real, ...MOCK_EXAMPLES.map((m) => ({ name: `mock:${m.name}`, title: m.title }))];
    },
    () => MOCK_EXAMPLES.map((m) => ({ name: `mock:${m.name}`, title: m.title })),
  );
}

export async function getExample(name: string): Promise<Design> {
  if (name.startsWith("mock:")) {
    const m = MOCK_EXAMPLES.find((x) => `mock:${x.name}` === name);
    if (!m) throw new Error(`unknown mock example ${name}`);
    return structuredClone(m.design);
  }
  return json<Design>(`/api/examples/${encodeURIComponent(name)}`);
}

export function trace(design: Design, signal?: AbortSignal): Promise<TraceResponse> {
  return withFallback(
    () => json<TraceResponse>("/api/trace", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ design }),
      signal,
    }),
    () => traceDesign(design),
  );
}

export function exportPyOpticL(design: Design): Promise<string> {
  return withFallback(
    async () => (await json<{ code: string }>("/api/export/pyopticl", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ design }),
    })).code,
    () => mockPyOpticL(design),
  );
}

// ───────── SSE over POST (EventSource can't POST) ─────────

async function* readSSE(resp: Response, signal?: AbortSignal): AsyncGenerator<AgentEvent> {
  if (!resp.body) throw new Error("no response body");
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  try {
    while (true) {
      if (signal?.aborted) return;
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      buf = buf.replace(/\r\n/g, "\n");
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const data = block
          .split("\n")
          .filter((l) => l.startsWith("data:"))
          .map((l) => l.slice(5).replace(/^ /, ""))
          .join("\n");
        if (!data) continue;
        try {
          yield JSON.parse(data) as AgentEvent;
        } catch {
          /* ignore malformed */
        }
      }
    }
    const tail = buf.trim();
    if (tail.startsWith("data:")) {
      try { yield JSON.parse(tail.slice(5).trim()) as AgentEvent; } catch { /* */ }
    }
  } finally {
    reader.releaseLock();
  }
}

async function* streamOrMock(
  start: () => Promise<Response>,
  mock: () => AsyncGenerator<AgentEvent>,
  signal?: AbortSignal,
): AsyncGenerator<AgentEvent> {
  if (forcedMock) { yield* mock(); return; }
  let resp: Response;
  try {
    resp = await start();
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
    setBackendDown(true);
    yield* mock();
    return;
  }
  if (!resp.ok) {
    if (resp.status >= 502) { setBackendDown(true); yield* mock(); return; }
    const t = await resp.text().catch(() => "");
    yield { type: "error", message: `HTTP ${resp.status}: ${t.slice(0, 300)}` };
    return;
  }
  setBackendDown(false);
  yield* readSSE(resp, signal);
}

export function designStream(goal: string, candidates = 4, signal?: AbortSignal) {
  return streamOrMock(
    () => fetch("/api/design", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ goal, candidates }),
      signal,
    }),
    () => mockAgentStream("design", goal, signal),
    signal,
  );
}

export function reproduceStream(image: File, notes: string, signal?: AbortSignal) {
  return streamOrMock(
    () => {
      const fd = new FormData();
      fd.append("image", image);
      fd.append("notes", notes);
      return fetch("/api/reproduce", { method: "POST", body: fd, headers: { Accept: "text/event-stream" }, signal });
    },
    () => mockAgentStream("reproduce", notes, signal),
    signal,
  );
}
