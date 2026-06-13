"""Threshold configuration (Architecture §7.2).

Cold-start defaults loaded from ``thresholds.json``. In production these become
per-user adaptive values (cold <50 req: defaults; warm 50-500: percentile; hot
>500: rolling window). For the MVP we ship the deterministic defaults and expose
a simple override hook.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path

_DEFAULTS_PATH = Path(__file__).with_name("thresholds.json")


@dataclass(frozen=True)
class Thresholds:
    context_length_ratio_max: float = 0.85
    token_usage_high: float = 0.80
    latency_high_ms: float = 3000
    overlap_low: float = 0.40
    overlap_very_low: float = 0.30
    similarity_min: float = 0.50
    entity_coverage_min: float = 0.40
    entity_coverage_hallucination: float = 0.50
    contradiction_min: float = 0.20
    variance_min: float = 0.30
    temperature_high: float = 0.5
    hallucination_fire: float = 0.50

    @classmethod
    def load(cls, path: Path | None = None) -> "Thresholds":
        path = path or _DEFAULTS_PATH
        try:
            raw = json.loads(path.read_text())
        except FileNotFoundError:
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})


DEFAULT_THRESHOLDS = Thresholds.load()
