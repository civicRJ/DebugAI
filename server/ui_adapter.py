"""Map an engine diagnosis dict to design-system component props.

Produces the ``ui`` block the dashboard hands straight to <DiagnosticCard> /
<SignalIndicator> (window.DesignSystem_90c6f1). Keeping this on the backend
means the frontend stays a thin renderer and anomaly logic lives next to the
thresholds that define it.
"""

from __future__ import annotations

import html
import re

from debugai.thresholds import DEFAULT_THRESHOLDS as T

_TAG_RE = re.compile(r"<[^>]*>")


def _plain(text: str) -> str:
    """Strip any HTML/markup so model- or input-derived text is safe to render
    (the DiagnosticCard 'location' slot uses innerHTML)."""
    return html.escape(_TAG_RE.sub("", text or "")).strip()

# Human-readable titles for each failure id.
TITLES = {
    "context_overflow": "Context overflow",
    "retrieval_failure": "Retrieval failure",
    "entity_gap": "Entity gap",
    "hallucination": "Hallucination",
    "prompt_brittleness": "Prompt brittleness",
    "instruction_violation": "Instruction / pedagogy violation",
    "healthy": "Healthy",
}

# severity (engine) -> data-severity (design system)
_SEV = {"critical": "critical", "warning": "warn", "ok": "ok"}

# Per-signal display config: label, whether higher is worse, anomaly threshold,
# and how to normalise the value into the 0-1 confidence bar.
_SIGNAL_META = {
    "overlap":         ("context overlap",  False, T.overlap_low,                None),
    "entity_coverage": ("entity coverage",  False, T.entity_coverage_min,        None),
    "similarity":      ("retrieval sim",    False, T.similarity_min,             None),
    "contradiction":   ("contradiction",    True,  T.contradiction_min,          None),
    "variance":        ("output variance",  True,  T.variance_min,               None),
    "token_ratio":     ("token usage",      True,  T.token_usage_high,           None),
    "context_ratio":   ("context length",   True,  T.context_length_ratio_max,   None),
    "latency_ms":      ("latency",          True,  T.latency_high_ms,            5000.0),
}

_ORDER = list(_SIGNAL_META.keys())


def _signal_props(key: str, value: float) -> dict:
    label, higher_worse, threshold, scale = _SIGNAL_META[key]
    anomalous = value > threshold if higher_worse else value < threshold

    if key == "latency_ms":
        fill = min(value / scale, 1.0)
        shown = f"{int(value)}ms"
    else:
        fill = max(0.0, min(value, 1.0))
        shown = f"{value:.2f}"

    return {
        "name": label,
        "value": shown,
        "confidence": round(fill, 4),
        "status": "critical" if anomalous else "trace",
        "state": "fired",
    }


def to_card(diag: dict) -> dict:
    """Return DiagnosticCard-ready props for one diagnosis dict."""
    signals = diag.get("signals") or {}
    signal_props = [_signal_props(k, signals[k]) for k in _ORDER if k in signals]

    if diag.get("healthy") or not diag.get("primary"):
        return {
            "severity": "ok",
            "id": "healthy",
            "title": "Healthy — no failure detected",
            "confidence": None,
            "signals": signal_props,
            "fix": None,
            "explanation": _plain(diag.get("explanation", "")),
            "secondary": [],
        }

    p = diag["primary"]
    return {
        "severity": _SEV.get(p["severity"], "warn"),
        "id": p["failure"],
        "title": TITLES.get(p["failure"], p["failure"]),
        "confidence": p["confidence"],
        "signals": signal_props,
        "fix": p["fix"],
        "explanation": _plain(diag.get("explanation", p.get("root_cause", ""))),
        "secondary": [
            {"id": s["failure"], "title": TITLES.get(s["failure"], s["failure"]),
             "confidence": s["confidence"], "severity": _SEV.get(s["severity"], "warn")}
            for s in diag.get("secondary", [])
        ],
    }
