"""Tests for the adaptive threshold calibration engine (§7.2)."""

from debugai.calibration import COLD_MAX, WARM_MAX, ThresholdStore
from debugai.thresholds import DEFAULT_THRESHOLDS


def _healthy_row(i):
    # A tight, high-quality healthy baseline with a little spread.
    return {
        "similarity": 0.80 + (i % 10) * 0.01,      # 0.80–0.89
        "overlap": 0.70 + (i % 10) * 0.01,         # 0.70–0.79
        "entity_coverage": 0.90,
        "contradiction": 0.02 + (i % 5) * 0.005,   # ~0.02–0.04
        "variance": 0.05,
        "context_ratio": 0.20,
        "token_ratio": 0.25,
        "latency_ms": 800 + (i % 10) * 10,
    }


def _feed(store, n, healthy=True):
    for i in range(n):
        store.record(_healthy_row(i), healthy=healthy)


def test_cold_returns_defaults():
    store = ThresholdStore()
    _feed(store, 10)
    assert store.regime() == "cold"
    assert store.current() is DEFAULT_THRESHOLDS


def test_warm_tightens_to_user_baseline():
    store = ThresholdStore()
    _feed(store, 60)  # > COLD_MAX, <= WARM_MAX
    assert store.regime() == "warm"
    t = store.current()
    # User's healthy similarity sits ~0.85, so the floor rises above the 0.50 default.
    assert t.similarity_min > DEFAULT_THRESHOLDS.similarity_min
    assert t.overlap_low > DEFAULT_THRESHOLDS.overlap_low
    # Low-contradiction baseline → stricter contradiction gate (clamped at 0.10).
    assert t.contradiction_min <= DEFAULT_THRESHOLDS.contradiction_min


def test_hot_uses_zscore_window():
    store = ThresholdStore(window=WARM_MAX)
    _feed(store, WARM_MAX + 50)  # > WARM_MAX → hot
    assert store.regime() == "hot"
    t = store.current()
    # similarity_min ≈ mean - 2·std of the healthy baseline, and well above default.
    assert 0.5 < t.similarity_min < 0.9


def test_clamps_prevent_runaway():
    store = ThresholdStore()
    # Very-low-but-nonzero baseline: mean+2std falls below the clamp floor, so the
    # calibrated value is pinned to the floor (not collapsed to ~0).
    for _ in range(60):
        store.record({"similarity": 0.85, "overlap": 0.75, "entity_coverage": 0.9,
                      "contradiction": 0.01, "variance": 0.01, "context_ratio": 0.2,
                      "token_ratio": 0.2, "latency_ms": 800}, healthy=True)
    t = store.current()
    assert t.contradiction_min == 0.10  # clamp floor
    assert t.variance_min == 0.15       # clamp floor


def test_degenerate_all_zero_signal_not_adapted():
    store = ThresholdStore()
    # context_ratio never supplied (always 0) → signal not exercised → keep default.
    for _ in range(60):
        store.record({"similarity": 0.85, "overlap": 0.75, "entity_coverage": 0.9,
                      "contradiction": 0.02, "variance": 0.05, "context_ratio": 0.0,
                      "token_ratio": 0.0, "latency_ms": 0}, healthy=True)
    d = store.details()
    by_field = {s["field"]: s for s in d["signals"]}
    assert by_field["context_length_ratio_max"]["adapted"] is False
    assert by_field["latency_high_ms"]["adapted"] is False
    assert store.current().context_length_ratio_max == DEFAULT_THRESHOLDS.context_length_ratio_max


def test_only_healthy_requests_form_baseline():
    store = ThresholdStore()
    _feed(store, 60, healthy=False)  # 60 requests, none healthy
    assert store.regime() == "warm"
    d = store.details()
    assert d["healthy_baseline"] == 0
    # No baseline → every signal keeps its default.
    assert all(not s["adapted"] for s in d["signals"])
    assert store.current().similarity_min == DEFAULT_THRESHOLDS.similarity_min


def test_details_report_shape():
    store = ThresholdStore()
    _feed(store, 60)
    d = store.details()
    assert d["regime"] == "warm" and d["total_requests"] == 60
    assert len(d["signals"]) == len(DEFAULT_THRESHOLDS.__dataclass_fields__) - 4 or len(d["signals"]) == 8
    fields = {s["field"] for s in d["signals"]}
    assert "similarity_min" in fields and "latency_high_ms" in fields
