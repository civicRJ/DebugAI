import React from "react";
import { SignalIndicator } from "../SignalIndicator/SignalIndicator.jsx";

function SevIcon({ severity }) {
  if (severity === "ok") {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M20 6 9 17l-5-5" />
      </svg>
    );
  }
  // critical + warn share the alert glyph
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3 2 20h20L12 3Z" />
      <path d="M12 10v4" />
      <path d="M12 17.5h.01" />
    </svg>
  );
}

function FixIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m12 3 1.9 4.6L19 9.2l-3.6 3.3.9 5L12 15.1 7.7 17.5l.9-5L5 9.2l5.1-1.6L12 3Z" />
    </svg>
  );
}

/**
 * DiagnosticCard — the signature failure readout.
 * Severity rail, signal breakdown, confidence score, and a suggested fix.
 */
export function DiagnosticCard({
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
  const confPct =
    confidence == null
      ? null
      : Math.round((confidence <= 1 ? confidence * 100 : confidence));

  return (
    <div className={cls} data-severity={severity} {...rest}>
      <div className="diag__head">
        <div className="diag__sev"><SevIcon severity={severity} /></div>
        <div className="diag__titles">
          {id && <div className="diag__id">{id}</div>}
          <div className="diag__title">{title}</div>
          {location && (
            <div className="diag__loc" dangerouslySetInnerHTML={{ __html: location }} />
          )}
        </div>
        {confPct != null && (
          <div className="diag__conf">
            <div className="diag__conf-val">{confPct}<span style={{ fontSize: "0.6em" }}>%</span></div>
            <div className="diag__conf-label ds-overline">confidence</div>
          </div>
        )}
      </div>

      <div className="diag__body">
        {signals.length > 0 && (
          <>
            <div className="diag__section-label">Signal breakdown</div>
            <div className="diag__signals">
              {signals.map((s, i) => (
                <SignalIndicator key={i} {...s} />
              ))}
            </div>
          </>
        )}

        {fix && (
          <div className="diag__fix">
            <div className="diag__fix-head"><FixIcon />{fixLabel}</div>
            <div className="diag__fix-body">{fix}</div>
          </div>
        )}

        {actions && (
          <div className="diag__foot">{actions}</div>
        )}
      </div>
    </div>
  );
}

export default DiagnosticCard;
