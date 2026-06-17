"""SDK-first debug report artifact.

The raw diagnosis is intentionally complete, but product workflows need a
single object that says what failed, why, what to change, and whether the fix
was verified. This module keeps that artifact available from code, CLI, and UI.
"""

from __future__ import annotations

from typing import Any, Callable

from debugai.agents import propose_fix
from debugai.analyze import analyze
from debugai.fix_artifact import regression_artifact
from debugai.schema import CaptureRecord

Rerun = Callable[[str, str, list, "float | None"], str]

_CAPTURE_KEYS = (
    "prompt",
    "output",
    "system_prompt",
    "chunks",
    "similarity_scores",
    "retrieval_query",
    "temperature",
    "max_tokens",
    "context_window",
    "latency_ms",
    "token_usage",
    "tool_calls",
    "tools_expected",
    "response_schema",
    "model_name",
)


def capture_record_from_case(case: dict[str, Any]) -> CaptureRecord:
    """Convert an analyze-style dict into a CaptureRecord."""
    return CaptureRecord(
        user_prompt=case.get("prompt", ""),
        llm_output=case.get("output", ""),
        system_prompt=case.get("system_prompt", ""),
        retrieved_chunks=case.get("chunks") or [],
        similarity_scores=case.get("similarity_scores") or [],
        retrieval_query=case.get("retrieval_query"),
        temperature=case.get("temperature"),
        max_tokens=case.get("max_tokens"),
        context_window=case.get("context_window"),
        latency_ms=case.get("latency_ms"),
        token_usage=case.get("token_usage") or {},
        tool_calls=case.get("tool_calls") or [],
        tools_expected=case.get("tools_expected") or [],
        response_schema=case.get("response_schema"),
    )


def analyze_kwargs(case: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields accepted by analyze()."""
    return {k: case[k] for k in _CAPTURE_KEYS if k in case}


def summarize_evidence(primary: dict | None) -> list[str]:
    """Turn detector evidence into short, readable bullets."""
    if not primary:
        return []
    failure = primary.get("failure")
    ev = primary.get("evidence") or {}
    if failure == "schema_violation":
        return [str(v) for v in ev.get("violations", [])[:5]]
    if failure == "tool_call_failure":
        return [str(v) for v in ev.get("issues", [])[:5]]
    if failure == "citation_failure":
        return [str(v) for v in ev.get("issues", [])[:5]]
    if failure == "ambiguous_prompt":
        return [
            f"Prompt: {ev.get('prompt', '')}",
            "Contains an unresolved reference",
            "Model answered instead of asking a clarifying question",
        ]
    if failure == "retrieval_failure":
        return [
            f"Mean similarity {ev.get('similarity', 0):.2f}",
            f"Entity coverage {ev.get('entity_coverage', 0):.2f}",
            f"Context overlap {ev.get('overlap', 0):.2f}",
        ]
    if failure == "hallucination":
        return [
            f"Entity coverage {ev.get('entity_coverage', 0):.2f}",
            f"Contradiction {ev.get('contradiction', 0):.2f}",
            f"Variance {ev.get('variance', 0):.2f}",
            f"Overlap {ev.get('overlap', 0):.2f}",
        ]
    if failure == "context_overflow":
        return [
            f"Context ratio {ev.get('context_ratio', 0):.2f}",
            f"Token ratio {ev.get('token_ratio', 0):.2f}",
            f"Latency {ev.get('latency_ms', 0)}ms",
        ]
    if failure == "entity_gap":
        return [
            f"Entity coverage {ev.get('entity_coverage', 0):.2f}",
            f"Missing entities {ev.get('entities_missing', 0)}",
        ]
    if failure == "prompt_brittleness":
        return [
            f"Variance {ev.get('variance', 0):.2f}",
            f"Temperature {ev.get('temperature')}",
        ]
    if failure == "instruction_violation":
        violations = ev.get("violations") or []
        return [str(v.get("rule", v)) for v in violations[:5]]
    return [f"{k}: {v}" for k, v in list(ev.items())[:5]]


def debug_report(
    *,
    run_fix: bool = True,
    rerun: Rerun | None = None,
    explain_with_llm: bool = False,
    **case: Any,
) -> dict[str, Any]:
    """Diagnose one failing LLM call and return the product-level report.

    The returned dict is stable enough for SDK users to log, print, attach to
    CI output, or send to the hosted app.
    """
    diagnosis = analyze(
        explain_with_llm=explain_with_llm,
        **analyze_kwargs(case),
    )
    record = capture_record_from_case(case)
    primary = diagnosis.get("primary")
    fix_report = None
    if run_fix and primary:
        report = propose_fix(diagnosis, record, rerun=rerun)
        fix_report = report.to_dict() if report else None
    status = "healthy" if diagnosis.get("healthy") else "failing"
    return {
        "status": status,
        "failure": None if diagnosis.get("healthy") else primary.get("failure"),
        "confidence": None if diagnosis.get("healthy") else primary.get("confidence"),
        "severity": None if diagnosis.get("healthy") else primary.get("severity"),
        "root_cause": None if diagnosis.get("healthy") else primary.get("root_cause"),
        "evidence": summarize_evidence(primary),
        "fix": None if diagnosis.get("healthy") else primary.get("fix"),
        "diagnosis": diagnosis,
        "fix_report": fix_report,
        "regression_artifact": regression_artifact(diagnosis, record, fix_report),
    }


def format_debug_report(report: dict[str, Any]) -> str:
    """Render a debug report for terminal output or logs."""
    if report.get("status") == "healthy":
        return "Healthy: no failure detected."
    lines = [
        f"Failure: {report.get('failure')} ({report.get('severity')}, confidence {report.get('confidence')})",
        f"Root cause: {report.get('root_cause')}",
    ]
    evidence = report.get("evidence") or []
    if evidence:
        lines.append("Evidence:")
        lines.extend(f"- {item}" for item in evidence)
    if report.get("fix"):
        lines.append(f"Fix: {report['fix']}")
    fix_report = report.get("fix_report")
    if fix_report:
        lines.append(
            "Verification: "
            f"{fix_report.get('verdict')} via {fix_report.get('agent')} "
            f"({fix_report.get('tests_passed')}/{fix_report.get('tests_total')} tests)"
        )
    return "\n".join(lines)
