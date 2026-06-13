import * as React from "react";

export interface CodeBlockProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "children"> {
  /** Raw code as a string. Rendered line-by-line with optional gutter. */
  code?: string;
  /** Pre-tinted markup (e.g. <span className="tok-key">). Overrides `code` rendering. */
  children?: React.ReactNode;
  /** File path / name shown in the chrome bar. */
  filename?: string;
  /** Language label shown at the right of the bar, e.g. "ts", "py". */
  language?: string;
  /** Show the left line-number gutter. Default true. */
  showLineNumbers?: boolean;
  /** 1-based line numbers to highlight with an amber rail. */
  highlight?: number[];
  /** Show the top chrome bar (dots + filename + copy). Default true. */
  showChrome?: boolean;
  /** Show the copy button. Default true. */
  copyable?: boolean;
}

export declare function CodeBlock(props: CodeBlockProps): React.ReactElement;
export default CodeBlock;
