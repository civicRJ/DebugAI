import * as React from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Visual intent. Amber primary = the signal action. Default "primary". */
  variant?: ButtonVariant;
  /** Control height. Default "md". */
  size?: ButtonSize;
  /** Render the label in monospace (for command-style actions). */
  mono?: boolean;
  /** Icon node rendered before the label. */
  leadingIcon?: React.ReactNode;
  /** Icon node rendered after the label. */
  trailingIcon?: React.ReactNode;
}

export declare function Button(props: ButtonProps): React.ReactElement;
export default Button;
