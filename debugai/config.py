"""DebugAI SDK configuration — a single object controls everything that runs
per request, replacing the scattered wrap_llm() keyword arguments.

    from debugai import DebugAIConfig
    config = DebugAIConfig(
        enable_judge=True,      # LLM-as-judge for system-prompt adherence
        sample_rate=0.1,        # diagnose 10% of requests
        on_diagnosis=lambda d: print(d["primary"]),
        sink_url="http://my-debugai/api/traces",
        sink_token="dbg_...",
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from debugai.thresholds import DEFAULT_THRESHOLDS, Thresholds


@dataclass
class DebugAIConfig:
    # ── Background workers ──────────────────────────────────────────────────
    enable_diagnosis: bool = True
    """Run the 8-signal engine + 5 detectors on every (sampled) request."""

    enable_traces: bool = True
    """Emit an observability Trace (spans, scores, cost) per request."""

    enable_judge: bool = False
    """LLM-as-judge: check system-prompt rule adherence (costs an LLM call)."""

    enable_explain: bool = False
    """LLM explainer: generate a human-readable explanation (costs an LLM call)."""

    lazy: bool = True
    """Skip expensive signals (embeddings/NER/NLI) when cheap signals are healthy."""

    sample_rate: float = 1.0
    """Fraction of requests to diagnose (0.0–1.0). Deterministic count-based."""

    max_queue_depth: int = 10_000
    """Maximum pending jobs in the background worker queue. Excess jobs are
    dropped (backpressure) so diagnosis never slows the real request."""

    # ── Metrics ─────────────────────────────────────────────────────────────
    track_tokens: bool = True
    """Accumulate prompt + completion token counts per model in MetricsLedger."""

    track_cost: bool = True
    """Estimate cost per request and accumulate in MetricsLedger."""

    track_latency: bool = True
    """Record per-request latency for p50/p95 in MetricsLedger."""

    # ── Sinks ───────────────────────────────────────────────────────────────
    on_diagnosis: Callable[[dict], None] | None = None
    """Called with each diagnosis dict after background analysis completes."""

    on_trace: Callable[[Any], None] | None = None
    """Called with each Trace object after background analysis completes."""

    on_metrics: Callable[[dict], None] | None = None
    """Called after each request with a snapshot of per-request metrics."""

    sink_url: str | None = None
    """POST traces to a DebugAI server endpoint (e.g. http://…/api/traces).
    Requires sink_token if the server has auth enabled."""

    sink_token: str | None = None
    """X-API-Key token for sink_url authentication."""

    # ── Conversation ────────────────────────────────────────────────────────
    session_id: str | None = None
    """Default session ID for all traces; overridden by the session() ctx manager."""

    tags: dict[str, str] = field(default_factory=dict)
    """Key-value tags attached to every trace and diagnosis record."""

    # ── Thresholds ──────────────────────────────────────────────────────────
    thresholds: Thresholds = field(default_factory=lambda: DEFAULT_THRESHOLDS)
    """Detection thresholds. Per-user adaptive calibration overrides these at
    the server level; SDK callers can override them explicitly here."""

    # ── Provider config ──────────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434/v1"
    """Ollama server URL for local models (Qwen, Llama, Phi, DeepSeek…).
    Overridden by the OLLAMA_BASE_URL env var."""

    model_prices: dict | None = None
    """Custom per-model pricing overrides: {"my-model": (input_$/1M, output_$/1M)}.
    Merged with the built-in table; your entries take precedence."""

    # ── LiteLLM-parity features (B1+) ───────────────────────────────────────
    fallbacks: list = field(default_factory=list)
    """Model names to try if the primary call fails (rate limit / error / timeout).
    e.g. fallbacks=['claude-haiku-4-5', 'ollama/qwen2.5']"""

    response_schema: dict | None = None
    """JSON Schema to validate structured outputs. Violations are surfaced as
    an instruction_violation in the diagnosis."""

    on_schema_violation: Callable | None = None
    """Called when a schema violation is detected: fn(output_text, violations_list)."""
