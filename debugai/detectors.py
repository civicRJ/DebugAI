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
QUERY_DRIFT = "query_drift"
RETRIEVAL_AMBIGUITY = "retrieval_ambiguity"
TOOL_RESULT_IGNORED = "tool_result_ignored"
PROMPT_INJECTION = "prompt_injection"
SENSITIVE_DATA_LEAK = "sensitive_data_leak"

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
    QUERY_DRIFT: "warning",
    RETRIEVAL_AMBIGUITY: "warning",
    TOOL_RESULT_IGNORED: "critical",
    PROMPT_INJECTION: "critical",
    SENSITIVE_DATA_LEAK: "critical",
}

LAYER = {
    CONTEXT_OVERFLOW: "runtime",
    RETRIEVAL_FAILURE: "retrieval",
    ENTITY_GAP: "knowledge_base",
    HALLUCINATION: "grounding",
    PROMPT_BRITTLENESS: "prompt",
    SCHEMA_VIOLATION: "schema",
    TOOL_CALL_FAILURE: "tool_execution",
    CITATION_FAILURE: "citation",
    AMBIGUOUS_PROMPT: "prompt",
    QUERY_DRIFT: "retrieval",
    RETRIEVAL_AMBIGUITY: "retrieval",
    TOOL_RESULT_IGNORED: "tool_execution",
    PROMPT_INJECTION: "safety",
    SENSITIVE_DATA_LEAK: "safety",
}

_GATED_BASE = 0.70  # base confidence for a critical gated detector that fires
_CITATION_RE = re.compile(r"\[(\d+)\]|\b(?:source|chunk)\s*(\d+)\b", re.IGNORECASE)
_AMBIGUOUS_RE = re.compile(r"\b(it|this|that|these|those|they|them|do it|handle it)\b", re.IGNORECASE)
_INJECTION_RE = re.compile(
    r"\b(ignore|disregard|override)\s+(?:all\s+)?(?:previous|prior|above|system|developer)"
    r"|\breveal\s+(?:the\s+)?(?:system|developer)\s+prompt\b"
    r"|\byou\s+are\s+now\s+(?:system|developer)\b"
    r"|\bjailbreak\b|\bdo\s+not\s+follow\s+(?:the\s+)?instructions\b",
    re.IGNORECASE,
)
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("assignment_secret", re.compile(
        r"\b(?:api[_ -]?key|secret|password|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}",
        re.IGNORECASE,
    )),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
)
_WORD_RE = re.compile(r"[A-Za-z0-9']+")


@dataclass
class DetectorResult:
    failure: str
    fired: bool
    confidence: float
    severity: str
    layer: str = ""
    root_cause: str = ""
    fix: str = ""  # deterministic fix hint (Layer-3 fallback)
    evidence: dict = field(default_factory=dict)

    def clamp(self) -> "DetectorResult":
        self.confidence = round(max(0.0, min(self.confidence, 1.0)), 4)
        if not self.layer:
            self.layer = LAYER.get(self.failure, "application")
        return self


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD_RE.findall(text or "")}


def _text_overlap(a: str, b: str) -> float:
    at, bt = _tokens(a), _tokens(b)
    union = at | bt
    return (len(at & bt) / len(union)) if union else 0.0


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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
# 2. Sensitive data leak — Critical | output safety contract
# --------------------------------------------------------------------------- #
def detect_sensitive_data_leak(s: SignalVector, rec: CaptureRecord, t: Thresholds) -> DetectorResult:
    leaked: list[dict[str, str]] = []
    for label, pattern in _SECRET_PATTERNS:
        for match in pattern.finditer(rec.llm_output or ""):
            value = match.group(0)
            if value:
                leaked.append({"type": label, "sample": value[:8] + "..."})

    fired = bool(leaked)
    conf = 0.92 + min(0.02 * max(len(leaked) - 1, 0), 0.06)
    return DetectorResult(
        failure=SENSITIVE_DATA_LEAK,
        fired=fired,
        confidence=conf,
        severity=SEVERITY[SENSITIVE_DATA_LEAK],
        root_cause=(
            f"The response appears to expose sensitive data "
            f"({leaked[0]['type'] if leaked else 'none detected'})."
        ),
        fix="Add an output redaction guard for secrets and identifiers, block raw secret patterns before return, "
        "and keep credentials out of prompts, retrieved context, and tool outputs.",
        evidence={"leaks": leaked},
    ).clamp()


# --------------------------------------------------------------------------- #
# 3. Schema violation — Critical | structured-output contract
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
# 4. Tool call failure — Critical | agent/tool execution contract
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
# 5. Tool result ignored — Critical | tool output grounding
# --------------------------------------------------------------------------- #
def _tool_result_text(call: dict) -> str:
    parts: list[str] = []
    for key in ("output", "result", "content", "response"):
        value = call.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif value is not None:
            try:
                parts.append(json.dumps(value, sort_keys=True))
            except TypeError:
                parts.append(str(value))
    return "\n".join(parts)


def detect_tool_result_ignored(s: SignalVector, rec: CaptureRecord, t: Thresholds) -> DetectorResult:
    outputs = [
        _tool_result_text(call)
        for call in (rec.tool_calls or [])
        if not call.get("error") and str(call.get("status", "")).lower() not in {"error", "failed"}
    ]
    outputs = [o for o in outputs if len(_tokens(o)) >= 5]
    overlaps = [_text_overlap(rec.llm_output or "", o) for o in outputs]
    min_overlap = min(overlaps) if overlaps else 1.0
    fired = bool(outputs) and min_overlap < 0.12
    return DetectorResult(
        failure=TOOL_RESULT_IGNORED,
        fired=fired,
        confidence=0.78 if fired else 0.0,
        severity=SEVERITY[TOOL_RESULT_IGNORED],
        root_cause=(
            f"A tool returned usable evidence, but the answer has only "
            f"{min_overlap:.0%} lexical overlap with the tool result."
        ),
        fix="Require the final answer to ground every factual claim in the latest tool result, "
        "add a post-tool verifier, and retry when the model answers from memory after tool execution.",
        evidence={"tool_result_count": len(outputs), "min_tool_output_overlap": round(min_overlap, 4)},
    ).clamp()


# --------------------------------------------------------------------------- #
# 6. Prompt injection in retrieved context — Critical | RAG safety
# --------------------------------------------------------------------------- #
def detect_prompt_injection(s: SignalVector, rec: CaptureRecord, t: Thresholds) -> DetectorResult:
    matches: list[dict[str, str | int]] = []
    for i, chunk in enumerate(rec.retrieved_chunks or [], start=1):
        m = _INJECTION_RE.search(chunk or "")
        if m:
            matches.append({"chunk": i, "sample": m.group(0)[:80]})

    fired = bool(matches)
    return DetectorResult(
        failure=PROMPT_INJECTION,
        fired=fired,
        confidence=0.88 if fired else 0.0,
        severity=SEVERITY[PROMPT_INJECTION],
        root_cause=(
            f"Retrieved context contains instruction-like text that can override the task "
            f"({matches[0]['sample'] if matches else 'none detected'})."
        ),
        fix="Treat retrieved text strictly as untrusted data: wrap it in delimiters, strip instruction-like spans, "
        "and add a system rule that retrieved content cannot change developer or system instructions.",
        evidence={"matches": matches},
    ).clamp()


# --------------------------------------------------------------------------- #
# 7. Query drift — Warning | retrieval rewrite layer
# --------------------------------------------------------------------------- #
def detect_query_drift(s: SignalVector, rec: CaptureRecord, t: Thresholds) -> DetectorResult:
    fired = bool(rec.retrieval_query and rec.retrieved_chunks) and s.query_drift > 0.72
    conf = 0.62 + min(max(s.query_drift - 0.72, 0.0) * 0.40, 0.18)
    return DetectorResult(
        failure=QUERY_DRIFT,
        fired=fired,
        confidence=conf,
        severity=SEVERITY[QUERY_DRIFT],
        root_cause=(
            f"The retrieval query drifted {s.query_drift:.0%} away from the user prompt, "
            "so the retriever may be searching for the wrong problem."
        ),
        fix="Log and constrain query rewriting: preserve user entities, include the original request beside the rewrite, "
        "and retry retrieval when rewrite drift is high.",
        evidence={"user_prompt": rec.user_prompt, "retrieval_query": rec.retrieval_query,
                  "query_drift": s.query_drift, "similarity": s.similarity},
    ).clamp()


# --------------------------------------------------------------------------- #
# 8. Retrieval failure — Critical | checked after contract failures
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
                  "overlap": s.overlap, "retrieval_top_score": s.retrieval_top_score},
    ).clamp()


# --------------------------------------------------------------------------- #
# 9. Retrieval ambiguity — Warning | top-k ranking quality
# --------------------------------------------------------------------------- #
def detect_retrieval_ambiguity(s: SignalVector, rec: CaptureRecord, t: Thresholds) -> DetectorResult:
    has_topk = len([x for x in (rec.similarity_scores or []) if _is_number(x)]) >= 2
    fired = (
        has_topk
        and s.similarity >= t.similarity_min
        and s.retrieval_margin < 0.05
        and s.retrieval_entropy > 0.80
    )
    conf = 0.60
    if s.retrieval_margin < 0.02:
        conf += 0.08
    if s.retrieval_entropy > 0.90:
        conf += 0.06
    return DetectorResult(
        failure=RETRIEVAL_AMBIGUITY,
        fired=fired,
        confidence=conf,
        severity=SEVERITY[RETRIEVAL_AMBIGUITY],
        root_cause=(
            f"Top retrieved chunks are too close to rank confidently "
            f"(margin {s.retrieval_margin:.2f}, entropy {s.retrieval_entropy:.2f})."
        ),
        fix="Add a reranker, use metadata filters, ask a clarifying question for ambiguous entities, "
        "or widen hybrid search before selecting final chunks.",
        evidence={"retrieval_margin": s.retrieval_margin, "retrieval_entropy": s.retrieval_entropy,
                  "similarity": s.similarity},
    ).clamp()


# --------------------------------------------------------------------------- #
# 10. Citation failure — Warning | source attribution contract
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
        if s.claims_total and s.claim_support < 0.70:
            score += 0.15
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
                  "variance": s.variance, "overlap": s.overlap,
                  "claim_support": s.claim_support,
                  "claims_unsupported": s.claims_unsupported},
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
    detect_sensitive_data_leak,
    detect_schema_violation,
    detect_tool_call_failure,
    detect_tool_result_ignored,
    detect_prompt_injection,
    detect_query_drift,
    detect_retrieval_failure,
    detect_retrieval_ambiguity,
    detect_citation_failure,
    detect_entity_gap,
    detect_hallucination,
    detect_prompt_brittleness,
    detect_ambiguous_prompt,
]
