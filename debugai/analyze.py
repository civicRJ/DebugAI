"""Level 1 API — the single-call entry point (Architecture §3.2).

    from debugai import analyze
    result = analyze(
        prompt="What is the refund policy?",
        output="Refunds are issued within 90 days...",
        chunks=[...],
        similarity_scores=[...],
    )
    print(result["primary"]["failure"], result["primary"]["confidence"])

Returns the structured JSON contract from §7.3:
    { "healthy": bool,
      "primary":   {failure, confidence, severity, root_cause, fix, evidence},
      "secondary": [ ... ],
      "signals":   { ...8 metrics... },
      "explanation": "human-readable text" }
"""

from __future__ import annotations

from typing import Any

from debugai.diagnosis import diagnose
from debugai.explainer import explain
from debugai.judge import INSTRUCTION_VIOLATION, judge_instructions
from debugai.schema import CaptureRecord
from debugai.signals import compute_signals
from debugai.thresholds import DEFAULT_THRESHOLDS, Thresholds

_IV_FIX = (
    "Strengthen the system prompt to enforce the violated rules: reveal at most "
    "one small hint per turn (never the full solution early), ask exactly one NEW "
    "leading question that advances beyond what was already said (never restate a "
    "prior question), and don't open by paraphrasing the student."
)


def _merge_instruction(result: dict, jd) -> dict:
    """Fold an instruction-adherence verdict into the diagnosis, re-ranking by
    confidence so the most severe failure becomes primary."""
    severity = "critical" if any(v.severity == "critical" for v in jd.violations) else "warning"
    rules = "; ".join(v.rule for v in jd.violations[:3])
    iv = {
        "failure": INSTRUCTION_VIOLATION,
        "confidence": jd.confidence,
        "severity": severity,
        "root_cause": f"The response violates {len(jd.violations)} system-prompt "
                      f"rule(s): {rules}",
        "fix": _IV_FIX,
        "evidence": {"violations": [v.to_dict() for v in jd.violations],
                     "judge_model": jd.model},
    }
    fired = ([result["primary"]] if result.get("primary") else []) + result.get("secondary", []) + [iv]
    fired.sort(key=lambda r: r["confidence"], reverse=True)
    result["healthy"] = False
    result["primary"] = fired[0]
    result["secondary"] = fired[1:]
    return result


def analyze(
    prompt: str,
    output: str,
    *,
    system_prompt: str = "",
    chunks: list[str] | None = None,
    similarity_scores: list[float] | None = None,
    retrieval_query: str | None = None,
    expected_output: str | None = None,
    model_name: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    context_window: int | None = None,
    latency_ms: int | None = None,
    token_usage: dict[str, int] | None = None,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    explain_with_llm: bool = True,
    lazy: bool = False,
    judge: bool = False,
    judge_model: str | None = None,
) -> dict[str, Any]:
    """Diagnose why an LLM output failed and return a structured fix.

    Only ``prompt`` and ``output`` are required (Core IO). Supplying retrieval
    and runtime fields unlocks the RAG and capacity signals.
    """
    rec = CaptureRecord(
        user_prompt=prompt,
        llm_output=output,
        system_prompt=system_prompt,
        expected_output=expected_output,
        retrieved_chunks=chunks or [],
        similarity_scores=similarity_scores or [],
        retrieval_query=retrieval_query,
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        context_window=context_window,
        latency_ms=latency_ms,
        token_usage=token_usage or {},
    )

    signals = compute_signals(rec, lazy=lazy)
    diag = diagnose(signals, rec, thresholds)
    result = diag.to_dict()

    # Optional behavioural / instruction-following check (LLM-as-judge) — catches
    # failures the grounding signals can't see (e.g. a tutor revealing the answer).
    if judge and rec.system_prompt:
        jd = judge_instructions(rec.system_prompt, rec.user_prompt, rec.llm_output,
                                model=judge_model)
        if not jd.healthy:
            result = _merge_instruction(result, jd)

    if explain_with_llm:
        explanation = explain(diag)
        result["explainer_model"] = explanation["model"]
        # Prefer the deterministic primary's own root_cause when the judge changed
        # the primary; otherwise use the LLM explanation.
        if (result.get("primary") or {}).get("failure") == INSTRUCTION_VIOLATION:
            result["explanation"] = result["primary"]["root_cause"]
        else:
            result["explanation"] = explanation["explanation"]
            if diag.primary is not None and explanation.get("fix"):
                result["primary"]["fix"] = explanation["fix"]
    else:
        result["explanation"] = (
            result["primary"]["root_cause"] if result.get("primary") else "No failure detected."
        )
        result["explainer_model"] = "none"

    return result
