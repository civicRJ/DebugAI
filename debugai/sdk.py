"""Level 2 integration — the one-line SDK wrapper (Architecture §3.2).

    from debugai.sdk import wrap_llm
    client = wrap_llm(OpenAI())          # or wrap_llm(Anthropic())
    resp = client.chat.completions.create(...)   # unchanged call site

``wrap_llm`` returns a transparent proxy: every attribute access forwards to the
real client untouched *except* the terminal ``create`` call, which is
instrumented. After the real call returns, a CaptureRecord is built and handed
to a background worker for diagnosis — so the user's request is never blocked
(the only added latency is cheap dict-building, well under the 10ms budget).

Retrieval context (chunks + similarity scores) isn't visible from the LLM call
itself, so attach it either with the ``retrieval_context`` context manager or
by passing ``debugai_chunks`` / ``debugai_similarity_scores`` kwargs to
``create`` (popped before the call is forwarded).
"""

from __future__ import annotations

import atexit
import contextlib
import contextvars
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from debugai.analyze import analyze
from debugai.thresholds import DEFAULT_THRESHOLDS, Thresholds
from debugai.tracing import Span, Trace, scores_from_diagnosis, status_from_diagnosis

log = logging.getLogger("debugai.sdk")

# Per-context retrieval payload set by retrieval_context() (thread/async safe).
_retrieval: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "debugai_retrieval", default=None
)
# Per-context session id set by session() (groups traces into a conversation).
_session: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "debugai_session", default=None
)


@contextlib.contextmanager
def session(session_id: str):
    """Group all wrapped LLM calls made inside the block into one session."""
    token = _session.set(session_id)
    try:
        yield
    finally:
        _session.reset(token)


@contextlib.contextmanager
def retrieval_context(chunks: list[str], similarity_scores: list[float] | None = None,
                      retrieval_query: str | None = None):
    """Attach RAG context to any wrapped LLM calls made inside the block."""
    token = _retrieval.set(
        {
            "retrieved_chunks": list(chunks or []),
            "similarity_scores": list(similarity_scores or []),
            "retrieval_query": retrieval_query,
        }
    )
    try:
        yield
    finally:
        _retrieval.reset(token)


# --------------------------------------------------------------------------- #
# Provider adapters (duck-typed so fakes work without the real SDKs installed)
# --------------------------------------------------------------------------- #
@dataclass
class _Captured:
    system_prompt: str = ""
    user_prompt: str = ""
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


def _msg_text(content) -> str:
    """Coerce a chat message's `content` (str, None, or a list of content parts)
    to plain text — the modern SDKs allow list/None, which would otherwise break
    the wrapper before the real LLM call runs."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict):
                out.append(part.get("text") or part.get("content") or "")
            elif isinstance(part, str):
                out.append(part)
        return " ".join(p for p in out if p)
    return str(content)


class _OpenAIAdapter:
    create_path = ("chat", "completions", "create")

    @staticmethod
    def matches(client: Any) -> bool:
        chat = getattr(client, "chat", None)
        comp = getattr(chat, "completions", None)
        return callable(getattr(comp, "create", None))

    @staticmethod
    def from_request(kwargs: dict) -> _Captured:
        msgs = kwargs.get("messages", []) or []
        system = " ".join(_msg_text(m.get("content")) for m in msgs if m.get("role") == "system")
        user = " ".join(_msg_text(m.get("content")) for m in msgs if m.get("role") == "user")
        return _Captured(
            system_prompt=system,
            user_prompt=user,
            model_name=kwargs.get("model"),
            temperature=kwargs.get("temperature"),
            max_tokens=kwargs.get("max_tokens"),
        )

    @staticmethod
    def from_response(resp: Any) -> tuple[str, dict]:
        try:
            text = resp.choices[0].message.content or ""
        except Exception:
            text = ""
        usage = {}
        u = getattr(resp, "usage", None)
        if u is not None:
            usage = {
                "prompt": getattr(u, "prompt_tokens", 0),
                "completion": getattr(u, "completion_tokens", 0),
                "total": getattr(u, "total_tokens", 0),
            }
        return text, usage


class _AnthropicAdapter:
    create_path = ("messages", "create")

    @staticmethod
    def matches(client: Any) -> bool:
        msgs = getattr(client, "messages", None)
        # Distinguish from OpenAI (which has .chat); Anthropic has no .chat.
        return callable(getattr(msgs, "create", None)) and not hasattr(client, "chat")

    @staticmethod
    def from_request(kwargs: dict) -> _Captured:
        system = kwargs.get("system", "") or ""
        msgs = kwargs.get("messages", []) or []
        user = " ".join(_msg_text(m.get("content")) for m in msgs if m.get("role") == "user")
        return _Captured(
            system_prompt=system if isinstance(system, str) else _msg_text(system),
            user_prompt=user,
            model_name=kwargs.get("model"),
            temperature=kwargs.get("temperature"),
            max_tokens=kwargs.get("max_tokens"),
        )

    @staticmethod
    def from_response(resp: Any) -> tuple[str, dict]:
        text = ""
        try:
            text = "".join(
                getattr(b, "text", "") for b in resp.content
                if getattr(b, "type", "") == "text"
            )
        except Exception:
            text = ""
        usage = {}
        u = getattr(resp, "usage", None)
        if u is not None:
            inp = getattr(u, "input_tokens", 0)
            out = getattr(u, "output_tokens", 0)
            usage = {"prompt": inp, "completion": out, "total": inp + out}
        return text, usage


_ADAPTERS = [_OpenAIAdapter, _AnthropicAdapter]


def _detect_adapter(client: Any):
    for adapter in _ADAPTERS:
        if adapter.matches(client):
            return adapter
    raise TypeError(
        "wrap_llm: unrecognised client. Expected an OpenAI "
        "(.chat.completions.create) or Anthropic (.messages.create) client."
    )


# --------------------------------------------------------------------------- #
# Background diagnosis worker (async + batching, §5 step 'Async + batching')
# --------------------------------------------------------------------------- #
@dataclass
class _Job:
    captured: _Captured
    output: str
    usage: dict
    latency_ms: int
    retrieval: dict | None
    context_window: int | None
    session_id: str | None = None


class _Diagnoser:
    """Single daemon worker that drains a queue and runs diagnosis off the
    request path. Batching keeps the worker from thrashing on bursty traffic."""

    def __init__(self, on_diagnosis: Callable | None, explain_with_llm: bool,
                 thresholds: Thresholds, batch_size: int = 16,
                 on_trace: Callable | None = None):
        self._q: queue.Queue = queue.Queue()
        self._on_diagnosis = on_diagnosis
        self._on_trace = on_trace
        self._explain = explain_with_llm
        self._thresholds = thresholds
        self._batch = batch_size
        self.recent: list[dict] = []
        self.recent_traces: list[dict] = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        atexit.register(self.flush)

    def submit(self, job: _Job) -> None:
        self._q.put(job)

    def _run(self) -> None:
        while True:
            job = self._q.get()
            if job is None:  # shutdown sentinel
                self._q.task_done()
                break
            try:
                self._process(job)
            except Exception as e:  # never let the worker die
                log.warning("diagnosis failed: %s", e)
            finally:
                self._q.task_done()

    def _process(self, job: _Job) -> None:
        r = job.retrieval or {}
        result = analyze(
            prompt=job.captured.user_prompt,
            output=job.output,
            system_prompt=job.captured.system_prompt,
            chunks=r.get("retrieved_chunks"),
            similarity_scores=r.get("similarity_scores"),
            retrieval_query=r.get("retrieval_query"),
            model_name=job.captured.model_name,
            temperature=job.captured.temperature,
            max_tokens=job.captured.max_tokens,
            context_window=job.context_window,
            latency_ms=job.latency_ms,
            token_usage=job.usage,
            thresholds=self._thresholds,
            explain_with_llm=self._explain,
            lazy=True,  # fail open: skip expensive signals for healthy traffic
        )
        with self._lock:
            self.recent.append(result)
            del self.recent[:-200]  # cap memory
        if self._on_diagnosis is not None:
            self._on_diagnosis(result)

        trace = self._build_trace(job, result)
        with self._lock:
            self.recent_traces.append(trace.to_dict())
            del self.recent_traces[:-200]
        if self._on_trace is not None:
            self._on_trace(trace)

    def _build_trace(self, job: _Job, result: dict) -> Trace:
        """Turn a captured call + its diagnosis into an observability trace."""
        t = Trace(name="llm.call", session_id=job.session_id, model=job.captured.model_name)
        r = job.retrieval or {}
        if r.get("retrieved_chunks"):
            sp = Span(name="retrieval", kind="retrieval")
            sp.input = r.get("retrieval_query")
            sp.output = r.get("retrieved_chunks")
            sp.metadata = {"similarity_scores": r.get("similarity_scores")}
            sp.end_ms = sp.start_ms  # retrieval timing not captured by the LLM wrapper
            t.add_span(sp)
        gen = Span(name="generation", kind="generation", model=job.captured.model_name)
        gen.input = job.captured.user_prompt
        gen.output = job.output
        gen.set_usage(prompt=(job.usage or {}).get("prompt", 0),
                      completion=(job.usage or {}).get("completion", 0))
        gen.end_ms = gen.start_ms + float(job.latency_ms or 0)
        t.add_span(gen)
        t.diagnosis = result
        t.scores = scores_from_diagnosis(result)
        t.status = status_from_diagnosis(result)
        t.end()
        return t

    def flush(self) -> None:
        """Block until all queued jobs are processed (used in tests / shutdown)."""
        self._q.join()


# --------------------------------------------------------------------------- #
# Transparent proxy
# --------------------------------------------------------------------------- #
class _PathProxy:
    """Forwards attribute access to ``target`` until the configured create path
    is reached, where it returns the instrumented callable instead."""

    def __init__(self, target: Any, path: tuple[str, ...], instrumented: Callable):
        object.__setattr__(self, "_t", target)
        object.__setattr__(self, "_path", path)
        object.__setattr__(self, "_instrumented", instrumented)

    def __getattr__(self, name: str) -> Any:
        path = object.__getattribute__(self, "_path")
        target = object.__getattribute__(self, "_t")
        attr = getattr(target, name)
        if path and name == path[0]:
            if len(path) == 1:  # this is the terminal create() method
                return object.__getattribute__(self, "_instrumented")
            return _PathProxy(attr, path[1:], object.__getattribute__(self, "_instrumented"))
        return attr  # forward everything else untouched

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(object.__getattribute__(self, "_t"), name, value)


def wrap_llm(
    client: Any,
    *,
    on_diagnosis: Callable | None = None,
    on_trace: Callable | None = None,
    session_id: str | None = None,
    explain_with_llm: bool = False,
    context_window: int | None = None,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    sample_rate: float = 1.0,
) -> Any:
    """Wrap an OpenAI/Anthropic client so every ``create`` call is auto-diagnosed
    and auto-traced.

    Drop-in replacement: call sites don't change. ``on_diagnosis`` receives each
    diagnosis dict; ``on_trace`` receives each observability Trace (or inspect
    ``client.debugai.recent`` / ``client.debugai.recent_traces``). Work runs in a
    background thread, so the wrapped call adds only microseconds. ``session_id``
    groups calls into a conversation (override per-call with the ``session``
    context manager).
    """
    adapter = _detect_adapter(client)
    diagnoser = _Diagnoser(on_diagnosis, explain_with_llm, thresholds, on_trace=on_trace)
    real_create = _resolve(client, adapter.create_path)

    # deterministic per-call sampling without Math.random (count-based)
    counter = {"n": 0}

    def instrumented(*args, **kwargs):
        # Pop DebugAI-only kwargs so they never reach the real SDK.
        chunks = kwargs.pop("debugai_chunks", None)
        scores = kwargs.pop("debugai_similarity_scores", None)
        rquery = kwargs.pop("debugai_retrieval_query", None)

        captured = adapter.from_request(kwargs)
        start = time.perf_counter()
        resp = real_create(*args, **kwargs)
        latency_ms = int((time.perf_counter() - start) * 1000)

        counter["n"] += 1
        sampled = sample_rate >= 1.0 or (counter["n"] * sample_rate) % 1 < sample_rate
        if sampled:
            output, usage = adapter.from_response(resp)
            retrieval = _retrieval.get()
            if chunks is not None:
                retrieval = {
                    "retrieved_chunks": list(chunks),
                    "similarity_scores": list(scores or []),
                    "retrieval_query": rquery,
                }
            diagnoser.submit(_Job(
                captured=captured, output=output, usage=usage,
                latency_ms=latency_ms, retrieval=retrieval,
                context_window=context_window,
                session_id=_session.get() or session_id,
            ))
        return resp

    proxy = _PathProxy(client, adapter.create_path, instrumented)
    # Expose the diagnoser for inspection / flush without colliding with client attrs.
    object.__setattr__(proxy, "debugai", diagnoser)
    return proxy


def _resolve(obj: Any, path: tuple[str, ...]) -> Any:
    for seg in path:
        obj = getattr(obj, seg)
    return obj


def http_trace_sink(url: str, token: str | None = None, timeout: float = 5.0) -> Callable:
    """An ``on_trace`` sink that POSTs each trace to a DebugAI server.

        client = wrap_llm(OpenAI(), on_trace=http_trace_sink(
            "http://localhost:8000/api/traces", token="dbg_..."))

    ``token`` is a per-account API token (Account → API tokens). Failures are
    logged, never raised, so tracing never breaks the app. Uses stdlib only.
    """
    import json as _json
    import urllib.request

    def sink(trace) -> None:
        payload = trace.to_dict() if hasattr(trace, "to_dict") else trace
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-API-Key"] = token
        req = urllib.request.Request(url, data=_json.dumps(payload).encode(),
                                     headers=headers, method="POST")
        try:
            urllib.request.urlopen(req, timeout=timeout).read()
        except Exception as e:  # pragma: no cover - network dependent
            log.warning("http_trace_sink: failed to post trace (%s)", e)

    return sink
