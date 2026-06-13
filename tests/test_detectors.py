"""Layer 2 tests — detectors fire on the right signal patterns, gates hold,
and the worked example from the architecture doc reproduces."""

from debugai.detectors import (
    CONTEXT_OVERFLOW,
    ENTITY_GAP,
    HALLUCINATION,
    PROMPT_BRITTLENESS,
    RETRIEVAL_FAILURE,
)
from debugai.diagnosis import diagnose
from debugai.schema import CaptureRecord
from debugai.signals import SignalVector
from debugai.thresholds import DEFAULT_THRESHOLDS as T


def _sig(**kw):
    base = dict(
        overlap=0.8, entity_coverage=1.0, similarity=0.85, contradiction=0.02,
        variance=0.05, latency_ms=500, token_ratio=0.2, context_ratio=0.2,
    )
    base.update(kw)
    return SignalVector(**base)


REC = CaptureRecord(user_prompt="q", llm_output="a", temperature=0.2)


def _primary(sig, rec=REC):
    d = diagnose(sig, rec, T)
    return (None if d.healthy else d.primary.failure), d


def test_healthy_passes():
    failure, d = _primary(_sig())
    assert d.healthy and failure is None


def test_doc_scenario_a_retrieval_failure_095():
    # Architecture §4.2 Scenario A: overlap .12, entity .17, similarity .41.
    sig = _sig(overlap=0.12, entity_coverage=0.17, similarity=0.41, contradiction=0.08)
    d = diagnose(sig, REC, T)
    assert d.primary.failure == RETRIEVAL_FAILURE
    assert d.primary.confidence == 0.95  # 0.70 + 0.15 (entity) + 0.10 (overlap)


def test_context_overflow_gate_and_boosts():
    sig = _sig(context_ratio=0.90, token_ratio=0.85, latency_ms=3500, overlap=0.30)
    failure, d = _primary(sig)
    assert failure == CONTEXT_OVERFLOW
    assert d.primary.confidence == 1.0  # base + all three boosts, clamped


def test_hallucination_fires_when_grounding_fails_despite_good_similarity():
    sig = _sig(similarity=0.7, entity_coverage=0.3, contradiction=0.4, variance=0.5, overlap=0.5)
    failure, _ = _primary(sig, CaptureRecord(user_prompt="q", llm_output="a", temperature=0.8))
    assert failure == HALLUCINATION


def test_entity_gap_vs_hallucination_distinguished_by_calm_signals():
    # Same missing entities, but calm (low variance, no contradiction) → entity gap.
    calm = _sig(similarity=0.7, entity_coverage=0.3, contradiction=0.05, variance=0.1, overlap=0.5)
    failure, _ = _primary(calm)
    assert failure == ENTITY_GAP


def test_prompt_brittleness_residual():
    sig = _sig(similarity=0.8, entity_coverage=1.0, contradiction=0.02, variance=0.6)
    rec = CaptureRecord(user_prompt="q", llm_output="a", temperature=0.9)
    failure, d = _primary(sig, rec)
    assert failure == PROMPT_BRITTLENESS
    assert d.primary.confidence == 0.75  # 0.60 + 0.15 temp boost


def test_multi_causal_primary_and_secondary():
    # Retrieval failure (high conf) + brittleness-ish residual shouldn't both be primary.
    sig = _sig(overlap=0.1, entity_coverage=0.1, similarity=0.3, contradiction=0.1)
    d = diagnose(sig, REC, T)
    assert d.primary.failure == RETRIEVAL_FAILURE
    assert all(s.confidence <= d.primary.confidence for s in d.secondary)
