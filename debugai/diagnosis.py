"""Diagnosis pipeline (Architecture §5.2 / §7.3).

Runs all five detectors, ranks the ones that fired by confidence, and returns a
primary diagnosis plus secondary issues. Gate patterns in the detectors prevent
nonsensical combinations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from debugai.detectors import DETECTORS, DetectorResult
from debugai.schema import CaptureRecord
from debugai.signals import SignalVector
from debugai.thresholds import DEFAULT_THRESHOLDS, Thresholds


@dataclass
class Diagnosis:
    healthy: bool
    primary: DetectorResult | None
    secondary: list[DetectorResult] = field(default_factory=list)
    signals: SignalVector | None = None

    def to_dict(self) -> dict:
        def fmt(r: DetectorResult | None) -> dict | None:
            if r is None:
                return None
            return {
                "failure": r.failure,
                "confidence": r.confidence,
                "severity": r.severity,
                "root_cause": r.root_cause,
                "fix": r.fix,
                "evidence": r.evidence,
            }

        return {
            "healthy": self.healthy,
            "primary": fmt(self.primary),
            "secondary": [fmt(r) for r in self.secondary],
            "signals": self.signals.to_dict() if self.signals else None,
        }


def diagnose(
    signals: SignalVector,
    rec: CaptureRecord,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> Diagnosis:
    """Classify a signal vector into primary + secondary failures."""
    results = [detector(signals, rec, thresholds) for detector in DETECTORS]
    fired = [r for r in results if r.fired]
    # Rank by confidence; ties broken by detector priority (stable sort order).
    fired.sort(key=lambda r: r.confidence, reverse=True)

    if not fired:
        return Diagnosis(healthy=True, primary=None, secondary=[], signals=signals)
    return Diagnosis(
        healthy=False,
        primary=fired[0],
        secondary=fired[1:],
        signals=signals,
    )
