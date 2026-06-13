"""Native observability — traces, spans, sessions, scores (Langfuse-style).

A `Trace` is one request through an LLM app; it holds nested `Span`s
(retrieval, generation, …), `Score`s (DebugAI's diagnosis + evals), and rolled-up
latency / token / cost. Traces can be grouped into a session (a conversation).

    tracer = Tracer(sink=store.add_trace)
    with tracer.trace("support.answer", session_id="s1") as t:
        with t.span("retrieval", kind="retrieval") as s:
            s.output = chunks
        with t.span("generation", kind="generation", model="claude-haiku-4-5") as s:
            s.output = answer
            s.set_usage(prompt=120, completion=30)
        t.add_score("confidence", 0.95)
"""

from __future__ import annotations

import contextlib
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

# USD per 1M tokens (input, output). Prefix match; unknown models → 0 cost.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
    "claude-3-5-haiku": (0.80, 4.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.0),
    "gpt-4.1": (2.0, 8.0),
    "o4-mini": (1.10, 4.40),
}


def estimate_cost(model: str | None, prompt_tokens: int, completion_tokens: int) -> float:
    if not model:
        return 0.0
    price = None
    for prefix, p in MODEL_PRICES.items():
        if model.startswith(prefix):
            price = p
            break
    if price is None:
        return 0.0
    return round((prompt_tokens * price[0] + completion_tokens * price[1]) / 1_000_000, 6)


def _now_ms() -> float:
    return time.time() * 1000.0


@dataclass
class Score:
    name: str
    value: float | str | bool
    data_type: str = "numeric"   # numeric | categorical | boolean
    comment: str = ""
    source: str = "debugai"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Span:
    name: str
    kind: str = "span"           # retrieval | generation | tool | span
    start_ms: float = field(default_factory=_now_ms)
    end_ms: float | None = None
    input: Any = None
    output: Any = None
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    metadata: dict = field(default_factory=dict)
    _t0: float = field(default=0.0, repr=False)

    def set_usage(self, prompt: int = 0, completion: int = 0) -> None:
        self.prompt_tokens, self.completion_tokens = prompt, completion

    def end(self) -> None:
        if self.end_ms is None:
            self.end_ms = _now_ms()

    @property
    def duration_ms(self) -> float:
        if self.end_ms is None:
            return 0.0
        return round(self.end_ms - self.start_ms, 2)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "kind": self.kind,
            "start_ms": self.start_ms, "end_ms": self.end_ms,
            "duration_ms": self.duration_ms,
            "input": _trim(self.input), "output": _trim(self.output),
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "metadata": self.metadata,
        }


@dataclass
class Trace:
    name: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    session_id: str | None = None
    start_ms: float = field(default_factory=_now_ms)
    end_ms: float | None = None
    spans: list[Span] = field(default_factory=list)
    scores: list[Score] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    status: str = "ok"            # ok | failing | error
    model: str | None = None
    diagnosis: dict | None = None
    timestamp: str | None = None

    # --- building ---
    @contextlib.contextmanager
    def span(self, name: str, kind: str = "span", model: str | None = None):
        s = Span(name=name, kind=kind, model=model)
        try:
            yield s
        finally:
            s.end()
            self.spans.append(s)

    def add_span(self, span: Span) -> None:
        if span.end_ms is None:
            span.end()
        self.spans.append(span)

    def add_score(self, name: str, value, data_type: str = "numeric", comment: str = "") -> None:
        self.scores.append(Score(name=name, value=value, data_type=data_type, comment=comment))

    def end(self) -> None:
        if self.end_ms is None:
            self.end_ms = _now_ms()

    # --- rollups ---
    @property
    def duration_ms(self) -> float:
        if self.end_ms is None:
            return round(max((s.end_ms or s.start_ms for s in self.spans), default=self.start_ms) - self.start_ms, 2)
        return round(self.end_ms - self.start_ms, 2)

    @property
    def prompt_tokens(self) -> int:
        return sum(s.prompt_tokens for s in self.spans)

    @property
    def completion_tokens(self) -> int:
        return sum(s.completion_tokens for s in self.spans)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cost_usd(self) -> float:
        total = 0.0
        for s in self.spans:
            total += estimate_cost(s.model or self.model, s.prompt_tokens, s.completion_tokens)
        return round(total, 6)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "session_id": self.session_id,
            "timestamp": self.timestamp, "status": self.status, "model": self.model,
            "start_ms": self.start_ms, "end_ms": self.end_ms,
            "duration_ms": self.duration_ms,
            "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens, "cost_usd": self.cost_usd,
            "spans": [s.to_dict() for s in self.spans],
            "scores": [s.to_dict() for s in self.scores],
            "metadata": self.metadata, "diagnosis": self.diagnosis,
        }


def scores_from_diagnosis(diagnosis: dict) -> list[Score]:
    """Attach a diagnosis to a trace as Langfuse-style scores."""
    if not diagnosis:
        return []
    healthy = bool(diagnosis.get("healthy"))
    scores = [Score(name="healthy", value=healthy, data_type="boolean")]
    primary = diagnosis.get("primary") or {}
    if not healthy and primary:
        scores.append(Score(name="failure", value=primary.get("failure", "unknown"),
                            data_type="categorical"))
        scores.append(Score(name="confidence", value=primary.get("confidence", 0.0),
                            data_type="numeric", comment=primary.get("severity", "")))
    return scores


def status_from_diagnosis(diagnosis: dict) -> str:
    if not diagnosis:
        return "ok"
    return "ok" if diagnosis.get("healthy") else "failing"


def _trim(value: Any, limit: int = 600) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    if isinstance(value, list):
        return [_trim(v, limit) for v in value]
    return value


class Tracer:
    """Creates traces and hands finished ones to a sink callback."""

    def __init__(self, sink: Callable[[Trace], None] | None = None):
        self.sink = sink

    @contextlib.contextmanager
    def trace(self, name: str, session_id: str | None = None, model: str | None = None,
              metadata: dict | None = None):
        t = Trace(name=name, session_id=session_id, model=model, metadata=metadata or {})
        try:
            yield t
        finally:
            t.end()
            if self.sink is not None:
                self.sink(t)
