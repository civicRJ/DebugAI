import * as React from "react";

export type SignalStatus = "ok" | "warn" | "critical" | "trace";
export type SignalState = "pending" | "fired";

export interface SignalIndicatorProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "children"> {
  /** Signal name, e.g. "latency.p99" or "heap.allocations". */
  name: string;
  /** Readout value shown on the right, e.g. "1.8s" or "OOM". */
  value?: React.ReactNode;
  /** Confidence / magnitude 0–1, drives the fill bar width. */
  confidence?: number;
  /** Status intent — drives color when fired. Default "trace". */
  status?: SignalStatus;
  /** "pending" shows the animated pulse; "fired" reveals value + fill. */
  state?: SignalState;
}

export declare function SignalIndicator(
  props: SignalIndicatorProps
): React.ReactElement;
export default SignalIndicator;
