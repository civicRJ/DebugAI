import React from "react";

/**
 * Button — primary action control for the DebugAI app.
 * Variants map to intent; amber primary is the signal action.
 */
export function Button({
  variant = "primary",
  size = "md",
  mono = false,
  leadingIcon = null,
  trailingIcon = null,
  type = "button",
  className = "",
  children,
  ...rest
}) {
  const cls = [
    "btn",
    `btn--${variant}`,
    `btn--${size}`,
    mono ? "btn--mono" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button type={type} className={cls} {...rest}>
      {leadingIcon}
      {children != null && <span>{children}</span>}
      {trailingIcon}
    </button>
  );
}

export default Button;
