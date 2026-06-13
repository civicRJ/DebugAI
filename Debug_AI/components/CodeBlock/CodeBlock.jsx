import React from "react";

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </svg>
  );
}

/**
 * CodeBlock — terminal/editor-style readout with a chrome bar,
 * optional line numbers, highlighted lines, and a copy button.
 * Pass `code` (plain string) or `children` (pre-tinted <span class="tok-*">).
 */
export function CodeBlock({
  code = "",
  children,
  filename,
  language = "",
  showLineNumbers = true,
  highlight = [],
  showChrome = true,
  copyable = true,
  className = "",
  ...rest
}) {
  const [copied, setCopied] = React.useState(false);
  const lines = String(code).replace(/\n$/, "").split("\n");
  const hl = new Set(highlight);

  const onCopy = () => {
    const text = code || (typeof children === "string" ? children : "");
    if (navigator.clipboard && text) {
      navigator.clipboard.writeText(text).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1400);
      });
    }
  };

  const cls = ["code-block", className].filter(Boolean).join(" ");

  return (
    <div className={cls} {...rest}>
      {showChrome && (
        <div className="code-block__bar">
          <span className="code-block__dot" style={{ background: "#F0563D" }} />
          <span className="code-block__dot" style={{ background: "#EF9F27" }} />
          <span className="code-block__dot" style={{ background: "#43C28A" }} />
          {filename && <span className="code-block__name">{filename}</span>}
          {language && <span className="code-block__lang">{language}</span>}
          {copyable && (
            <button
              className="code-block__copy"
              onClick={onCopy}
              aria-label={copied ? "Copied" : "Copy code"}
              title={copied ? "Copied" : "Copy"}
              style={copied ? { color: "var(--ok-bright)", borderColor: "var(--ok-base)" } : undefined}
            >
              <CopyIcon />
            </button>
          )}
        </div>
      )}
      <div className="code-block__body">
        {showLineNumbers && (
          <div className="code-block__gutter">
            {lines.map((_, i) => (
              <span className="code-block__ln" key={i}>{i + 1}</span>
            ))}
          </div>
        )}
        <code className="code-block__code">
          {children
            ? children
            : lines.map((ln, i) => (
                <span
                  className={"code-block__ln" + (hl.has(i + 1) ? " code-block__ln--hl" : "")}
                  key={i}
                >
                  {ln || " "}
                </span>
              ))}
        </code>
      </div>
    </div>
  );
}

export default CodeBlock;
