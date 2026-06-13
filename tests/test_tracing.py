"""Tests for native observability tracing."""

from debugai.tracing import (
    Span, Trace, Tracer, estimate_cost, scores_from_diagnosis, status_from_diagnosis,
)


def test_cost_estimation_known_and_unknown_models():
    # claude-haiku-4-5: (0.80, 4.0) per 1M tokens
    assert estimate_cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000) == 0.80 + 4.0
    assert estimate_cost("gpt-4o", 0, 0) == 0.0
    assert estimate_cost("some-unknown-model", 1000, 1000) == 0.0
    assert estimate_cost(None, 100, 100) == 0.0


def test_trace_rolls_up_spans():
    t = Trace(name="req", model="claude-haiku-4-5")
    with t.span("retrieval", kind="retrieval") as s:
        s.output = ["chunk a", "chunk b"]
    with t.span("generation", kind="generation", model="claude-haiku-4-5") as s:
        s.set_usage(prompt=1000, completion=500)
    t.end()
    assert len(t.spans) == 2
    assert t.prompt_tokens == 1000 and t.completion_tokens == 500
    assert t.total_tokens == 1500
    assert t.cost_usd > 0
    assert t.duration_ms >= 0
    d = t.to_dict()
    assert d["spans"][0]["kind"] == "retrieval"
    assert d["total_tokens"] == 1500


def test_scores_from_diagnosis_failing():
    diag = {"healthy": False, "primary": {"failure": "retrieval_failure",
            "confidence": 0.95, "severity": "critical"}}
    scores = {s.name: s for s in scores_from_diagnosis(diag)}
    assert scores["healthy"].value is False
    assert scores["failure"].value == "retrieval_failure"
    assert scores["confidence"].value == 0.95
    assert status_from_diagnosis(diag) == "failing"


def test_scores_from_diagnosis_healthy():
    diag = {"healthy": True, "primary": None}
    scores = {s.name: s for s in scores_from_diagnosis(diag)}
    assert scores["healthy"].value is True and "failure" not in scores
    assert status_from_diagnosis(diag) == "ok"


def test_tracer_sends_to_sink():
    captured = []
    tracer = Tracer(sink=captured.append)
    with tracer.trace("chat", session_id="sess-1", model="gpt-4o") as t:
        with t.span("generation", kind="generation", model="gpt-4o") as s:
            s.set_usage(prompt=10, completion=5)
        t.add_score("confidence", 0.8)
    assert len(captured) == 1
    tr = captured[0]
    assert tr.session_id == "sess-1" and tr.total_tokens == 15
    assert any(sc.name == "confidence" for sc in tr.scores)
