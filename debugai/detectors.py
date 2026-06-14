"""Layer 2 — Failure Classification Rules (Architecture §5).

Deterministic detectors. Each takes the signal vector + thresholds and
returns a DetectorResult. All detectors run (§5.2); results are ranked by
confidence into primary + secondary. Gate patterns prevent nonsensical
multi-classification.

Detector bases are tuned to the doc's worked example: Scenario A (similarity
0.41, entity 0.17, overlap 0.12) → retrieval failure 0.95 = 0.70 base + 0.15
(entity) + 0.10 (overlap).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from debugai.schema import CaptureRecord
from debugai.signals import SignalVector
from debugai.thresholds import Thresholds
from debugai.validators import validate_json_schema

# Failure type identifiers (also used by the fix-agent registry later).
CONTEXT_OVERFLOW = "context_overflow"
RETRIEVAL_FAILURE = "retrieval_failure"
ENTITY_GAP = "entity_gap"
HALLUCINATION = "hallucination"
PROMPT_BRITTLENESS = "prompt_brittleness"
SCHEMA_VIOLATION = "schema_violation"
TOOL_CALL_FAILURE = "tool_call_failure"
CITATION_FAILURE = "citation_failure"
AMBIGUOUS_PROMPT = "ambiguous_prompt"

SEVERITY = {
    CONTEXT_OVERFLOW: "critical",
    RETRIEVAL_FAILURE: "critical",
    ENTITY_GAP: "warning",
    HALLUCINATION: "critical",
    PROMPT_BRITTLENESS: "warning",
    SCHEMA_VIOLATION: "critical",
    TOOL_CALL_FAILURE: "critical",
    CITATION_FAILURE: "warning",
    AMBIGUOUS_PROMPT: "warning",
}

_GATED_BASE = 0.70  # base confidence for a critical gated detector that fires
_CITATION_RE = re.compile(r"\[(\d+)\]|\b(?:source|chunk)\s*(\d+)\b", re.IGNORECASE)
_AMBIGUOUS_RE = re.compile(r"\b(it|this|that|these|those|they|them|do it|handle it)\b", re.IGNORECASE)


@dataclass
class DetectorResult:
    failure: str
    fired: bool
    confidence: float
    severity: str
    root_cause: str = ""
    fix: str = ""  # deterministic fix hint (Layer-3 fallback)
    evidence: dict = field(default_factory=dict)

    def clamp(self) -> "DetectorResult":
        self.confidence = round(max(0.0, min(self.confidence, 1.0)), 4)
        return self


# --------------------------------------------------------------------------- #
# 1. Context overflow — Critical | checked 1st
# --------------------------------------------------------------------------- #
def detect_context_overflow(s: SignalVector, rec: CaptureRecord, t: Thresholds) -> DetectorResult:
    fired = s.context_ratio > t.context_length_ratio_max
    conf = _GATED_BASE
    if s.token_ratio > t.token_usage_high:
        conf += 0.15
    if s.latency_ms > t.latency_high_ms:
        conf += 0.10
    if s.overlap < t.overlap_low:
        conf += 0.10
    return DetectorResult(
        failure=CONTEXT_OVERFLOW,
        fired=fired,
        confidence=conf,
        severity=SEVERITY[CONTEXT_OVERFLOW],
        root_cause=(
            f"Prompt fills {s.context_ratio:.0%} of the context window "
            f"(> {t.context_length_ratio_max:.0%}); content is likely truncated."
        ),
        fix="Reduce retrieved chunks to the top-N most relevant, summarise prior "
        "conversation history, or move to a larger-context model.",
        evidence={"context_ratio": s.context_ratio, "token_ratio": s.token_ratio,
                  "latency_ms": s.latency_ms},
    ).clamp()


# --------------------------------------------------------------------------- #
# 2. Schema violation — Critical | structured-output contract
# --------------------------------------------------------------------------- #
def detect_schema_violation(s: SignalVector, rec: CaptureRecord, t: Thresholds) -> DetectorResult:
    violations = validate_json_schema(rec.llm_output, rec.response_schema)
    fired = bool(violations)
    conf = 0.85 + min(0.03 * max(len(violations) - 1, 0), 0.10)
    return DetectorResult(
        failure=SCHEMA_VIOLATION,
        fired=fired,
        confidence=conf,
        severity=SEVERITY[SCHEMA_VIOLATION],
        root_cause=(
            f"The response violates the required structured-output schema: "
            f"{violations[0] if violations else 'no schema violations'}"
        ),
        fix="Enable strict JSON/schema mode when calling the model, add a repair retry "
        "that re-prompts with the validation errors, and validate before using the response.",
        evidence={"violations": violations, "schema": rec.response_schema or {}},
    ).clamp()


# --------------------------------------------------------------------------- #
# 3. Tool call failure — Critical | agent/tool execution contract
# --------------------------------------------------------------------------- #
def detect_tool_call_failure(s: SignalVector, rec: CaptureRecord, t: Thresholds) -> DetectorResult:
    expected = {x for x in (rec.tools_expected or []) if x}
    calls = rec.tool_calls or []
    issues: list[str] = []

    if expected and not calls:
        issues.append(f"Expected one of {sorted(expected)} but no tool call was made.")

    for i, call in enumerate(calls):
        name = str(call.get("name") or "").strip()
        raw_input = call.get("input")
        if not name:
            issues.append(f"Tool call {i} is missing a tool name.")
        elif expected and name not in expected:
            issues.append(f"Tool call {i} used unexpected tool '{name}'.")
        if isinstance(raw_input, str) and raw_input.strip():
            try:
                json.loads(raw_input)
            except json.JSONDecodeError as e:
                issues.append(f"Tool call {i} has malformed JSON arguments: {e.msg}.")
        if call.get("error") or str(call.get("status", "")).lower() in {"error", "failed"}:
            issues.append(f"Tool call {i} returned an error status.")

    fired = bool(issues)
    conf = 0.80 + min(0.05 * max(len(issues) - 1, 0), 0.15)
    return DetectorResult(
        failure=TOOL_CALL_FAILURE,
        fired=fired,
        confidence=conf,
        severity=SEVERITY[TOOL_CALL_FAILURE],
        root_cause=(
            f"The agent/tool contract failed: {issues[0] if issues else 'no tool issues'}"
        ),
        fix="Constrain tool selection, validate tool arguments before execution, retry "
        "malformed calls with the validation error, and require the model to use tool results.",
        evidence={"issues": issues, "expected_tools": sorted(expected), "tool_calls": calls},
    ).clamp()


# --------------------------------------------------------------------------- #
# 4. Retrieval failure — Critical | checked after contract failures
# --------------------------------------------------------------------------- #
def detect_retrieval_failure(s: SignalVector, rec: CaptureRecord, t: Thresholds) -> DetectorResult:
    fired = s.similarity < t.similarity_min
    conf = _GATED_BASE
    if s.entity_coverage < t.entity_coverage_min:
        conf += 0.15
    if s.overlap < t.overlap_very_low:
        conf += 0.10
    return DetectorResult(
        failure=RETRIEVAL_FAILURE,
        fired=fired,
        confidence=conf,
        severity=SEVERITY[RETRIEVAL_FAILURE],
        root_cause=(
            f"Mean retrieval similarity {s.similarity:.2f} is below "
            f"{t.similarity_min:.2f}; the retriever returned irrelevant chunks."
        ),
        fix="Re-chunk source documents with an entity-aware strategy, tune the "
        "retriever / embedding model, or expand the knowledge base.",
        evidence={"similarity": s.similarity, "entity_coverage": s.entity_coverage,
                  "overlap": s.overlap},
    ).clamp()


# --------------------------------------------------------------------------- #
# 5. Citation failure — Warning | source attribution contract
# --------------------------------------------------------------------------- #
def detect_citation_failure(s: SignalVector, rec: CaptureRecord, t: Thresholds) -> DetectorResult:
    output = rec.llm_output or ""
    chunks = rec.retrieved_chunks or []
    issues: list[str] = []

    refs = []
    for m in _CITATION_RE.finditer(output):
        value = m.group(1) or m.group(2)
        if value:
            refs.append(int(value))
    missing = [r for r in refs if r < 1 or r > len(chunks)]
    if missing:
        issues.append(f"Citation(s) {missing} do not map to retrieved chunks.")

    citation_required = "cite" in (rec.system_prompt or "").lower() or "citation" in (
        rec.system_prompt or ""
    ).lower()
    if citation_required and chunks and not refs:
        issues.append("The prompt requires citations but the response has none.")

    fired = bool(issues)
    conf = 0.72 if missing else 0.65
    return DetectorResult(
        failure=CITATION_FAILURE,
        fired=fired,
        confidence=conf,
        severity=SEVERITY[CITATION_FAILURE],
        root_cause=f"The response has unsupported citation behavior: {issues[0] if issues else 'citations valid'}",
        fix="Force citations to use retrieved chunk IDs, reject citations outside the retrieved set, "
        "and add a post-generation citation verifier before returning the answer.",
        evidence={"issues": issues, "citations": refs, "chunk_count": len(chunks)},
    ).clamp()


# --------------------------------------------------------------------------- #
# 6. Entity gap — Warning | checked after retrieval/citation
# --------------------------------------------------------------------------- #
def detect_entity_gap(s: SignalVector, rec: CaptureRecord, t: Thresholds) -> DetectorResult:
    fired = (
        s.similarity >= t.similarity_min
        and s.entity_coverage < t.entity_coverage_min
        and s.contradiction < t.contradiction_min
        and s.variance <= t.variance_min
    )
    conf = 0.60 + min(0.08 * s.entities_missing, 0.30)
    return DetectorResult(
        failure=ENTITY_GAP,
        fired=fired,
        confidence=conf,
        severity=SEVERITY[ENTITY_GAP],
        root_cause=(
            f"Retrieval is healthy but {s.entities_missing} entity(ies) in the "
            "answer are absent from the retrieved context — a knowledge-base hole."
        ),
        fix="Check whether the missing entities exist elsewhere in the corpus with "
        "different chunking; if not, flag the knowledge-base gap for human review.",
        evidence={"entity_coverage": s.entity_coverage,
                  "entities_missing": s.entities_missing},
    ).clamp()


# --------------------------------------------------------------------------- #
# 7. Hallucination — Critical | checked after grounding evidence
# --------------------------------------------------------------------------- #
def detect_hallucination(s: SignalVector, rec: CaptureRecord, t: Thresholds) -> DetectorResult:
    score = 0.0
    if s.similarity >= t.similarity_min:  # gate
        if s.entity_coverage < t.entity_coverage_hallucination:
            score += 0.35
        if s.contradiction > t.contradiction_min:
            score += 0.30
        if s.variance > t.variance_min:
            score += 0.20
        if t.overlap_very_low <= s.overlap <= 0.70:
            score += 0.10
        # High overlap (≥ 0.70) means the output largely repeats the context —
        # strong grounding evidence that weighs against hallucination.
        if s.overlap >= 0.70:
            score -= 0.15
    fired = s.similarity >= t.similarity_min and score >= t.hallucination_fire
    return DetectorResult(
        failure=HALLUCINATION,
        fired=fired,
        confidence=score,
        severity=SEVERITY[HALLUCINATION],
        root_cause=(
            "Retrieval succeeded but the output is not grounded in it "
            f"(fabrication score {score:.2f}): low entity coverage / contradiction "
            "/ instability indicate invented content."
        ),
        fix="Add grounding constraints to the system prompt (answer only from "
        "provided context; cite sources; say 'not found' when unsupported).",
        evidence={"entity_coverage": s.entity_coverage, "contradiction": s.contradiction,
                  "variance": s.variance, "overlap": s.overlap},
    ).clamp()


# --------------------------------------------------------------------------- #
# 8. Prompt brittleness — Warning | residual instability
# --------------------------------------------------------------------------- #
def detect_prompt_brittleness(s: SignalVector, rec: CaptureRecord, t: Thresholds) -> DetectorResult:
    gate = (
        s.similarity >= t.similarity_min
        and s.entity_coverage >= t.entity_coverage_min
        and s.contradiction < t.contradiction_min
    )
    fired = gate and s.variance > t.variance_min
    conf = 0.60
    if rec.temperature is not None and rec.temperature > t.temperature_high:
        conf += 0.15
    return DetectorResult(
        failure=PROMPT_BRITTLENESS,
        fired=fired,
        confidence=conf,
        severity=SEVERITY[PROMPT_BRITTLENESS],
        root_cause=(
            f"All grounding signals are healthy but output variance {s.variance:.2f} "
            "is high — the same prompt yields inconsistent answers."
        ),
        fix="Lower the sampling temperature, add an explicit output-format template, "
        "and insert few-shot examples to pin down the expected response shape.",
        evidence={"variance": s.variance, "temperature": rec.temperature},
    ).clamp()


# --------------------------------------------------------------------------- #
# 9. Ambiguous prompt — Warning | user request underspecified
# --------------------------------------------------------------------------- #
def detect_ambiguous_prompt(s: SignalVector, rec: CaptureRecord, t: Thresholds) -> DetectorResult:
    prompt = rec.user_prompt or ""
    output = rec.llm_output or ""
    short_pronoun_prompt = len(prompt.split()) <= 8 and bool(_AMBIGUOUS_RE.search(prompt))
    answered_instead_of_clarifying = len(output.split()) >= 30 and "?" not in output
    fired = short_pronoun_prompt and answered_instead_of_clarifying and not rec.retrieved_chunks
    return DetectorResult(
        failure=AMBIGUOUS_PROMPT,
        fired=fired,
        confidence=0.62,
        severity=SEVERITY[AMBIGUOUS_PROMPT],
        root_cause="The user request is underspecified, but the model answered instead of asking a clarifying question.",
        fix="Add an ambiguity gate: when the prompt depends on unresolved pronouns or missing constraints, "
        "ask one clarifying question before producing a final answer.",
        evidence={
            "prompt": prompt,
            "short_prompt": len(prompt.split()) <= 8,
            "has_ambiguous_reference": bool(_AMBIGUOUS_RE.search(prompt)),
        },
    ).clamp()


# Priority order matters (§5.2): earlier detectors gate later ones.
DETECTORS = [
    detect_context_overflow,
    detect_schema_violation,
    detect_tool_call_failure,
    detect_retrieval_failure,
    detect_citation_failure,
    detect_entity_gap,
    detect_hallucination,
    detect_prompt_brittleness,
    detect_ambiguous_prompt,
]
