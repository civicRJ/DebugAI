"""Adaptive threshold calibration (Architecture §7.2).

Static thresholds break across embedding models, domains, and chunk sizes. The
``ThresholdStore`` learns a per-user "known good" baseline from the signals of
healthy requests and tightens the gating thresholds to *that user's* norms:

    cold  (<50 requests)   sensible defaults — not enough data yet
    warm  (50-500)         percentile-based (5th / 95th of healthy baseline)
    hot   (>500)           rolling-window z-score (mean ± 2 std), last `window`

A signal is only adapted once it has ``MIN_SAMPLES`` healthy observations;
otherwise its default is kept. Every calibrated value is clamped to a sane band
so pathological data can't produce a runaway threshold.
"""

from __future__ import annotations

import dataclasses
import json
import threading
from dataclasses import dataclass
from pathlib import Path

from debugai.thresholds import DEFAULT_THRESHOLDS, Thresholds

COLD_MAX = 50
WARM_MAX = 500
MIN_SAMPLES = 15
Z = 2.0  # z-score: anomaly = 2 std beyond the healthy baseline

# Thresholds field -> (signal key, direction). "low" = anomaly below threshold,
# "high" = anomaly above threshold. Fields not listed stay fixed (semantic).
CALIBRATION_SPEC: dict[str, tuple[str, str]] = {
    "similarity_min": ("similarity", "low"),
    "overlap_low": ("overlap", "low"),
    "entity_coverage_min": ("entity_coverage", "low"),
    "contradiction_min": ("contradiction", "high"),
    "variance_min": ("variance", "high"),
    "context_length_ratio_max": ("context_ratio", "high"),
    "token_usage_high": ("token_ratio", "high"),
    "latency_high_ms": ("latency_ms", "high"),
}

# Clamp bands keep calibrated thresholds reasonable regardless of the data.
CLAMP: dict[str, tuple[float, float]] = {
    "similarity_min": (0.10, 0.90),
    "overlap_low": (0.10, 0.85),
    "entity_coverage_min": (0.10, 0.85),
    "contradiction_min": (0.10, 0.60),
    "variance_min": (0.15, 0.80),
    "context_length_ratio_max": (0.50, 0.95),
    "token_usage_high": (0.50, 0.95),
    "latency_high_ms": (500.0, 30000.0),
}

_SIGNAL_KEYS = sorted({k for k, _ in CALIBRATION_SPEC.values()})


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _std(xs: list[float], mu: float) -> float:
    if len(xs) < 2:
        return 0.0
    return (sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def _percentile(xs: list[float], p: float) -> float:
    s = sorted(xs)
    if not s:
        return 0.0
    idx = (len(s) - 1) * (p / 100.0)
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    frac = idx - lo
    return s[lo] * (1 - frac) + s[hi] * frac


@dataclass
class SignalCalibration:
    signal: str
    direction: str
    field: str
    n: int
    baseline_mean: float
    baseline_std: float
    default: float
    value: float
    adapted: bool


class ThresholdStore:
    """Per-user adaptive threshold store. Thread-safe; optionally persisted."""

    def __init__(self, path: Path | None = None, window: int = WARM_MAX):
        self._path = path
        self._window = window
        self._lock = threading.Lock()
        self._total = 0
        self._healthy: list[dict[str, float]] = []  # baseline signal rows
        if path is not None:
            self._load()

    # --- persistence -------------------------------------------------------
    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text())
            self._total = data.get("total", 0)
            self._healthy = data.get("healthy", [])[-self._window:]
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.write_text(json.dumps(
            {"total": self._total, "healthy": self._healthy[-self._window:]}
        ))

    # --- ingest ------------------------------------------------------------
    def record(self, signals: dict, healthy: bool) -> None:
        with self._lock:
            self._total += 1
            if healthy:
                row = {k: float(signals.get(k, 0.0)) for k in _SIGNAL_KEYS}
                self._healthy.append(row)
                del self._healthy[:-self._window]
            self._persist()

    # --- regime ------------------------------------------------------------
    def regime(self) -> str:
        if self._total < COLD_MAX:
            return "cold"
        return "warm" if self._total <= WARM_MAX else "hot"

    # --- calibration -------------------------------------------------------
    def _calibrate_field(self, field: str, regime: str) -> SignalCalibration:
        signal, direction = CALIBRATION_SPEC[field]
        default = getattr(DEFAULT_THRESHOLDS, field)
        values = [r[signal] for r in self._healthy if signal in r]
        mu = _mean(values) if values else default
        sd = _std(values, mu) if values else 0.0

        # A baseline that is entirely zero means the signal was never exercised
        # (e.g. no context_window supplied → context_ratio always 0). Don't adapt
        # it — keep the default rather than collapsing to a clamp floor.
        degenerate = mu == 0.0 and sd == 0.0
        adapted = regime != "cold" and len(values) >= MIN_SAMPLES and not degenerate
        value = default
        if adapted:
            if regime == "warm":  # percentile of the healthy baseline
                value = _percentile(values, 5.0 if direction == "low" else 95.0)
            else:  # hot: rolling-window z-score
                value = mu - Z * sd if direction == "low" else mu + Z * sd
            lo, hi = CLAMP[field]
            value = max(lo, min(value, hi))

        return SignalCalibration(
            signal=signal, direction=direction, field=field, n=len(values),
            baseline_mean=round(mu, 4), baseline_std=round(sd, 4),
            default=default, value=round(value, 4), adapted=adapted,
        )

    def current(self) -> Thresholds:
        """The active, calibrated thresholds for this user."""
        with self._lock:
            regime = self.regime()
            if regime == "cold":
                return DEFAULT_THRESHOLDS
            overrides = {
                field: self._calibrate_field(field, regime).value
                for field in CALIBRATION_SPEC
            }
        return dataclasses.replace(DEFAULT_THRESHOLDS, **overrides)

    def details(self) -> dict:
        """Full calibration report for the dashboard."""
        with self._lock:
            regime = self.regime()
            cals = [self._calibrate_field(f, regime) for f in CALIBRATION_SPEC]
            return {
                "regime": regime,
                "total_requests": self._total,
                "healthy_baseline": len(self._healthy),
                "window": self._window,
                "next_regime_at": COLD_MAX if regime == "cold" else (
                    WARM_MAX if regime == "warm" else None
                ),
                "signals": [dataclasses.asdict(c) for c in cals],
            }

    def reset(self) -> None:
        with self._lock:
            self._total = 0
            self._healthy = []
            self._persist()
