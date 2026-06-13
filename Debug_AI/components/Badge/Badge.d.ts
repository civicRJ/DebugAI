import * as React from "react";

export type BadgeVariant = "ok" | "warn" | "critical" | "trace" | "neutral";

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement> {
  /** Status intent — drives color. Default "neutral". */
  variant?: BadgeVariant;
  /** Show a glowing leading signal dot. */
  dot?: boolean;
  /** Filled treatment instead of tinted. */
  solid?: boolean;
}

export declare function Badge(props: BadgeProps): React.ReactElement;
export default Badge;
