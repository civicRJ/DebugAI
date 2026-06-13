"""Per-model metrics ledger — lightweight thread-safe counters for tokens,
cost, latency, requests, and failures.

    import debugai
    debugai.metrics.snapshot()      # full dict
    debugai.metrics.by_model        # per-model breakdown
    debugai.metrics.reset()         # clear all counters
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class _ModelStats:
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    failures: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    _latencies: list[float] = field(default_factory=list)

    def record(self, prompt: int, completion: int, cost: float,
               latency_ms: float, failed: bool, from_cache: bool = False) -> None:
        self.requests += 1
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion
        self.cost_usd = round(self.cost_usd + cost, 8)
        if not from_cache:
            self._latencies.append(latency_ms)
        if failed:
            self.failures += 1
        if from_cache:
            self.cache_hits += 1
        else:
            self.cache_misses += 1

    def _pct(self, p: float) -> float:
        if not self._latencies:
            return 0.0
        s = sorted(self._latencies)
        i = max(0, min(int(len(s) * p), len(s) - 1))
        return round(s[i], 2)

    def to_dict(self) -> dict:
        return {
            "requests": self.requests,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "failures": self.failures,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "latency_p50_ms": self._pct(0.50),
            "latency_p95_ms": self._pct(0.95),
        }


class MetricsLedger:
    """Thread-safe per-model aggregate counters. Updated by the SDK worker
    after each request; safe to read from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._models: dict[str, _ModelStats] = {}
        self._global = _ModelStats()

    # ── Recording (called by background worker) ─────────────────────────────
    def record(self, model: str, prompt_tokens: int, completion_tokens: int,
               cost_usd: float, latency_ms: float, failed: bool,
               from_cache: bool = False) -> None:
        with self._lock:
            if model not in self._models:
                self._models[model] = _ModelStats()
            self._models[model].record(prompt_tokens, completion_tokens,
                                        cost_usd, latency_ms, failed, from_cache)
            self._global.record(prompt_tokens, completion_tokens,
                                cost_usd, latency_ms, failed, from_cache)

    # ── Read properties (safe from any thread) ──────────────────────────────
    @property
    def requests(self) -> int:
        with self._lock:
            return self._global.requests

    @property
    def failures(self) -> int:
        with self._lock:
            return self._global.failures

    @property
    def total_tokens(self) -> int:
        with self._lock:
            return self._global.total_tokens

    @property
    def cost_usd(self) -> float:
        with self._lock:
            return self._global.cost_usd

    @property
    def latency_p50(self) -> float:
        with self._lock:
            return self._global._pct(0.50)

    @property
    def latency_p95(self) -> float:
        with self._lock:
            return self._global._pct(0.95)

    @property
    def by_model(self) -> dict[str, dict]:
        with self._lock:
            return {m: s.to_dict() for m, s in self._models.items()}

    def snapshot(self) -> dict:
        """Return a complete, JSON-serialisable snapshot of all counters."""
        with self._lock:
            return {
                **self._global.to_dict(),
                "by_model": {m: s.to_dict() for m, s in self._models.items()},
            }

    def reset(self) -> None:
        """Clear all counters (useful between test runs or reporting windows)."""
        with self._lock:
            self._models.clear()
            self._global = _ModelStats()


# Module-level singleton — `import debugai; debugai.metrics`
metrics = MetricsLedger()
