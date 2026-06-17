"""Layer 1 tests — signal computations behave and stay in range."""

import math

import pytest

from debugai.schema import CaptureRecord
from debugai.signals import (
    SignalVector,
    compute_entity_coverage,
    compute_overlap,
    compute_query_drift,
    compute_retrieval_quality,
    compute_signals,
    compute_context_dilution,
    compute_freshness_gap,
    compute_retrieval_coverage,
    compute_source_conflict,
    compute_tool_argument_risk,
    compute_token_ratio,
    estimate_variance,
)


def _rec(**kw):
    base = dict(user_prompt="q", llm_output="a")
    base.update(kw)
    return CaptureRecord(**base)


def test_overlap_grounded_vs_fabricated():
    ctx = "Refunds are issued within 30 days with a receipt."
    grounded, _ = compute_overlap("Refunds are issued within 30 days.", ctx)
    fabricated, _ = compute_overlap("The capital of France is Paris.", ctx)
    assert grounded > fabricated
    assert 0.0 <= fabricated <= grounded <= 1.0


def test_overlap_no_context_is_grounded_sentinel():
    score, method = compute_overlap("anything", "")
    assert score == 1.0 and method == "no-context"


def test_entity_coverage_counts_missing():
    cov, total, missing = compute_entity_coverage(
        "The Model Z tows 4500 kg.", "The Model Z is a pickup truck."
    )
    assert 0.0 <= cov <= 1.0
    assert total >= 1
    assert missing == total - round(cov * total)


def test_entity_coverage_no_entities_is_full():
    cov, total, missing = compute_entity_coverage("it works well", "context here")
    assert (cov, total, missing) == (1.0, 0, 0)


def test_variance_scales_with_temperature():
    low, _ = estimate_variance(_rec(temperature=0.0))
    high, _ = estimate_variance(_rec(temperature=1.0))
    none, _ = estimate_variance(_rec(temperature=None))
    assert none == 0.0
    assert high > low
    assert 0.0 <= high <= 1.0


def test_variance_reduced_by_constraints():
    free, _ = estimate_variance(_rec(temperature=1.0, system_prompt="answer freely"))
    constrained, _ = estimate_variance(
        _rec(temperature=1.0, system_prompt="Respond ONLY in JSON format.")
    )
    assert constrained < free


def test_token_ratio_uses_usage_then_cap():
    r = _rec(token_usage={"total": 800}, max_tokens=1000)
    assert compute_token_ratio(r) == pytest.approx(0.8)
    assert compute_token_ratio(_rec()) == 0.0  # no cap → cannot flag


def test_retrieval_quality_captures_margin_and_entropy():
    top, margin, entropy = compute_retrieval_quality(
        _rec(similarity_scores=[0.82, 0.81, 0.80])
    )
    assert top == pytest.approx(0.82)
    assert margin == pytest.approx(0.01)
    assert entropy > 0.99


def test_query_drift_detects_bad_retrieval_rewrite():
    drift = compute_query_drift(_rec(
        user_prompt="What is the refund policy for annual plans?",
        retrieval_query="enterprise security SOC2 audit retention",
        retrieved_chunks=["Annual plans can be refunded within 30 days."],
    ))
    assert drift > 0.8


def test_expanded_debugging_signals_cover_pipeline_risks():
    rec = _rec(
        user_prompt="What is the latest refund policy for annual plans?",
        retrieved_chunks=[
            "Parking is behind the building.",
            "Refunds are allowed within 30 days.",
            "Refunds are not allowed after purchase.",
        ],
        similarity_scores=[0.7, 0.6, 0.5],
        tool_calls=[{"name": "refund_order", "input": '{"order_id":"*","action":"refund all"}'}],
    )
    assert compute_retrieval_coverage(rec) < 0.6
    assert compute_context_dilution(rec) > 0.0
    assert compute_source_conflict(rec.retrieved_chunks) > 0.5
    assert compute_freshness_gap(rec) == 1.0
    assert compute_tool_argument_risk(rec) > 0.0


def test_compute_signals_returns_full_vector_no_nan():
    s = compute_signals(_rec(
        user_prompt="What is the refund policy?",
        llm_output="Refunds within 30 days.",
        retrieved_chunks=["Refunds are issued within 30 days with a receipt."],
        similarity_scores=[0.88, 0.74],
        temperature=0.2,
    ))
    assert isinstance(s, SignalVector)
    assert s.retrieval_top_score == pytest.approx(0.88)
    assert s.retrieval_margin == pytest.approx(0.14)
    assert s.claim_support == pytest.approx(1.0)
    assert "retrieval_coverage" in s.to_dict()
    assert "context_dilution" in s.to_dict()
    for name, val in s.to_dict().items():
        if isinstance(val, float):
            assert not math.isnan(val), name


def test_lazy_skips_expensive_when_healthy():
    s = compute_signals(_rec(
        llm_output="ok",
        similarity_scores=[0.9],
        temperature=0.0,
    ), lazy=True)
    assert s.overlap_method == "skipped-lazy"
    assert s.overlap == 1.0 and s.contradiction == 0.0
