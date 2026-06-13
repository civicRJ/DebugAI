"""Layer 1 tests — signal computations behave and stay in range."""

import math

import pytest

from debugai.schema import CaptureRecord
from debugai.signals import (
    SignalVector,
    compute_entity_coverage,
    compute_overlap,
    compute_signals,
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


def test_compute_signals_returns_full_vector_no_nan():
    s = compute_signals(_rec(
        user_prompt="What is the refund policy?",
        llm_output="Refunds within 30 days.",
        retrieved_chunks=["Refunds are issued within 30 days with a receipt."],
        similarity_scores=[0.88],
        temperature=0.2,
    ))
    assert isinstance(s, SignalVector)
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
