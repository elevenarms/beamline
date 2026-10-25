import { useState } from "react";
import { Bot, Cpu, Play, RotateCcw, Square, Crosshair, Terminal, SlidersHorizontal, Gauge, Activity, CheckCircle2, AlertTriangle } from "lucide-react";
import { useLab } from "../labStore";
import { useStore } from "../store";
import { useConsole } from "../consoleStore";
import { mW } from "../lib/format";

const STEP_SIZES_UM = [0.05, 0.5, 5, 50, 250] as const;
const SPEED_PRESETS = [0.5, 1, 2, 3, 5] as const;

/** Left Mission-Control Column: Run + 1-5x Speed Slider, Overhead Gantry Sliders, Inverted UR5e Joints, Compact X/Y Crib Matrix. */
export function RoboLabLeftColumn() {
  const running = useLab((s) => s.running);
  const phase = useLab((s) => s.phase);
  const statusMessage = useLab((s) => s.statusMessage);
  const wasmReady = useLab((s) => s.wasmReady);
  const wasmVersion = useLab((s) => s.wasmVersion);
  const simTimeS = useLab((s) => s.simTimeS);
  const dofCount = useLab((s) => s.dofCount);
  const playbackSpeed = useLab((s) => s.playbackSpeed);
  const setPlaybackSpeed = useLab((s) => s.setPlaybackSpeed);
  const slots = useLab((s) => s.slots);
  const activeSlotIndex = useLab((s) => s.activeSlotIndex);
  const stageSimMm = useLab((s) => s.stageSimMm);
  const railRangeMm = useLab((s) => s.railRangeMm);
  const railCmdXMm = useLab((s) => s.railCmdXMm);
  const railSimXMm = useLab((s) => s.railSimXMm);
  const carriageCmdYMm = useLab((s) => s.carriageCmdYMm);
  const carriageSimYMm = useLab((s) => s.carriageSimYMm);
  const armSimRad = useLab((s) => s.armSimRad);

  const startAutonomousRun = useLab((s) => s.startAutonomousRun);
  const stopRun = useLab((s) => s.stopRun);
  const indexCribSlot = useLab((s) => s.indexCribSlot);
  const setRailXMm = useLab((s) => s.setRailXMm);
  const setCarriageYMm = useLab((s) => s.setCarriageYMm);
  const setEnabled = useLab((s) => s.setEnabled);
  const design = useStore((s) => s.design);

  const [useLlm, setUseLlm] = useState<boolean>(true);
  const placedCount = slots.filter((s) => s.state === "placed").length;
  const maxPlateY = design?.baseplate?.height_mm ?? 150;
  const progressPct = slots.length > 0 ? Math.round((placedCount / slots.length) * 100) : 0;

  return (
    <div
      className="robo-lab-panel"
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        padding: "10px 12px",
        gap: 10,
        overflow: "hidden",
        boxSizing: "border-box",
      }}
    >
      {/* Header & Exit back to Standard View */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 600, fontSize: 13 }}>
          <Bot size={15} />
          <span>Robotics Workcell</span>
        </div>
        <span className={`pill${wasmReady ? "" : " warn"}`} style={{ fontSize: 10.5 }}>
          <span className="dot" /> MuJoCo {wasmVersion} · {dofCount} DOF
        </span>
      </div>

      {/* Primary Run Button + Live 1x-5x Playback Speed Slider */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", gap: 6 }}>
          {!running ? (
            <button
              className="btn primary"
              style={{ flex: 1, justifyContent: "center", height: 30, fontWeight: 600 }}
              disabled={!design}
              onClick={() => void startAutonomousRun(useLlm)}
            >
              <Play size={14} /> Build &amp; Align Bench
            </button>
          ) : (
            <button
              className="btn"
              style={{ flex: 1, justifyContent: "center", height: 30, borderColor: "var(--err)", color: "var(--err)", fontWeight: 600 }}
              onClick={stopRun}
            >
              <Square size={14} /> Stop Lab Run
            </button>
          )}
          <button
            className="btn small"
            onClick={() => setEnabled(false)}
            title="Return to standard optical layout view"
          >
            Exit Lab
          </button>
        </div>

        {/* Playback Speed Slider (1x - 5x) */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "5px 8px",
            borderRadius: 5,
            background: "var(--bg-2, rgba(148,163,184,0.08))",
            border: "1px solid var(--line)",
          }}
        >
          <Gauge size={13} style={{ flexShrink: 0, color: "var(--muted)" }} />
          <span style={{ fontSize: 11, fontWeight: 500, whiteSpace: "nowrap" }}>Speed</span>
          <input
            type="range"
            min={0.5}
            max={5}
            step={0.5}
            value={playbackSpeed}
            onChange={(e) => setPlaybackSpeed(Number(e.target.value))}
            style={{ flex: 1, minWidth: 50 }}
            aria-label="Playback speed 0.5x to 5x"
          />
          <div style={{ display: "flex", gap: 2 }}>
            {SPEED_PRESETS.map((sp) => (
              <button
                key={sp}
                type="button"
                className={`btn small mono${playbackSpeed === sp ? " active" : ""}`}
                style={{ padding: "1px 5px", fontSize: 10, height: 20 }}
                onClick={() => setPlaybackSpeed(sp)}
              >
                {sp}×
              </button>
            ))}
          </div>
        </div>

        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--muted)", cursor: "pointer" }}>
          <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
          <span>Query live Gemini <code>gemini-4-argon</code> Lab Director</span>
        </label>
      </div>

      {/* Live Phase & Progress Bar */}
      <div
        style={{
          padding: "7px 9px",
          borderRadius: 6,
          background: "var(--bg-2, rgba(148,163,184,0.08))",
          border: "1px solid var(--line)",
          fontSize: 11,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontWeight: 600 }}>
          <span>Phase: {phase.toUpperCase()}</span>
          <span className="mono">
            {placedCount}/{slots.length} placed · {playbackSpeed.toFixed(1)}× · t={simTimeS.toFixed(1)}s
          </span>
        </div>
        <div style={{ height: 4, borderRadius: 2, background: "rgba(148,163,184,0.2)", overflow: "hidden", marginBottom: 5 }}>
          <div
            style={{
              width: `${progressPct}%`,
              height: "100%",
              background: phase === "done" ? "#10b981" : "#38bdf8",
              transition: "width 120ms linear",
            }}
          />
        </div>
        <div className="muted" style={{ fontSize: 10.5, lineHeight: 1.3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title={statusMessage}>
          {statusMessage}
        </div>
      </div>

      {/* Overhead Gantry Linear Sliders (Build Plate X & Bridge Y) */}
      <div style={{ borderTop: "1px solid var(--line)", paddingTop: 8, display: "flex", flexDirection: "column", gap: 5 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
            <SlidersHorizontal size={11} style={{ verticalAlign: "-1px", marginRight: 4 }} />
            Overhead Gantry Slider
          </span>
          <span className="mono muted" style={{ fontSize: 10.5 }}>
            X:{railSimXMm.toFixed(0)} Y:{carriageSimYMm.toFixed(0)} mm
          </span>
        </div>

        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10.5 }}>
          <span className="mono muted" style={{ width: 52 }}>Rail X:</span>
          <input
            type="range"
            min={railRangeMm[0]}
            max={railRangeMm[1]}
            step={1}
            value={railCmdXMm}
            onChange={(e) => setRailXMm(Number(e.target.value))}
            style={{ flex: 1 }}
            aria-label="Overhead Gantry X Slider"
          />
          <span className="mono" style={{ width: 52, textAlign: "right" }}>{railCmdXMm.toFixed(0)} mm</span>
        </label>

        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10.5 }}>
          <span className="mono muted" style={{ width: 52 }}>Bridge Y:</span>
          <input
            type="range"
            min={0}
            max={maxPlateY}
            step={1}
            value={carriageCmdYMm}
            onChange={(e) => setCarriageYMm(Number(e.target.value))}
            style={{ flex: 1 }}
            aria-label="Overhead Gantry Bridge Y Slider"
          />
          <span className="mono" style={{ width: 52, textAlign: "right" }}>{carriageCmdYMm.toFixed(0)} mm</span>
        </label>

        <div style={{ display: "flex", gap: 4 }}>
          <button type="button" className="btn small" style={{ flex: 1, fontSize: 10 }} onClick={() => setRailXMm(railRangeMm[0])}>
            Crib ({railRangeMm[0]}mm)
          </button>
          <button type="button" className="btn small" style={{ flex: 1, fontSize: 10 }} onClick={() => setRailXMm(Math.round(railRangeMm[1] * 0.5))}>
            Mid ({Math.round(railRangeMm[1] * 0.5)}mm)
          </button>
          <button type="button" className="btn small" style={{ flex: 1, fontSize: 10 }} onClick={() => setRailXMm(railRangeMm[1])}>
            End ({railRangeMm[1]}mm)
          </button>
        </div>
      </div>

      {/* Inverted UR5e 6-DOF Joint Angles */}
      <div style={{ borderTop: "1px solid var(--line)", paddingTop: 8 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <span style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
            <Cpu size={11} style={{ verticalAlign: "-1px", marginRight: 4 }} />
            Inverted UR5e 6-DOF Joints
          </span>
        </div>
        <div className="mono" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 4, fontSize: 10.5 }}>
          {armSimRad.map((rad, i) => (
            <div key={i} style={{ padding: "3px 5px", borderRadius: 4, background: "var(--bg-2, rgba(148,163,184,0.08))" }}>
              J{i + 1}: {((rad * 180) / Math.PI).toFixed(1)}°
            </div>
          ))}
        </div>
      </div>

      {/* Zero-Scroll Compact Motorized X/Y Crib Matrix */}
      <div style={{ borderTop: "1px solid var(--line)", paddingTop: 8, flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
          <span style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
            X/Y Inventory Crib ({slots.length} parts)
          </span>
          <span className="mono muted" style={{ fontSize: 10 }}>
            Stage ({stageSimMm[0].toFixed(0)}, {stageSimMm[1].toFixed(0)}) mm
          </span>
        </div>

        {slots.length > 28 ? (
          /* High-density 11-column zero-scroll matrix for 121-optic sr_ion_apparatus */
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(11, 1fr)",
              gap: 3,
              alignContent: "start",
            }}
          >
            {slots.map((sl) => {
              const isSel = sl.slot_index === activeSlotIndex;
              const bg =
                sl.state === "placed"
                  ? "rgba(16, 185, 129, 0.28)"
                  : sl.state === "carried"
                    ? "#f59e0b"
                    : "rgba(56, 189, 248, 0.28)";
              const border = isSel
                ? "1.5px solid #fbbf24"
                : sl.state === "placed"
                  ? "1px solid rgba(16, 185, 129, 0.65)"
                  : "1px solid rgba(56, 189, 248, 0.55)";
              return (
                <button
                  key={sl.element_id}
                  type="button"
                  onClick={() => indexCribSlot(sl.slot_index)}
                  title={`#${sl.slot_index} ${sl.element_id} (${sl.type}) — ${sl.state ?? "placed"}`}
                  style={{
                    height: 15,
                    borderRadius: 2.5,
                    background: bg,
                    border,
                    padding: 0,
                    cursor: "pointer",
                  }}
                />
              );
            })}
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 4 }}>
            {slots.map((sl) => {
              const isSel = sl.slot_index === activeSlotIndex;
              const dotColor = sl.state === "placed" ? "#10b981" : sl.state === "carried" ? "#f59e0b" : "#38bdf8";
              return (
                <button
                  key={sl.element_id}
                  type="button"
                  className="btn small"
                  onClick={() => indexCribSlot(sl.slot_index)}
                  style={{ padding: "3px 5px", borderColor: isSel ? "#f59e0b" : undefined, justifyContent: "space-between" }}
                >
                  <b className="mono" style={{ fontSize: 10 }}>{sl.element_id}</b>
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: dotColor }} />
                </button>
              );
            })}
          </div>
        )}

        <div className="muted" style={{ display: "flex", gap: 10, fontSize: 10, marginTop: "auto", paddingTop: 4 }}>
          <span><span style={{ display: "inline-block", width: 7, height: 7, borderRadius: 2, background: "#38bdf8", marginRight: 4 }} />In Crib</span>
          <span><span style={{ display: "inline-block", width: 7, height: 7, borderRadius: 2, background: "#f59e0b", marginRight: 4 }} />Carried</span>
          <span><span style={{ display: "inline-block", width: 7, height: 7, borderRadius: 2, background: "#10b981", marginRight: 4 }} />Placed on Bench</span>
        </div>
      </div>
    </div>
  );
}

/** Right Mission-Control Column: Optical Verify Summary + 0x23/MicroManipulatorStepper Jogger + Live G-Code Stream (Zero outer scroll). */
export function RoboLabRightColumn() {
  const slots = useLab((s) => s.slots);
  const selectedMmsElementId = useLab((s) => s.selectedMmsElementId);
  const mmsPosUm = useLab((s) => s.mmsPosUm);
  const mmsRotorDeg = useLab((s) => s.mmsRotorDeg);
  const mmsEncoderCounts = useLab((s) => s.mmsEncoderCounts);
  const gcodeLog = useLab((s) => s.gcodeLog);
  const focusElementWithRobot = useLab((s) => s.focusElementWithRobot);
  const sendGcode = useLab((s) => s.sendGcode);
  const jogMmsUm = useLab((s) => s.jogMmsUm);

  const trace = useStore((s) => s.trace);
  const report = useStore((s) => s.report);

  const [stepUm, setStepUm] = useState<number>(5);
  const [customGcode, setCustomGcode] = useState<string>("G0 X0.125000 Y-0.050000 Z0.025000 F10.000");

  const passed = report?.passed ?? false;
  const score = report?.score ?? 0;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        padding: "10px 12px",
        gap: 10,
        overflow: "hidden",
        boxSizing: "border-box",
      }}
    >
      {/* 1. Live Optical Verification & Power Meter Card */}
      <div
        style={{
          padding: "8px 10px",
          borderRadius: 6,
          background: passed ? "rgba(16, 185, 129, 0.10)" : "rgba(239, 68, 68, 0.10)",
          border: `1px solid ${passed ? "rgba(16, 185, 129, 0.45)" : "rgba(239, 68, 68, 0.45)"}`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: 13, color: passed ? "#10b981" : "#f87171" }}>
            {passed ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
            <span>{passed ? "OPTICS VERIFIED · PASS" : "ASSEMBLING / ALIGNING"}</span>
          </div>
          <span className="mono" style={{ fontSize: 16, fontWeight: 700, color: passed ? "#10b981" : "#f87171" }}>
            {score.toFixed(0)}<small style={{ fontSize: 10, opacity: 0.75 }}>/100</small>
          </span>
        </div>
        <div className="mono" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6, fontSize: 11 }}>
          <div>
            <div className="muted" style={{ fontSize: 9.5 }}>Delivered</div>
            <b>{mW(report?.metrics.delivered_mw)}</b>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 9.5 }}>Beams</div>
            <b>{trace?.segments.length ?? 0} segs</b>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 9.5 }}>Stray Light</div>
            <b>{mW(report?.metrics.stray_mw)}</b>
          </div>
        </div>
      </div>

      {/* 2. 0x23/MicroManipulatorStepper (HW v4.0 Delta-3D) Sub-µm Alignment Controls */}
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
            <Crosshair size={11} style={{ verticalAlign: "-1px", marginRight: 4 }} />
            0x23/MicroManipulatorStepper
          </span>
          <select
            className="select"
            style={{ fontSize: 10.5, padding: "2px 6px", height: 23, maxWidth: 160 }}
            value={selectedMmsElementId}
            onChange={(e) => focusElementWithRobot(e.target.value)}
          >
            {slots.map((s) => (
              <option key={s.element_id} value={s.element_id}>
                {s.element_id} ({s.type})
              </option>
            ))}
          </select>
        </div>

        {/* Delta-3D XYZ & MT6835 30x Magnetic Encoder Readout */}
        <div className="mono" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 4, fontSize: 10.5 }}>
          {(["X", "Y", "Z"] as const).map((ax, i) => (
            <div key={ax} style={{ padding: "4px 6px", borderRadius: 4, background: "var(--bg-2, rgba(148,163,184,0.08))" }}>
              <div className="muted" style={{ fontSize: 9 }}>{ax} (50nm grid)</div>
              <b>{mmsPosUm[i].toFixed(2)} µm</b>
            </div>
          ))}
          {(["A", "B", "C"] as const).map((ax, i) => (
            <div key={ax} style={{ padding: "4px 6px", borderRadius: 4, background: "var(--bg-2, rgba(148,163,184,0.08))" }}>
              <div className="muted" style={{ fontSize: 9 }}>Rotor {ax} (MT6835)</div>
              <b>{mmsRotorDeg[i].toFixed(2)}°</b>
              <div className="muted" style={{ fontSize: 8.5 }}>{mmsEncoderCounts[i]} cts</div>
            </div>
          ))}
        </div>

        {/* Step Size & Jog Pad */}
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span className="muted" style={{ fontSize: 10.5 }}>Step:</span>
          {STEP_SIZES_UM.map((st) => (
            <button
              key={st}
              type="button"
              className={`btn small${stepUm === st ? " active" : ""}`}
              onClick={() => setStepUm(st)}
              style={{ fontSize: 10, padding: "2px 5px", flex: 1, justifyContent: "center" }}
            >
              {st < 0.1 ? "50nm" : `${st}µm`}
            </button>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 4 }}>
          {(["X", "Y", "Z"] as const).map((ax) => (
            <div key={ax} style={{ display: "flex", gap: 3 }}>
              <button type="button" className="btn small mono" style={{ flex: 1, justifyContent: "center" }} onClick={() => void jogMmsUm(ax, -stepUm)}>
                -{ax}
              </button>
              <button type="button" className="btn small mono" style={{ flex: 1, justifyContent: "center" }} onClick={() => void jogMmsUm(ax, stepUm)}>
                +{ax}
              </button>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", gap: 4 }}>
          <button type="button" className="btn small" style={{ flex: 1, justifyContent: "center" }} onClick={() => void sendGcode(["G28 A B C", "M50"])}>
            <RotateCcw size={11} /> Home (G28)
          </button>
          <button type="button" className="btn small" style={{ flex: 1, justifyContent: "center" }} onClick={() => void sendGcode(["M56 J0 P S", "M51"])}>
            Calibrate (M56)
          </button>
          <button type="button" className="btn small" style={{ flex: 1, justifyContent: "center" }} onClick={() => void sendGcode(["M57", "M58"])}>
            State (M57)
          </button>
        </div>

        <form
          style={{ display: "flex", gap: 4 }}
          onSubmit={(e) => {
            e.preventDefault();
            if (customGcode.trim()) void sendGcode([customGcode.trim(), "M50"]);
          }}
        >
          <input
            className="input mono"
            style={{ flex: 1, fontSize: 10.5, padding: "3px 6px" }}
            value={customGcode}
            onChange={(e) => setCustomGcode(e.target.value)}
            placeholder="G0 X0.1 Y-0.05 Z0.02 F10"
          />
          <button type="submit" className="btn small">Send</button>
        </form>
      </div>

      {/* 3. Live Serial G-Code Stream (fills remaining height cleanly) */}
      <div
        className="mono"
        style={{
          flex: 1,
          minHeight: 0,
          overflow: "hidden",
          padding: 8,
          borderRadius: 6,
          background: "#0d1117",
          color: "#e2e8f0",
          fontSize: 10,
          border: "1px solid var(--line)",
        }}
      >
        <div style={{ color: "#94a3b8", marginBottom: 4, fontWeight: 600 }}>
          <Terminal size={10} style={{ verticalAlign: "-1px", marginRight: 4 }} />
          OpenMicroStageInterface @ 921600 baud (G-Code Stream)
        </div>
        {gcodeLog.slice(-13).map((row) => (
          <div key={row.id} style={{ marginBottom: 2.5, lineHeight: 1.35 }}>
            <span style={{ color: "#38bdf8" }}>{row.unit_id}&gt;</span>{" "}
            <span style={{ color: "#fbbf24" }}>{row.command}</span>{" "}
            <span style={{ color: row.status.startsWith("error") ? "#f87171" : "#34d399" }}>
              {row.response}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Always-Visible Bottom Console Dock in Robotics Lab View: Argon Sub-Agents + Live Robotics Telemetry Feed. */
export function RoboLabBottomConsole() {
  const agents = useConsole((s) => s.agents);
  const eventLog = useLab((s) => s.eventLog);
  const agentList = Object.values(agents);

  return (
    <div
      style={{
        height: 175,
        flexShrink: 0,
        borderTop: "1px solid var(--line)",
        background: "var(--panel)",
        display: "grid",
        gridTemplateColumns: "300px 1fr",
        overflow: "hidden",
      }}
    >
      {/* Left: Active Argon Lab Agents */}
      <div style={{ borderRight: "1px solid var(--line)", padding: "8px 10px", display: "flex", flexDirection: "column", gap: 5, overflow: "hidden" }}>
        <div style={{ fontSize: 10.5, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--muted)" }}>
          <Activity size={11} style={{ verticalAlign: "-1px", marginRight: 4 }} />
          Argon Lab Controller Agents ({agentList.length})
        </div>
        {agentList.length === 0 ? (
          <div className="muted" style={{ fontSize: 11 }}>
            Press <b>Build &amp; Align Bench</b> to stream live Argon Lab Director &amp; robot controller agents.
          </div>
        ) : (
          agentList.map((a) => {
            const stateColor =
              a.state === "done" ? "#10b981" : a.state === "running" ? "#f59e0b" : a.state === "error" ? "#ef4444" : "#64748b";
            return (
              <div
                key={a.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "4px 7px",
                  borderRadius: 4,
                  background: "var(--bg-2, rgba(148,163,184,0.08))",
                  fontSize: 11,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 6, overflow: "hidden" }}>
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: stateColor, flexShrink: 0 }} />
                  <span style={{ fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {a.title}
                  </span>
                </div>
                <span className="mono muted" style={{ fontSize: 10, flexShrink: 0, marginLeft: 6 }}>
                  {a.elapsedMs != null ? `${(a.elapsedMs / 1000).toFixed(1)}s` : a.state}
                </span>
              </div>
            );
          })
        )}
      </div>

      {/* Right: Live Streaming Robotics & Argon Telemetry Feed */}
      <div
        className="mono"
        style={{
          padding: "8px 12px",
          overflow: "hidden",
          background: "#0b0f16",
          color: "#e2e8f0",
          fontSize: 10.5,
          display: "flex",
          flexDirection: "column",
          gap: 3,
        }}
      >
        <div style={{ color: "#94a3b8", fontWeight: 600, marginBottom: 2, fontSize: 10 }}>
          LIVE ARGON + MUJOCO + 0x23/MICROMANIPULATOR TELEMETRY STREAM
        </div>
        {eventLog.slice(-7).map((ev) => (
          <div key={ev.id} style={{ lineHeight: 1.35, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            <span style={{ color: ev.color, fontWeight: 600 }}>[{ev.tag}]</span>{" "}
            <span>{ev.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default RoboLabLeftColumn;
