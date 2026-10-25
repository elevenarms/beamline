import { useState } from "react";
import { Bot, Cpu, Play, RotateCcw, Square, Crosshair, Terminal } from "lucide-react";
import { useLab } from "../labStore";
import { useStore } from "../store";

const STEP_SIZES_UM = [0.05, 0.5, 5, 50, 250] as const;

export default function RoboLabPanel() {
  const enabled = useLab((s) => s.enabled);
  const setEnabled = useLab((s) => s.setEnabled);
  const running = useLab((s) => s.running);
  const phase = useLab((s) => s.phase);
  const statusMessage = useLab((s) => s.statusMessage);
  const wasmReady = useLab((s) => s.wasmReady);
  const wasmVersion = useLab((s) => s.wasmVersion);
  const simTimeS = useLab((s) => s.simTimeS);
  const dofCount = useLab((s) => s.dofCount);
  const slots = useLab((s) => s.slots);
  const activeSlotIndex = useLab((s) => s.activeSlotIndex);
  const stageSimMm = useLab((s) => s.stageSimMm);
  const armSimRad = useLab((s) => s.armSimRad);
  const selectedMmsElementId = useLab((s) => s.selectedMmsElementId);
  const mmsPosUm = useLab((s) => s.mmsPosUm);
  const mmsRotorDeg = useLab((s) => s.mmsRotorDeg);
  const mmsEncoderCounts = useLab((s) => s.mmsEncoderCounts);
  const gcodeLog = useLab((s) => s.gcodeLog);

  const startAutonomousRun = useLab((s) => s.startAutonomousRun);
  const stopRun = useLab((s) => s.stopRun);
  const indexCribSlot = useLab((s) => s.indexCribSlot);
  const sendGcode = useLab((s) => s.sendGcode);
  const jogMmsUm = useLab((s) => s.jogMmsUm);
  const design = useStore((s) => s.design);

  const [stepUm, setStepUm] = useState<number>(5);
  const [customGcode, setCustomGcode] = useState<string>("G0 X0.125000 Y-0.050000 Z0.025000 F10.000");
  const [useLlm, setUseLlm] = useState<boolean>(true);

  const placedCount = slots.filter((s) => s.state === "placed").length;

  return (
    <div className="panel robo-lab-panel" style={{ display: "flex", flexDirection: "column", gap: 12, padding: 12 }}>
      {/* Header & MuJoCo WASM Badge */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 600 }}>
          <Bot size={16} />
          <span>Autonomous Robotics Lab</span>
        </div>
        <span className={`pill${wasmReady ? "" : " warn"}`} style={{ fontSize: 11 }}>
          <span className="dot" /> MuJoCo {wasmVersion} WASM · {dofCount} DOF
        </span>
      </div>

      <p className="muted" style={{ fontSize: 12, margin: 0, lineHeight: 1.4 }}>
        Self-running workcell: motorized X/Y inventory crib presents parts to a 6-DOF robot arm for breadboard construction, followed by closed-loop sub-µm alignment via{" "}
        <a href="https://github.com/0x23/MicroManipulatorStepper" target="_blank" rel="noreferrer">
          0x23/MicroManipulatorStepper
        </a>{" "}
        (HW v4.0 Delta-3D).
      </p>

      {/* Primary Action Controls */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", gap: 6 }}>
          {!running ? (
            <button
              className="btn primary"
              style={{ flex: 1, justifyContent: "center" }}
              disabled={!design}
              onClick={() => void startAutonomousRun(useLlm)}
            >
              <Play size={14} /> Build &amp; Align Bench (Argon + MuJoCo)
            </button>
          ) : (
            <button
              className="btn"
              style={{ flex: 1, justifyContent: "center", borderColor: "var(--err)", color: "var(--err)" }}
              onClick={stopRun}
            >
              <Square size={14} /> Stop Lab Run
            </button>
          )}
          <button
            className={`btn${enabled ? " active" : ""}`}
            onClick={() => setEnabled(!enabled)}
            title="Toggle 3D MuJoCo workcell in viewport"
          >
            {enabled ? "Hide 3D Cell" : "Show 3D Cell"}
          </button>
        </div>

        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, color: "var(--muted)", cursor: "pointer" }}>
          <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
          <span>Query live Gemini <code>gemini-4-argon</code> Lab Director before assembly</span>
        </label>
      </div>

      {/* Live Status Banner */}
      <div
        style={{
          padding: "8px 10px",
          borderRadius: 6,
          background: "var(--bg-2, rgba(148,163,184,0.08))",
          border: "1px solid var(--line)",
          fontSize: 11.5,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontWeight: 600 }}>
          <span>Phase: {phase.toUpperCase()}</span>
          <span className="mono">
            {placedCount}/{slots.length} placed · t={simTimeS.toFixed(1)}s
          </span>
        </div>
        <div className="muted" style={{ fontSize: 11, lineHeight: 1.35 }}>
          {statusMessage}
        </div>
      </div>

      {/* Section 1: Motorized X/Y Presentation Stage & Inventory Crib */}
      <div style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
          <span style={{ fontSize: 11.5, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
            1 · Motorized X/Y Crib Stage ({slots.length} slots)
          </span>
          <span className="mono muted" style={{ fontSize: 11 }}>
            X:{stageSimMm[0].toFixed(1)} Y:{stageSimMm[1].toFixed(1)} mm
          </span>
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 5,
          }}
        >
          {slots.map((sl) => {
            const isSel = sl.slot_index === activeSlotIndex;
            const badgeColor =
              sl.state === "placed" ? "var(--ok, #10b981)" : sl.state === "carried" ? "#f59e0b" : "#38bdf8";
            return (
              <button
                key={sl.element_id}
                type="button"
                className="btn small"
                onClick={() => {
                  if (!enabled) setEnabled(true);
                  indexCribSlot(sl.slot_index);
                }}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "flex-start",
                  padding: "5px 6px",
                  borderColor: isSel ? "#f59e0b" : undefined,
                  textAlign: "left",
                }}
                title={`Click to index X/Y crib stage to present ${sl.element_id} (${sl.type}) at Pick Station`}
              >
                <div style={{ display: "flex", width: "100%", justifyContent: "space-between", alignItems: "center" }}>
                  <b className="mono" style={{ fontSize: 11 }}>{sl.element_id}</b>
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: badgeColor }} />
                </div>
                <span className="muted" style={{ fontSize: 9.5, overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }}>
                  {sl.type.replace(/_/g, " ")}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Section 2: 6-DOF Robot Arm Telemetry */}
      <div style={{ borderTop: "1px solid var(--line)", paddingTop: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <span style={{ fontSize: 11.5, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
            <Cpu size={12} style={{ verticalAlign: "-2px", marginRight: 4 }} />
            2 · 6-DOF Arm Joints (MuJoCo qpos)
          </span>
        </div>
        <div className="mono" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 4, fontSize: 11 }}>
          {armSimRad.map((rad, i) => (
            <div key={i} style={{ padding: "3px 6px", borderRadius: 4, background: "var(--bg-2, rgba(148,163,184,0.08))" }}>
              J{i + 1}: {((rad * 180) / Math.PI).toFixed(1)}°
            </div>
          ))}
        </div>
      </div>

      {/* Section 3: 0x23/MicroManipulatorStepper (HW v4.0 Delta-3D) */}
      <div style={{ borderTop: "1px solid var(--line)", paddingTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontSize: 11.5, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
            <Crosshair size={12} style={{ verticalAlign: "-2px", marginRight: 4 }} />
            3 · 0x23/MicroManipulatorStepper
          </span>
          <select
            className="select"
            style={{ fontSize: 11, padding: "2px 6px", height: 24 }}
            value={selectedMmsElementId}
            onChange={(e) => useLab.setState({ selectedMmsElementId: e.target.value })}
          >
            {slots.map((s) => (
              <option key={s.element_id} value={s.element_id}>
                MMS-{s.element_id} ({s.type})
              </option>
            ))}
          </select>
        </div>

        {/* Delta-3D Pose & MT6835 30x Magnetic Encoder Readout */}
        <div className="mono" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 4, fontSize: 10.5 }}>
          {(["X", "Y", "Z"] as const).map((ax, i) => (
            <div key={ax} style={{ padding: "4px 6px", borderRadius: 4, background: "var(--bg-2, rgba(148,163,184,0.08))" }}>
              <div className="muted" style={{ fontSize: 9.5 }}>{ax} (50nm grid)</div>
              <b>{mmsPosUm[i].toFixed(2)} µm</b>
            </div>
          ))}
          {(["A", "B", "C"] as const).map((ax, i) => (
            <div key={ax} style={{ padding: "4px 6px", borderRadius: 4, background: "var(--bg-2, rgba(148,163,184,0.08))" }}>
              <div className="muted" style={{ fontSize: 9.5 }}>Rotor {ax} (MT6835)</div>
              <b>{mmsRotorDeg[i].toFixed(2)}°</b>
              <div className="muted" style={{ fontSize: 9 }}>{mmsEncoderCounts[i]} cts</div>
            </div>
          ))}
        </div>

        {/* Step Size & Sub-Micrometer Jog Pad */}
        <div style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap" }}>
          <span className="muted" style={{ fontSize: 11 }}>Step:</span>
          {STEP_SIZES_UM.map((st) => (
            <button
              key={st}
              type="button"
              className={`btn small${stepUm === st ? " active" : ""}`}
              onClick={() => setStepUm(st)}
              style={{ fontSize: 10.5, padding: "2px 6px" }}
            >
              {st < 0.1 ? "50nm" : `${st}µm`}
            </button>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 4 }}>
          {(["X", "Y", "Z"] as const).map((ax) => (
            <div key={ax} style={{ display: "flex", gap: 3 }}>
              <button type="button" className="btn small mono" style={{ flex: 1 }} onClick={() => void jogMmsUm(ax, -stepUm)}>
                -{ax}
              </button>
              <button type="button" className="btn small mono" style={{ flex: 1 }} onClick={() => void jogMmsUm(ax, stepUm)}>
                +{ax}
              </button>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", gap: 4 }}>
          <button type="button" className="btn small" onClick={() => void sendGcode(["G28 A B C", "M50"])}>
            <RotateCcw size={12} /> Home (G28)
          </button>
          <button type="button" className="btn small" onClick={() => void sendGcode(["M56 J0 P S", "M51"])}>
            Calibrate (M56)
          </button>
          <button type="button" className="btn small" onClick={() => void sendGcode(["M57", "M58"])}>
            State (M57)
          </button>
        </div>

        {/* Custom G-Code Serial Input */}
        <form
          style={{ display: "flex", gap: 4 }}
          onSubmit={(e) => {
            e.preventDefault();
            if (customGcode.trim()) void sendGcode([customGcode.trim(), "M50"]);
          }}
        >
          <input
            className="input mono"
            style={{ flex: 1, fontSize: 11, padding: "4px 6px" }}
            value={customGcode}
            onChange={(e) => setCustomGcode(e.target.value)}
            placeholder="G0 X0.1 Y-0.05 Z0.02 F10"
          />
          <button type="submit" className="btn small">Send</button>
        </form>

        {/* Serial G-Code Log */}
        <div
          className="mono"
          style={{
            maxHeight: 135,
            overflowY: "auto",
            padding: 6,
            borderRadius: 4,
            background: "#0d1117",
            color: "#e2e8f0",
            fontSize: 10,
            border: "1px solid var(--line)",
          }}
        >
          <div style={{ color: "#64748b", marginBottom: 3 }}>
            <Terminal size={10} style={{ verticalAlign: "-1px", marginRight: 4 }} />
            OpenMicroStageInterface @ 921600 baud
          </div>
          {gcodeLog.slice(-12).map((row) => (
            <div key={row.id} style={{ marginBottom: 2 }}>
              <span style={{ color: "#38bdf8" }}>{row.unit_id}&gt;</span>{" "}
              <span style={{ color: "#fbbf24" }}>{row.command}</span>{" "}
              <span style={{ color: row.status.startsWith("error") ? "#f87171" : "#34d399" }}>
                {row.response}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
