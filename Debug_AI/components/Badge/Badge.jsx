import React from "react";

/**
 * Badge — compact status token. Monospace, uppercase, optional signal dot.
 */
export function Badge({
  variant = "neutral",
  dot = false,
  solid = false,
  className = "",
  children,
  ...rest
}) {
  const cls = [
    "badge",
    `badge--${variant}`,
    solid ? "badge--solid" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <span className={cls} {...rest}>
      {dot && <span className="badge__dot" aria-hidden="true" />}
      {children}
    </span>
  );
}

export default Badge;
