/* @ds-bundle: {"format":3,"namespace":"DesignSystem_90c6f1","components":[{"name":"Badge","sourcePath":"components/Badge/Badge.jsx"},{"name":"Button","sourcePath":"components/Button/Button.jsx"},{"name":"CodeBlock","sourcePath":"components/CodeBlock/CodeBlock.jsx"},{"name":"DiagnosticCard","sourcePath":"components/DiagnosticCard/DiagnosticCard.jsx"},{"name":"SignalIndicator","sourcePath":"components/SignalIndicator/SignalIndicator.jsx"}],"sourceHashes":{"components/Badge/Badge.jsx":"a33f3f8cde51","components/Button/Button.jsx":"3b02396c5bd9","components/CodeBlock/CodeBlock.jsx":"db05908666ba","components/DiagnosticCard/DiagnosticCard.jsx":"ca59698fc6e2","components/SignalIndicator/SignalIndicator.jsx":"28ca4f12d678"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.DesignSystem_90c6f1 = window.DesignSystem_90c6f1 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/Badge/Badge.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Badge — compact status token. Monospace, uppercase, optional signal dot.
 */
function Badge({
  variant = "neutral",
  dot = false,
  solid = false,
  className = "",
  children,
  ...rest
}) {
  const cls = ["badge", `badge--${variant}`, solid ? "badge--solid" : "", className].filter(Boolean).join(" ");
  return /*#__PURE__*/React.createElement("span", _extends({
    className: cls
  }, rest), dot && /*#__PURE__*/React.createElement("span", {
    className: "badge__dot",
    "aria-hidden": "true"
  }), children);
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/Badge/Badge.jsx", error: String((e && e.message) || e) }); }

// components/Button/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * Button — primary action control for the DebugAI app.
 * Variants map to intent; amber primary is the signal action.
 */
function Button({
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
  const cls = ["btn", `btn--${variant}`, `btn--${size}`, mono ? "btn--mono" : "", className].filter(Boolean).join(" ");
  return /*#__PURE__*/React.createElement("button", _extends({
    type: type,
    className: cls
  }, rest), leadingIcon, children != null && /*#__PURE__*/React.createElement("span", null, children), trailingIcon);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/Button/Button.jsx", error: String((e && e.message) || e) }); }

// components/CodeBlock/CodeBlock.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function CopyIcon() {
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": "true"
  }, /*#__PURE__*/React.createElement("rect", {
    x: "9",
    y: "9",
    width: "11",
    height: "11",
    rx: "2"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M5 15V5a2 2 0 0 1 2-2h10"
  }));
}

/**
 * CodeBlock — terminal/editor-style readout with a chrome bar,
 * optional line numbers, highlighted lines, and a copy button.
 * Pass `code` (plain string) or `children` (pre-tinted <span class="tok-*">).
 */
function CodeBlock({
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
  return /*#__PURE__*/React.createElement("div", _extends({
    className: cls
  }, rest), showChrome && /*#__PURE__*/React.createElement("div", {
    className: "code-block__bar"
  }, /*#__PURE__*/React.createElement("span", {
    className: "code-block__dot",
    style: {
      background: "#F0563D"
    }
  }), /*#__PURE__*/React.createElement("span", {
    className: "code-block__dot",
    style: {
      background: "#EF9F27"
    }
  }), /*#__PURE__*/React.createElement("span", {
    className: "code-block__dot",
    style: {
      background: "#43C28A"
    }
  }), filename && /*#__PURE__*/React.createElement("span", {
    className: "code-block__name"
  }, filename), language && /*#__PURE__*/React.createElement("span", {
    className: "code-block__lang"
  }, language), copyable && /*#__PURE__*/React.createElement("button", {
    className: "code-block__copy",
    onClick: onCopy,
    "aria-label": copied ? "Copied" : "Copy code",
    title: copied ? "Copied" : "Copy",
    style: copied ? {
      color: "var(--ok-bright)",
      borderColor: "var(--ok-base)"
    } : undefined
  }, /*#__PURE__*/React.createElement(CopyIcon, null))), /*#__PURE__*/React.createElement("div", {
    className: "code-block__body"
  }, showLineNumbers && /*#__PURE__*/React.createElement("div", {
    className: "code-block__gutter"
  }, lines.map((_, i) => /*#__PURE__*/React.createElement("span", {
    className: "code-block__ln",
    key: i
  }, i + 1))), /*#__PURE__*/React.createElement("code", {
    className: "code-block__code"
  }, children ? children : lines.map((ln, i) => /*#__PURE__*/React.createElement("span", {
    className: "code-block__ln" + (hl.has(i + 1) ? " code-block__ln--hl" : ""),
    key: i
  }, ln || " ")))));
}
Object.assign(__ds_scope, { CodeBlock });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/CodeBlock/CodeBlock.jsx", error: String((e && e.message) || e) }); }

// components/SignalIndicator/SignalIndicator.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/**
 * SignalIndicator — one telemetry signal in a diagnosis.
 * Shows a node, label, confidence fill bar, and value readout.
 * `state` drives the fired/pending visual (animated pulse while pending).
 */
function SignalIndicator({
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
  return /*#__PURE__*/React.createElement("div", _extends({
    className: cls,
    "data-status": status,
    "data-state": state
  }, rest), /*#__PURE__*/React.createElement("span", {
    className: "signal__node",
    "aria-hidden": "true"
  }), /*#__PURE__*/React.createElement("div", {
    className: "signal__main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "signal__name"
  }, name), /*#__PURE__*/React.createElement("div", {
    className: "signal__bar"
  }, /*#__PURE__*/React.createElement("div", {
    className: "signal__fill",
    style: {
      width: state === "fired" ? `${pct}%` : "0%"
    }
  }))), /*#__PURE__*/React.createElement("div", {
    className: "signal__value"
  }, state === "fired" ? value : "·····"));
}
Object.assign(__ds_scope, { SignalIndicator });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/SignalIndicator/SignalIndicator.jsx", error: String((e && e.message) || e) }); }

// components/DiagnosticCard/DiagnosticCard.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function SevIcon({
  severity
}) {
  if (severity === "ok") {
    return /*#__PURE__*/React.createElement("svg", {
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: "2.2",
      strokeLinecap: "round",
      strokeLinejoin: "round",
      "aria-hidden": "true"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M20 6 9 17l-5-5"
    }));
  }
  // critical + warn share the alert glyph
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2.2",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": "true"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M12 3 2 20h20L12 3Z"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M12 10v4"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M12 17.5h.01"
  }));
}
function FixIcon() {
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": "true"
  }, /*#__PURE__*/React.createElement("path", {
    d: "m12 3 1.9 4.6L19 9.2l-3.6 3.3.9 5L12 15.1 7.7 17.5l.9-5L5 9.2l5.1-1.6L12 3Z"
  }));
}

/**
 * DiagnosticCard — the signature failure readout.
 * Severity rail, signal breakdown, confidence score, and a suggested fix.
 */
function DiagnosticCard({
  severity = "critical",
  id,
  title,
  location,
  confidence,
  signals = [],
  fix,
  fixLabel = "Suggested fix",
  actions,
  className = "",
  ...rest
}) {
  const cls = ["diag", className].filter(Boolean).join(" ");
  const confPct = confidence == null ? null : Math.round(confidence <= 1 ? confidence * 100 : confidence);
  return /*#__PURE__*/React.createElement("div", _extends({
    className: cls,
    "data-severity": severity
  }, rest), /*#__PURE__*/React.createElement("div", {
    className: "diag__head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "diag__sev"
  }, /*#__PURE__*/React.createElement(SevIcon, {
    severity: severity
  })), /*#__PURE__*/React.createElement("div", {
    className: "diag__titles"
  }, id && /*#__PURE__*/React.createElement("div", {
    className: "diag__id"
  }, id), /*#__PURE__*/React.createElement("div", {
    className: "diag__title"
  }, title), location && /*#__PURE__*/React.createElement("div", {
    className: "diag__loc",
    dangerouslySetInnerHTML: {
      __html: location
    }
  })), confPct != null && /*#__PURE__*/React.createElement("div", {
    className: "diag__conf"
  }, /*#__PURE__*/React.createElement("div", {
    className: "diag__conf-val"
  }, confPct, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "0.6em"
    }
  }, "%")), /*#__PURE__*/React.createElement("div", {
    className: "diag__conf-label ds-overline"
  }, "confidence"))), /*#__PURE__*/React.createElement("div", {
    className: "diag__body"
  }, signals.length > 0 && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "diag__section-label"
  }, "Signal breakdown"), /*#__PURE__*/React.createElement("div", {
    className: "diag__signals"
  }, signals.map((s, i) => /*#__PURE__*/React.createElement(__ds_scope.SignalIndicator, _extends({
    key: i
  }, s))))), fix && /*#__PURE__*/React.createElement("div", {
    className: "diag__fix"
  }, /*#__PURE__*/React.createElement("div", {
    className: "diag__fix-head"
  }, /*#__PURE__*/React.createElement(FixIcon, null), fixLabel), /*#__PURE__*/React.createElement("div", {
    className: "diag__fix-body"
  }, fix)), actions && /*#__PURE__*/React.createElement("div", {
    className: "diag__foot"
  }, actions)));
}
Object.assign(__ds_scope, { DiagnosticCard });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/DiagnosticCard/DiagnosticCard.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.CodeBlock = __ds_scope.CodeBlock;

__ds_ns.DiagnosticCard = __ds_scope.DiagnosticCard;

__ds_ns.SignalIndicator = __ds_scope.SignalIndicator;

})();
