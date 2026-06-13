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
from debugai.schema import CaptureRecord
from debugai.signals import compute_signals
from debugai.thresholds import DEFAULT_THRESHOLDS, Thresholds


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

    if explain_with_llm:
        explanation = explain(diag)
        result["explanation"] = explanation["explanation"]
        result["explainer_model"] = explanation["model"]
        # Prefer the LLM's specific fix when present; keep deterministic as base.
        if diag.primary is not None and explanation.get("fix"):
            result["primary"]["fix"] = explanation["fix"]
    else:
        result["explanation"] = (
            diag.primary.root_cause if diag.primary else "No failure detected."
        )
        result["explainer_model"] = "none"

    return result
