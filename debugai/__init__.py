"""DebugAI — AI Observability & Debugging Platform.

A 3-layer root-cause engine for LLM application failures:

  Layer 1 (deterministic)  — Signal extraction: 8 metrics per request.
  Layer 2 (deterministic)  — Rule engine: 5 failure detectors, primary + secondary.
  Layer 3 (probabilistic)  — LLM explainer: human-readable explanation + fix.

Public API (Level 1 integration):

    from debugai import analyze
    result = analyze(prompt, output, chunks=..., similarity_scores=...)
"""

from debugai.schema import CaptureRecord
from debugai.analyze import analyze
from debugai.config import DebugAIConfig
from debugai.metrics import metrics
from debugai.sdk import (
    wrap_llm, awrap_llm, retrieval_context, session, http_trace_sink,
    completion, acompletion, CompletionResponse,
    register_provider, register_adapter, set_default_config,
    compare, ComparisonResult, BudgetExceededError,
    _GenericOpenAICompatAdapter,
)
from debugai.tracing import Trace, Span, Tracer, Score

__all__ = [
    # Core
    "analyze", "CaptureRecord",
    # Config & metrics
    "DebugAIConfig", "metrics",
    # SDK wrappers
    "wrap_llm", "awrap_llm",
    # Universal completion API
    "completion", "acompletion", "CompletionResponse",
    # Registration
    "register_provider", "register_adapter", "set_default_config",
    # Context managers
    "retrieval_context", "session",
    # Observability
    "Trace", "Span", "Tracer", "Score",
    # Sinks
    "http_trace_sink",
    # Adapters
    "_GenericOpenAICompatAdapter",
    # Compare + budget
    "compare", "ComparisonResult", "BudgetExceededError",
]
__version__ = "0.2.0"
__all__ += ["__version__"]
