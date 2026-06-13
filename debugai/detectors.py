"""Layer 2 — Failure Classification Rules (Architecture §5).

Five deterministic detectors. Each takes the signal vector + thresholds and
returns a DetectorResult. All detectors run (§5.2); results are ranked by
confidence into primary + secondary. Gate patterns prevent nonsensical
multi-classification.

Detector bases are tuned to the doc's worked example: Scenario A (similarity
0.41, entity 0.17, overlap 0.12) → retrieval failure 0.95 = 0.70 base + 0.15
(entity) + 0.10 (overlap).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from debugai.schema import CaptureRecord
from debugai.signals import SignalVector
from debugai.thresholds import Thresholds

# Failure type identifiers (also used by the fix-agent registry later).
CONTEXT_OVERFLOW = "context_overflow"
RETRIEVAL_FAILURE = "retrieval_failure"
ENTITY_GAP = "entity_gap"
HALLUCINATION = "hallucination"
PROMPT_BRITTLENESS = "prompt_brittleness"

SEVERITY = {
    CONTEXT_OVERFLOW: "critical",
    RETRIEVAL_FAILURE: "critical",
    ENTITY_GAP: "warning",
    HALLUCINATION: "critical",
    PROMPT_BRITTLENESS: "warning",
}

_GATED_BASE = 0.70  # base confidence for a critical gated detector that fires


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
# 2. Retrieval failure — Critical | checked 2nd
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
# 3. Entity gap — Warning | checked 3rd
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
# 4. Hallucination — Critical | checked 4th
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
# 5. Prompt brittleness — Warning | checked 5th
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


# Priority order matters (§5.2): earlier detectors gate later ones.
DETECTORS = [
    detect_context_overflow,
    detect_retrieval_failure,
    detect_entity_gap,
    detect_hallucination,
    detect_prompt_brittleness,
]
