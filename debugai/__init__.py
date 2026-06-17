"""DebugAI — SDK-first LLM debugging platform.

A 3-layer root-cause engine for LLM application failures:

  Layer 1 (deterministic)  — Signal extraction: 8 metrics per request.
  Layer 2 (deterministic)  — Rule engine: failure detectors, primary + secondary.
  Layer 3 (probabilistic)  — LLM explainer: human-readable explanation + fix.

Public API (Level 1 integration):

    from debugai import analyze
    result = analyze(prompt, output, chunks=..., similarity_scores=...)
"""

from debugai.schema import CaptureRecord
from debugai.analyze import analyze
from debugai.config import DebugAIConfig
from debugai.examples import example_cases, get_example, list_examples
from debugai.metrics import metrics
from debugai.prompt_audit import audit_prompt
from debugai.report import debug_report, format_debug_report
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
    "analyze", "audit_prompt", "CaptureRecord", "debug_report", "format_debug_report",
    "list_examples", "get_example", "example_cases",
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
__version__ = "0.2.1"
__all__ += ["__version__"]
