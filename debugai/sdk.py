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

import json as _json_mod

from debugai.analyze import analyze
from debugai.config import DebugAIConfig
from debugai.metrics import metrics as _global_metrics
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


class _OpenAICompatAdapter(_OpenAIAdapter):
    """Matches any OpenAI-API-compatible client: Azure, Groq, Together AI, Mistral,
    Ollama (Qwen, Llama, Phi, DeepSeek…), OpenRouter, LM Studio, vLLM.

    Identical create_path/from_request/from_response to _OpenAIAdapter.
    The difference is only in the base_url the client was constructed with."""
    create_path = ("chat", "completions", "create")

    @staticmethod
    def matches(client: Any) -> bool:
        return _OpenAIAdapter.matches(client) and not _AnthropicAdapter.matches(client)


# Backward-compat alias.
_GenericOpenAICompatAdapter = _OpenAICompatAdapter


class _CohereAdapter:
    """Native Cohere SDK adapter (ClientV2). Requires: pip install cohere"""

    create_path = ("chat",)

    @staticmethod
    def matches(client: Any) -> bool:
        return (callable(getattr(client, "chat", None)) and
                hasattr(client, "embed") and
                not hasattr(client, "messages"))

    @staticmethod
    def from_request(kwargs: dict) -> "_Captured":
        msgs = kwargs.get("messages") or []
        system = " ".join(m.get("message", m.get("content", "")) for m in msgs
                          if m.get("role", "").upper() in ("SYSTEM", "system"))
        user = " ".join(m.get("message", m.get("content", "")) for m in msgs
                        if m.get("role", "").upper() in ("USER", "user"))
        return _Captured(
            system_prompt=system,
            user_prompt=user,
            model_name=kwargs.get("model"),
            temperature=kwargs.get("temperature"),
            max_tokens=kwargs.get("max_tokens"),
        )

    @staticmethod
    def from_response(resp: Any) -> tuple[str, dict]:
        text = ""
        try:
            text = resp.message.content[0].text or ""
        except Exception:
            try:
                text = resp.text or ""
            except Exception:
                pass
        usage = {}
        try:
            u = resp.meta.tokens
            inp = getattr(u, "input_tokens", 0) or 0
            out = getattr(u, "output_tokens", 0) or 0
            usage = {"prompt": inp, "completion": out, "total": inp + out}
        except Exception:
            pass
        return text, usage


_ADAPTERS = [_AnthropicAdapter, _OpenAICompatAdapter, _OpenAIAdapter, _CohereAdapter]
_EXTRA_ADAPTERS: list = []


def register_adapter(adapter_class) -> None:
    """Register a custom adapter class for use with ``wrap_llm()``."""
    _EXTRA_ADAPTERS.insert(0, adapter_class)


def _detect_adapter(client: Any):
    for adapter in _EXTRA_ADAPTERS + _ADAPTERS:
        if adapter.matches(client):
            return adapter
    raise TypeError(
        "wrap_llm: unrecognised client. Supported: OpenAI-compatible clients "
        "(.chat.completions.create), Anthropic (.messages.create), Cohere (.chat + .embed). "
        "For custom providers use register_adapter() or register_provider()."
    )


def _validate_json_schema(output: str, schema: dict) -> list[str]:
    """Validate a JSON response against a JSON Schema dict. Returns a list of
    violation strings, or an empty list if valid. Stdlib only (no jsonschema pkg)."""
    if not schema:
        return []
    # Step 1: is it valid JSON?
    try:
        data = _json_mod.loads(output.strip())
    except _json_mod.JSONDecodeError as e:
        return [f"Output is not valid JSON: {e}"]
    violations = []
    # Step 2: basic type checking against the schema (no external dependency).
    schema_type = schema.get("type")
    if schema_type:
        type_map = {"object": dict, "array": list, "string": str,
                    "number": (int, float), "integer": int, "boolean": bool}
        expected = type_map.get(schema_type)
        if expected and not isinstance(data, expected):
            violations.append(
                f"Expected JSON {schema_type}, got {type(data).__name__}")
    # Step 3: check required properties.
    if isinstance(data, dict):
        for req in schema.get("required", []):
            if req not in data:
                violations.append(f"Missing required property: '{req}'")
        # Step 4: check property types.
        for prop, prop_schema in schema.get("properties", {}).items():
            if prop in data and isinstance(prop_schema, dict):
                ptype = prop_schema.get("type")
                type_map = {"string": str, "number": (int, float),
                            "integer": int, "boolean": bool, "array": list, "object": dict}
                expected = type_map.get(ptype)
                if expected and not isinstance(data[prop], expected):
                    violations.append(
                        f"Property '{prop}' should be {ptype}, got {type(data[prop]).__name__}")
    return violations


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
    request path. Configuration is read from a DebugAIConfig so the same
    worker respects enable_* flags, sampling, and sinks."""

    def __init__(self, config: DebugAIConfig,
                 # Legacy positional compat (on_diagnosis, explain_with_llm, thresholds)
                 on_diagnosis: Callable | None = None,
                 explain_with_llm: bool = False,
                 thresholds: Thresholds | None = None,
                 batch_size: int = 16,
                 on_trace: Callable | None = None):
        self._cfg = config
        # Legacy kwargs override the config so existing call-sites still work.
        if on_diagnosis is not None:
            self._cfg = DebugAIConfig(**{
                **self._cfg.__dict__,
                "on_diagnosis": on_diagnosis,
            })
        if on_trace is not None:
            self._cfg = DebugAIConfig(**{
                **self._cfg.__dict__,
                "on_trace": on_trace,
            })
        if thresholds is not None:
            self._cfg = DebugAIConfig(**{
                **self._cfg.__dict__,
                "thresholds": thresholds,
            })
        if explain_with_llm:
            self._cfg = DebugAIConfig(**{
                **self._cfg.__dict__,
                "enable_explain": True,
            })
        self._q: queue.Queue = queue.Queue(maxsize=config.max_queue_depth)
        self.recent: list[dict] = []
        self.recent_traces: list[dict] = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        atexit.register(self.flush)

    def submit(self, job: _Job) -> None:
        try:
            self._q.put_nowait(job)
        except queue.Full:
            log.debug("diagnosis queue full (depth %d); dropping job", self._cfg.max_queue_depth)

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
        cfg = self._cfg
        r = job.retrieval or {}

        result = None
        if cfg.enable_diagnosis:
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
                thresholds=cfg.thresholds,
                explain_with_llm=cfg.enable_explain,
                lazy=cfg.lazy,
            )
            with self._lock:
                self.recent.append(result)
                del self.recent[:-200]
            if cfg.on_diagnosis is not None:
                cfg.on_diagnosis(result)

        if cfg.enable_traces:
            trace = self._build_trace(job, result or {})
            with self._lock:
                self.recent_traces.append(trace.to_dict())
                del self.recent_traces[:-200]
            if cfg.on_trace is not None:
                cfg.on_trace(trace)
            if cfg.sink_url:
                _http_post_trace(trace.to_dict(), cfg.sink_url, cfg.sink_token)

        # Update global MetricsLedger after each request.
        if cfg.track_tokens or cfg.track_cost or cfg.track_latency:
            from debugai.tracing import estimate_cost
            usage = job.usage or {}
            prompt_t = usage.get("prompt", 0)
            compl_t = usage.get("completion", 0)
            cost = estimate_cost(job.captured.model_name, prompt_t, compl_t) if cfg.track_cost else 0.0
            failed = bool(result and not result.get("healthy"))
            _global_metrics.record(
                model=job.captured.model_name or "unknown",
                prompt_tokens=prompt_t if cfg.track_tokens else 0,
                completion_tokens=compl_t if cfg.track_tokens else 0,
                cost_usd=cost,
                latency_ms=float(job.latency_ms or 0),
                failed=failed,
            )
            if cfg.on_metrics is not None:
                cfg.on_metrics({
                    "model": job.captured.model_name,
                    "prompt_tokens": prompt_t,
                    "completion_tokens": compl_t,
                    "cost_usd": cost,
                    "latency_ms": job.latency_ms,
                    "failed": failed,
                })

        # B2: JSON schema validation (runs regardless of other diagnosis).
        if cfg.response_schema and job.output:
            violations = _validate_json_schema(job.output, cfg.response_schema)
            if violations:
                if cfg.on_schema_violation:
                    try:
                        cfg.on_schema_violation(job.output, violations)
                    except Exception as e:
                        log.warning("on_schema_violation callback failed: %s", e)

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


def _http_post_trace(trace_dict: dict, url: str, token: str | None) -> None:
    """Fire-and-forget HTTP POST for the sink_url option (stdlib only)."""
    import json as _json
    import urllib.request
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-API-Key"] = token
    req = urllib.request.Request(url, data=_json.dumps(trace_dict).encode(),
                                  headers=headers, method="POST")
    try:
        urllib.request.urlopen(req, timeout=5.0).read()
    except Exception as e:  # pragma: no cover - network dependent
        log.debug("sink_url POST failed (%s)", e)


def wrap_llm(
    client: Any,
    *,
    config: "DebugAIConfig | None" = None,
    # Legacy individual kwargs — still work for backward compatibility.
    on_diagnosis: Callable | None = None,
    on_trace: Callable | None = None,
    session_id: str | None = None,
    explain_with_llm: bool = False,
    context_window: int | None = None,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    sample_rate: float = 1.0,
) -> Any:
    """Wrap an OpenAI/Anthropic client so every ``create`` call is auto-diagnosed,
    auto-traced, and contributes to the metrics ledger.

    Drop-in replacement: call sites don't change. Pass a ``DebugAIConfig`` for full
    control, or use the individual legacy kwargs for backward compatibility.
    Work runs in a background thread — the wrapped call adds only microseconds.
    """
    # Build effective config: start from the provided config (or default),
    # then layer any explicit legacy kwargs on top.
    effective = config or DebugAIConfig(
        on_diagnosis=on_diagnosis,
        on_trace=on_trace,
        session_id=session_id,
        enable_explain=explain_with_llm,
        thresholds=thresholds,
        sample_rate=sample_rate,
    )
    # If individual kwargs provided alongside a config, they take precedence.
    if config is not None:
        overrides = {}
        if on_diagnosis is not None: overrides["on_diagnosis"] = on_diagnosis
        if on_trace is not None: overrides["on_trace"] = on_trace
        if session_id is not None: overrides["session_id"] = session_id
        if explain_with_llm: overrides["enable_explain"] = True
        if thresholds is not DEFAULT_THRESHOLDS: overrides["thresholds"] = thresholds
        if sample_rate != 1.0: overrides["sample_rate"] = sample_rate
        if overrides:
            import dataclasses
            effective = dataclasses.replace(effective, **overrides)

    adapter = _detect_adapter(client)
    diagnoser = _Diagnoser(effective)
    real_create = _resolve(client, adapter.create_path)
    _rate = effective.sample_rate
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
        sampled = _rate >= 1.0 or (counter["n"] * _rate) % 1 < _rate
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
                session_id=_session.get() or effective.session_id,
            ))
        return resp

    proxy = _PathProxy(client, adapter.create_path, instrumented)
    object.__setattr__(proxy, "debugai", diagnoser)
    return proxy


def _resolve(obj: Any, path: tuple[str, ...]) -> Any:
    for seg in path:
        obj = getattr(obj, seg)
    return obj


# --------------------------------------------------------------------------- #
# CompletionResponse — normalized thin wrapper around any provider's response
# --------------------------------------------------------------------------- #
class _UsageInfo:
    def __init__(self, prompt: int, completion: int):
        self.prompt = prompt
        self.completion = completion
        self.total = prompt + completion

    def __repr__(self):
        return f"Usage(prompt={self.prompt}, completion={self.completion})"


class CompletionResponse:
    """Normalized response from ``debugai.completion()`` / ``debugai.acompletion()``.

    Attributes:
        text        — extracted output text (works regardless of provider)
        usage       — token counts (prompt / completion / total)
        cost_usd    — estimated cost from the built-in pricing table
        latency_ms  — end-to-end measured latency
        model       — model name as returned by the provider
        raw         — the original native provider response (pass-through)
    """

    def __init__(self, text: str, usage: _UsageInfo, cost_usd: float,
                 latency_ms: int, model: str, raw: Any):
        self.text = text
        self.usage = usage
        self.cost_usd = cost_usd
        self.latency_ms = latency_ms
        self.model = model
        self.raw = raw
        self.fallback_attempts: list[tuple[str, str]] = []
        """List of (model, error) pairs for any fallback attempts before success."""

    def __repr__(self):
        return (f"CompletionResponse(model={self.model!r}, "
                f"tokens={self.usage.total}, cost=${self.cost_usd:.6f})")


# --------------------------------------------------------------------------- #
# Provider routing — maps model name prefix → (client factory, adapter)
# --------------------------------------------------------------------------- #
_PROVIDER_REGISTRY: list[tuple[Callable, "type[_OpenAIAdapter]", Callable]] = []
# Each entry: (matches_model_fn, adapter_class, client_factory_fn)


def _default_providers():
    """Backward-compat shim used by tests that monkeypatch this function.
    Real routing now goes through the PROVIDER_ROUTES table in providers.py."""
    from debugai.providers import PROVIDER_ROUTES, _ADAPTER_MAP

    entries = []
    for route in PROVIDER_ROUTES:
        r = route  # capture for closure
        adapter_cls = _ADAPTER_MAP.get(r.adapter, _OpenAICompatAdapter)
        entries.append((
            lambda m, pfx=r.prefix: m.lower().startswith(pfx.lower()),
            adapter_cls,
            lambda r=r: None,  # unused in new path
        ))
    return entries


def register_provider(
    matches: Callable[[str], bool],
    adapter,
    client_factory: Callable,
) -> None:
    """Register a custom provider so ``debugai.completion()`` can route to it.

        debugai.register_provider(
            matches=lambda m: m.startswith("my-model"),
            adapter=MyAdapter,
            client_factory=lambda: MyClient(...),
        )
    """
    _PROVIDER_REGISTRY.insert(0, (matches, adapter, client_factory))


def _route_provider(model: str, config: "DebugAIConfig | None" = None):
    """Return (adapter_class, client) for a model name.

    Checks, in order:
    1. User-registered entries via register_provider()
    2. The built-in PROVIDER_ROUTES table in providers.py
    """
    # 1. User-registered overrides.
    for matches, adapter, factory in _PROVIDER_REGISTRY:
        if matches(model):
            return adapter, factory()

    # 2. Built-in routing table.
    from debugai.providers import make_client, route_for
    route = route_for(model)
    if route is None:
        raise ValueError(
            f"No provider registered for model {model!r}. "
            "Supported prefixes: gpt-, claude-, gemini-, groq/, together/, "
            "mistral/, openrouter/, azure/, cohere/, ollama/, qwen*, llama*, "
            "phi*, deepseek*, gemma*, mixtral*. "
            "Or register your own: debugai.register_provider(...)."
        )
    from debugai.providers import _ADAPTER_MAP
    adapter_cls = _ADAPTER_MAP.get(route.adapter, _OpenAICompatAdapter)
    client = make_client(route, config or DebugAIConfig())
    return adapter_cls, client


# Module-level default config — used by completion() when no config is passed.
_default_config: "DebugAIConfig | None" = None


def set_default_config(config: "DebugAIConfig") -> None:
    """Set a module-level default config for all completion() calls."""
    global _default_config
    _default_config = config


def completion(model: str, messages: list, *, config: "DebugAIConfig | None" = None,
               **kwargs) -> CompletionResponse:
    """Universal LLM completion — works with any registered provider.

        import debugai
        resp = debugai.completion(model="gpt-4o", messages=[{"role":"user","content":"hi"}])
        print(resp.text, resp.cost_usd, resp.latency_ms)
    """
    cfg = config or _default_config or DebugAIConfig()
    adapter_cls, client = _route_provider(model, cfg)

    # Check for streaming — delegate to a different path if requested.
    if kwargs.get("stream"):
        return _stream_completion(model, messages, adapter_cls, client, cfg, kwargs)

    # Fallback loop: try the primary model, then each fallback on error.
    _fallbacks = list(cfg.fallbacks or [])
    _attempted: list[tuple[str, str]] = []  # (model_name, error)
    _model, _adapter, _client = model, adapter_cls, client
    while True:
        try:
            resp = _call_provider(_model, messages, _adapter, _client, kwargs)
            break
        except Exception as e:
            _attempted.append((_model, str(e)))
            log.warning("completion: %s failed (%s)", _model, e)
            if not _fallbacks:
                raise
            fallback_model = _fallbacks.pop(0)
            log.info("completion: trying fallback %s", fallback_model)
            _adapter, _client = _route_provider(fallback_model, cfg)
            _model = fallback_model

    latency_ms = int(resp._latency_ms)  # set by _call_provider
    text, usage_dict = _adapter.from_response(resp._raw)
    from debugai.tracing import estimate_cost
    usage = _UsageInfo(usage_dict.get("prompt", 0), usage_dict.get("completion", 0))
    cost = estimate_cost(_model, usage.prompt, usage.completion, cfg.model_prices)
    captured = _adapter.from_request({"model": _model, "messages": messages, **kwargs})

    # Background observability.
    if cfg.enable_diagnosis or cfg.enable_traces:
        diagnoser = _Diagnoser(cfg)
        diagnoser.submit(_Job(
            captured=captured, output=text, usage=usage_dict,
            latency_ms=latency_ms, retrieval=_retrieval.get(),
            context_window=None,
            session_id=_session.get() or cfg.session_id,
        ))

    result = CompletionResponse(text=text, usage=usage, cost_usd=cost,
                                 latency_ms=latency_ms, model=_model, raw=resp._raw)
    if _attempted:
        result.fallback_attempts = _attempted
    return result


class _RawResp:
    """Tiny wrapper carrying the raw response + measured latency out of _call_provider."""
    def __init__(self, raw, latency_ms: float):
        self._raw = raw
        self._latency_ms = latency_ms


def _call_provider(model: str, messages: list, adapter_cls, client, kwargs: dict) -> "_RawResp":
    """Single provider call, returning _RawResp(raw_response, latency_ms)."""
    kw = dict(kwargs)  # don't mutate caller's dict
    start = time.perf_counter()
    if adapter_cls is _AnthropicAdapter:
        raw = _resolve(client, adapter_cls.create_path)(
            model=model, messages=messages, max_tokens=kw.pop("max_tokens", 1024), **kw)
    else:
        raw = _resolve(client, adapter_cls.create_path)(
            model=model, messages=messages, **kw)
    return _RawResp(raw, (time.perf_counter() - start) * 1000)


def _stream_completion(model, messages, adapter_cls, client, cfg, kwargs):
    """Sync streaming: wrap the iterator so chunks pass through + diagnose at end."""
    create = _resolve(client, adapter_cls.create_path)
    if adapter_cls is _AnthropicAdapter:
        stream = create(model=model, messages=messages,
                        max_tokens=kwargs.pop("max_tokens", 1024), stream=True, **kwargs)
    else:
        stream = create(model=model, messages=messages, stream=True, **kwargs)
    return _StreamWrapper(stream, model, adapter_cls, cfg)


async def acompletion(model: str, messages: list, *, config: "DebugAIConfig | None" = None,
                      **kwargs) -> CompletionResponse:
    """Async variant of ``completion()``. Requires an async provider client."""
    import asyncio
    cfg = config or _default_config or DebugAIConfig()
    adapter_cls, _ = _route_provider(model, cfg)

    # Build an async client.
    if adapter_cls is _AnthropicAdapter:
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(timeout=60.0)
            acreate = client.messages.create
        except Exception:
            raise ImportError("anthropic[async] required for acompletion with Anthropic models.")
    else:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(timeout=60.0)
            acreate = client.chat.completions.create
        except Exception:
            raise ImportError("openai package required for acompletion with OpenAI models.")

    captured = adapter_cls.from_request({"model": model, "messages": messages, **kwargs})
    start = time.perf_counter()
    if adapter_cls is _AnthropicAdapter:
        resp = await acreate(model=model, messages=messages,
                              max_tokens=kwargs.pop("max_tokens", 1024), **kwargs)
    else:
        resp = await acreate(model=model, messages=messages, **kwargs)
    latency_ms = int((time.perf_counter() - start) * 1000)

    text, usage_dict = adapter_cls.from_response(resp)
    from debugai.tracing import estimate_cost
    usage = _UsageInfo(usage_dict.get("prompt", 0), usage_dict.get("completion", 0))
    cost = estimate_cost(model, usage.prompt, usage.completion)

    if cfg.enable_diagnosis or cfg.enable_traces:
        diagnoser = _Diagnoser(cfg)
        diagnoser.submit(_Job(
            captured=captured, output=text, usage=usage_dict,
            latency_ms=latency_ms, retrieval=_retrieval.get(),
            context_window=None,
            session_id=_session.get() or cfg.session_id,
        ))

    return CompletionResponse(text=text, usage=usage, cost_usd=cost,
                               latency_ms=latency_ms, model=model, raw=resp)


# --------------------------------------------------------------------------- #
# Streaming wrapper
# --------------------------------------------------------------------------- #
class _StreamWrapper:
    """Passes streaming chunks through unchanged, accumulates text, and fires
    a background diagnosis job after the last chunk is consumed."""

    def __init__(self, stream, model: str, adapter_cls, cfg: "DebugAIConfig"):
        self._stream = stream
        self._model = model
        self._adapter_cls = adapter_cls
        self._cfg = cfg
        self._buffer: list[str] = []
        self._usage: dict = {}

    def _extract_chunk_text(self, chunk) -> str:
        # OpenAI delta pattern
        try:
            return chunk.choices[0].delta.content or ""
        except Exception:
            pass
        # Anthropic content_block_delta pattern
        try:
            if getattr(chunk, "type", None) == "content_block_delta":
                return getattr(chunk.delta, "text", "") or ""
        except Exception:
            pass
        return ""

    def __iter__(self):
        return self

    def __next__(self):
        try:
            chunk = next(self._stream)
            self._buffer.append(self._extract_chunk_text(chunk))
            return chunk
        except StopIteration:
            self._finalize()
            raise

    def _finalize(self):
        if not (self._cfg.enable_diagnosis or self._cfg.enable_traces):
            return
        text = "".join(self._buffer)
        from debugai.signals import _approx_token_count
        completion_tokens = _approx_token_count(text)
        diagnoser = _Diagnoser(self._cfg)
        diagnoser.submit(_Job(
            captured=_Captured(user_prompt="(streamed)", model_name=self._model),
            output=text,
            usage={"prompt": 0, "completion": completion_tokens,
                   "total": completion_tokens},
            latency_ms=0,
            retrieval=_retrieval.get(),
            context_window=None,
            session_id=_session.get() or self._cfg.session_id,
        ))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def awrap_llm(
    async_client: Any,
    *,
    config: "DebugAIConfig | None" = None,
    on_diagnosis: Callable | None = None,
    on_trace: Callable | None = None,
    session_id: str | None = None,
    context_window: int | None = None,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    sample_rate: float = 1.0,
) -> Any:
    """Wrap an async OpenAI/Anthropic client (``AsyncOpenAI``, ``AsyncAnthropic``).

        from openai import AsyncOpenAI
        client = awrap_llm(AsyncOpenAI(), config=DebugAIConfig(sample_rate=0.5))
        resp = await client.chat.completions.create(model="gpt-4o", messages=[...])
    """
    effective = config or DebugAIConfig(
        on_diagnosis=on_diagnosis,
        on_trace=on_trace,
        session_id=session_id,
        thresholds=thresholds,
        sample_rate=sample_rate,
    )
    adapter = _detect_adapter(async_client)
    diagnoser = _Diagnoser(effective)
    real_create = _resolve(async_client, adapter.create_path)
    _rate = effective.sample_rate
    counter = {"n": 0}

    async def async_instrumented(*args, **kwargs):
        chunks = kwargs.pop("debugai_chunks", None)
        scores = kwargs.pop("debugai_similarity_scores", None)
        rquery = kwargs.pop("debugai_retrieval_query", None)

        captured = adapter.from_request(kwargs)
        start = time.perf_counter()
        resp = await real_create(*args, **kwargs)
        latency_ms = int((time.perf_counter() - start) * 1000)

        counter["n"] += 1
        sampled = _rate >= 1.0 or (counter["n"] * _rate) % 1 < _rate
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
                session_id=_session.get() or effective.session_id,
            ))
        return resp

    proxy = _PathProxy(async_client, adapter.create_path, async_instrumented)
    object.__setattr__(proxy, "debugai", diagnoser)
    return proxy


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
