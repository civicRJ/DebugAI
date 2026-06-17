"""Pipeline trace diagnosis.

Final-output diagnosis is useful, but production LLM apps fail in stages:
query rewrite, retrieval, context packing, tool execution, generation, and
validation. This module gives the SDK/server a lightweight stage analyzer that
pinpoints where the pipeline first went wrong.
"""

from __future__ import annotations

import json
from typing import Any

from debugai.analyze import analyze
from debugai.schema import CaptureRecord
from debugai.signals import compute_signals


def _stage_id(stage: dict[str, Any], i: int) -> str:
    return str(stage.get("id") or stage.get("name") or stage.get("kind") or f"stage_{i + 1}")


def _issue(stage_id: str, kind: str, failure: str, severity: str, confidence: float,
           root_cause: str, fix: str, evidence: dict | None = None) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "kind": kind,
        "failure": failure,
        "severity": severity,
        "confidence": round(max(0.0, min(confidence, 1.0)), 4),
        "root_cause": root_cause,
        "fix": fix,
        "evidence": evidence or {},
    }


def _tool_issues(stage: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    calls = stage.get("tool_calls") or stage.get("calls") or []
    expected = set(stage.get("tools_expected") or [])
    if expected and not calls:
        issues.append(f"Expected one of {sorted(expected)} but no tool call was made.")
    for i, call in enumerate(calls):
        raw = call.get("input")
        if isinstance(raw, str) and raw.strip():
            try:
                json.loads(raw)
            except json.JSONDecodeError:
                issues.append(f"Tool call {i} has malformed JSON arguments.")
        if call.get("error") or str(call.get("status", "")).lower() in {"error", "failed"}:
            issues.append(f"Tool call {i} returned an error status.")
    return issues


def analyze_pipeline(
    stages: list[dict[str, Any]],
    *,
    system_prompt: str = "",
    user_prompt: str = "",
    output_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Analyze a list of pipeline stages.

    Stage kinds currently recognized:
    `query_rewrite`, `retrieval`, `context_packing`, `tool`, `generation`,
    `validation`. Unknown stages are passed through as healthy metadata.
    """
    analyzed: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for i, stage in enumerate(stages):
        sid = _stage_id(stage, i)
        kind = str(stage.get("kind") or stage.get("type") or sid).lower()
        stage_issues: list[dict[str, Any]] = []

        if kind in {"query_rewrite", "rewrite"}:
            rec = CaptureRecord(
                user_prompt=user_prompt or stage.get("input") or "",
                llm_output=stage.get("output") or "",
                retrieval_query=stage.get("output") or "",
                retrieved_chunks=stage.get("chunks") or ["placeholder"],
            )
            signals = compute_signals(rec, lazy=True)
            if signals.query_drift > 0.72:
                stage_issues.append(_issue(
                    sid, kind, "query_drift", "warning", 0.70,
                    f"Retrieval query drifted {signals.query_drift:.0%} away from the user request.",
                    "Constrain query rewriting to preserve user entities and include the original query.",
                    {"query_drift": signals.query_drift, "rewrite": stage.get("output")},
                ))

        elif kind == "retrieval":
            rec = CaptureRecord(
                user_prompt=user_prompt or stage.get("input") or "",
                llm_output=stage.get("output") or "retrieval stage",
                retrieved_chunks=stage.get("chunks") or stage.get("output") or [],
                similarity_scores=stage.get("similarity_scores") or [],
                retrieval_query=stage.get("retrieval_query") or stage.get("input"),
                chunk_sources=stage.get("chunk_sources") or [],
            )
            signals = compute_signals(rec, lazy=True)
            if signals.similarity < 0.50:
                stage_issues.append(_issue(
                    sid, kind, "retrieval_failure", "critical", 0.85,
                    f"Mean retrieval similarity {signals.similarity:.2f} is below 0.50.",
                    "Tune retriever/reranker, preserve entities in rewrite, or re-chunk the source corpus.",
                    {"similarity": signals.similarity, "retrieval_coverage": signals.retrieval_coverage},
                ))
            if signals.context_dilution > 0.60:
                stage_issues.append(_issue(
                    sid, kind, "context_dilution", "warning", 0.64,
                    f"{signals.context_dilution:.0%} of retrieved chunks appear weakly related to the query.",
                    "Filter low-overlap chunks and rerank before context packing.",
                    {"context_dilution": signals.context_dilution},
                ))
            if signals.source_conflict > 0.50:
                stage_issues.append(_issue(
                    sid, kind, "source_conflict", "warning", 0.68,
                    "Retrieved sources appear to disagree on key facts.",
                    "Resolve source conflicts before generation or ask a clarifying question.",
                    {"source_conflict": signals.source_conflict},
                ))

        elif kind in {"tool", "tool_execution"}:
            tool_issues = _tool_issues(stage)
            if tool_issues:
                stage_issues.append(_issue(
                    sid, kind, "tool_call_failure", "critical", 0.82,
                    tool_issues[0],
                    "Validate tool selection and JSON arguments before execution; retry with validation errors.",
                    {"issues": tool_issues},
                ))

        elif kind in {"generation", "answer"}:
            diag = analyze(
                prompt=user_prompt or stage.get("input") or "",
                output=stage.get("output") or "",
                system_prompt=system_prompt,
                chunks=stage.get("chunks") or [],
                similarity_scores=stage.get("similarity_scores") or [],
                retrieval_query=stage.get("retrieval_query"),
                temperature=stage.get("temperature"),
                response_schema=output_schema,
                explain_with_llm=False,
                lazy=True,
            )
            if not diag.get("healthy") and diag.get("primary"):
                p = diag["primary"]
                stage_issues.append(_issue(
                    sid, kind, p["failure"], p["severity"], p["confidence"],
                    p["root_cause"], p["fix"], p.get("evidence") or {},
                ))

        elif kind in {"validation", "output_validation"}:
            schema = stage.get("schema") or output_schema
            if schema:
                diag = analyze(
                    prompt=user_prompt or "validate output",
                    output=stage.get("output") or "",
                    system_prompt=system_prompt,
                    response_schema=schema,
                    explain_with_llm=False,
                )
                if not diag.get("healthy") and diag.get("primary"):
                    p = diag["primary"]
                    stage_issues.append(_issue(
                        sid, kind, p["failure"], p["severity"], p["confidence"],
                        p["root_cause"], p["fix"], p.get("evidence") or {},
                    ))

        analyzed.append({
            "id": sid,
            "kind": kind,
            "healthy": not stage_issues,
            "issues": stage_issues,
        })
        issues.extend(stage_issues)

    issues.sort(key=lambda x: x["confidence"], reverse=True)
    return {
        "healthy": not issues,
        "primary": issues[0] if issues else None,
        "stages": analyzed,
        "issues": issues,
    }
