"""Layer 3 — LLM Explainer (Architecture §2.2, §8.2).

The ONLY diagnosis-path layer that calls an LLM. It translates the structured,
deterministic diagnosis into a human-readable explanation + fix, calibrating
language to confidence and variance type (§2.3 step 5).

Fail-open design: if no API key is configured (or the SDK is missing), we fall
back to a deterministic template built from the detector's own root_cause / fix
strings. The deterministic system always has the final say (§8.2).
"""

from __future__ import annotations

import json
import logging
import os

from debugai.diagnosis import Diagnosis

log = logging.getLogger("debugai.explainer")

# Small, fast, cheap model is right for an advisory explanation layer.
DEFAULT_MODEL = os.environ.get("DEBUGAI_EXPLAINER_MODEL", "claude-haiku-4-5-20251001")

_SYSTEM = (
    "You are DebugAI's explanation layer. A deterministic engine has already "
    "diagnosed why an LLM application's output failed. Your ONLY job is to turn "
    "the structured diagnosis into a crisp, developer-facing explanation and a "
    "concrete fix. Rules: (1) Never contradict the diagnosis — it is ground "
    "truth. (2) Calibrate certainty to the confidence score: state high-"
    "confidence findings plainly, hedge low-confidence ones. (3) Be specific — "
    "never say 'add more context'. (4) Keep it under 120 words. Respond as JSON: "
    '{"explanation": "...", "fix": "..."}.'
)


def _deterministic(diag: Diagnosis) -> dict:
    if diag.healthy or diag.primary is None:
        return {
            "explanation": "No failure detected — all signals are within healthy "
            "ranges.",
            "fix": "",
            "model": "deterministic",
        }
    p = diag.primary
    secondary = ", ".join(r.failure for r in diag.secondary)
    explanation = p.root_cause
    if secondary:
        explanation += f" Secondary issues also detected: {secondary}."
    return {"explanation": explanation, "fix": p.fix, "model": "deterministic"}


def _client(api_key: str | None = None):
    """Return an Anthropic client, or None if unavailable (fail open)."""
    key = os.environ.get("ANTHROPIC_API_KEY") if api_key is None else api_key
    if not key:
        return None
    try:
        import anthropic

        return anthropic.Anthropic(api_key=key, timeout=30.0, max_retries=2)
    except Exception as e:  # pragma: no cover - environment dependent
        log.warning("Anthropic client unavailable (%s); using deterministic explain", e)
        return None


def explain(diag: Diagnosis, model: str = DEFAULT_MODEL,
            api_key: str | None = None) -> dict:
    """Produce {explanation, fix, model} for a diagnosis."""
    if diag.healthy or diag.primary is None:
        return _deterministic(diag)

    client = _client(api_key=api_key)
    if client is None:
        return _deterministic(diag)

    payload = {
        "primary": {
            "failure": diag.primary.failure,
            "confidence": diag.primary.confidence,
            "severity": diag.primary.severity,
            "root_cause": diag.primary.root_cause,
            "deterministic_fix_hint": diag.primary.fix,
            "evidence": diag.primary.evidence,
        },
        "secondary": [
            {"failure": r.failure, "confidence": r.confidence} for r in diag.secondary
        ],
        "signals": diag.signals.to_dict() if diag.signals else {},
    }
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=400,
            system=_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        parsed = json.loads(text)
        return {
            "explanation": parsed.get("explanation", diag.primary.root_cause),
            "fix": parsed.get("fix", diag.primary.fix),
            "model": model,
        }
    except Exception as e:  # pragma: no cover - network dependent
        log.warning("LLM explain failed (%s); falling back to deterministic", e)
        return _deterministic(diag)
