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
from debugai.sdk import wrap_llm, retrieval_context, session, http_trace_sink
from debugai.tracing import Trace, Span, Tracer, Score

__all__ = [
    "analyze", "CaptureRecord", "wrap_llm", "retrieval_context", "session",
    "http_trace_sink", "Trace", "Span", "Tracer", "Score",
]
__version__ = "0.1.0"
