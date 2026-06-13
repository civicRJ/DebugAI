import * as React from "react";
import type { SignalIndicatorProps } from "../SignalIndicator/SignalIndicator";

export type DiagnosticSeverity = "critical" | "warn" | "ok";

export interface DiagnosticCardProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "id" | "title"> {
  /** Drives the rail color + severity glyph. Default "critical". */
  severity?: DiagnosticSeverity;
  /** Machine id, e.g. "DX-4471 · trace 0x9af2". */
  id?: React.ReactNode;
  /** Human-readable failure title. */
  title: React.ReactNode;
  /** Source location — HTML string (wrap the file/line in <b>). */
  location?: string;
  /** Confidence 0–1 (or 0–100). Renders the big percentage readout. */
  confidence?: number;
  /** Signals composing the diagnosis. */
  signals?: SignalIndicatorProps[];
  /** Suggested-fix content (string or JSX, may include <code>). */
  fix?: React.ReactNode;
  /** Label above the fix block. Default "Suggested fix". */
  fixLabel?: string;
  /** Footer action node(s), e.g. Buttons. */
  actions?: React.ReactNode;
}

export declare function DiagnosticCard(
  props: DiagnosticCardProps
): React.ReactElement;
export default DiagnosticCard;
