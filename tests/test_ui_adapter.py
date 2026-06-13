"""Tests for the diagnosis → design-system props adapter."""

from server.ui_adapter import to_card


def _diag(primary=None, healthy=False, signals=None, secondary=None, explanation=""):
    return {
        "healthy": healthy,
        "primary": primary,
        "secondary": secondary or [],
        "signals": signals or {},
        "explanation": explanation,
    }


BASE_SIGNALS = {
    "overlap": 0.1, "entity_coverage": 0.0, "similarity": 0.41, "contradiction": 0.5,
    "variance": 0.1, "latency_ms": 1200, "token_ratio": 0.2, "context_ratio": 0.2,
}


def test_healthy_maps_to_ok():
    card = to_card(_diag(healthy=True, signals=BASE_SIGNALS))
    assert card["severity"] == "ok"
    assert card["id"] == "healthy"
    assert card["confidence"] is None


def test_warning_severity_maps_to_warn():
    card = to_card(_diag(primary={
        "failure": "prompt_brittleness", "confidence": 0.75, "severity": "warning",
        "root_cause": "rc", "fix": "lower temperature",
    }, signals=BASE_SIGNALS))
    assert card["severity"] == "warn"
    assert card["title"] == "Prompt brittleness"


def test_signals_get_status_against_thresholds():
    card = to_card(_diag(primary={
        "failure": "retrieval_failure", "confidence": 0.95, "severity": "critical",
        "root_cause": "rc", "fix": "fix",
    }, signals=BASE_SIGNALS))
    by_name = {s["name"]: s for s in card["signals"]}
    # similarity 0.41 < 0.50 → anomalous
    assert by_name["retrieval sim"]["status"] == "critical"
    # contradiction 0.5 > 0.20 → anomalous
    assert by_name["contradiction"]["status"] == "critical"
    # token usage 0.2 < 0.80 → healthy/trace
    assert by_name["token usage"]["status"] == "trace"
    # all 8 signals present
    assert len(card["signals"]) == 8


def test_latency_normalised_and_formatted():
    card = to_card(_diag(primary={
        "failure": "context_overflow", "confidence": 0.9, "severity": "critical",
        "root_cause": "rc", "fix": "fix",
    }, signals={**BASE_SIGNALS, "latency_ms": 3500}))
    lat = next(s for s in card["signals"] if s["name"] == "latency")
    assert lat["value"] == "3500ms"
    assert lat["status"] == "critical"  # > 3000ms threshold
    assert 0 <= lat["confidence"] <= 1


def test_explanation_html_is_stripped_xss_safe():
    # The DiagnosticCard 'location' slot uses innerHTML — explanation must be plain.
    card = to_card(_diag(primary={
        "failure": "hallucination", "confidence": 0.9, "severity": "critical",
        "root_cause": "rc", "fix": "fix",
    }, signals=BASE_SIGNALS, explanation="<img src=x onerror=alert(1)>visible text"))
    assert "<" not in card["explanation"] and ">" not in card["explanation"]
    assert "onerror" not in card["explanation"]   # tag (and its handlers) removed
    assert "visible text" in card["explanation"]  # text content preserved


def test_secondary_carried_through():
    card = to_card(_diag(
        primary={"failure": "retrieval_failure", "confidence": 0.95, "severity": "critical",
                 "root_cause": "rc", "fix": "fix"},
        secondary=[{"failure": "hallucination", "confidence": 0.6, "severity": "critical"}],
        signals=BASE_SIGNALS,
    ))
    assert card["secondary"][0]["title"] == "Hallucination"
