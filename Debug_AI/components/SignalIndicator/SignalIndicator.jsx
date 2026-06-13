import React from "react";

/**
 * SignalIndicator — one telemetry signal in a diagnosis.
 * Shows a node, label, confidence fill bar, and value readout.
 * `state` drives the fired/pending visual (animated pulse while pending).
 */
export function SignalIndicator({
  name,
  value,
  confidence = 0,
  status = "trace",
  state = "fired",
  className = "",
  ...rest
}) {
  const pct = Math.max(0, Math.min(1, confidence)) * 100;
  const cls = ["signal", className].filter(Boolean).join(" ");

  return (
    <div
      className={cls}
      data-status={status}
      data-state={state}
      {...rest}
    >
      <span className="signal__node" aria-hidden="true" />
      <div className="signal__main">
        <div className="signal__name">{name}</div>
        <div className="signal__bar">
          <div
            className="signal__fill"
            style={{ width: state === "fired" ? `${pct}%` : "0%" }}
          />
        </div>
      </div>
      <div className="signal__value">
        {state === "fired" ? value : "·····"}
      </div>
    </div>
  );
}

export default SignalIndicator;
