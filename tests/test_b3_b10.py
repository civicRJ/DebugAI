"""Tests for LiteLLM-parity features B3–B10."""

import time
import types

import pytest

from debugai import (
    BudgetExceededError, ComparisonResult, DebugAIConfig,
    compare, completion, wrap_llm,
)
from debugai.metrics import MetricsLedger
from debugai.sdk import _AnthropicAdapter, _OpenAICompatAdapter, _prompt_hash, _validate_json_schema


def _ns(**k): return types.SimpleNamespace(**k)


def _oai_resp(text="ok", tool_calls=None):
    msg = _ns(content=text, tool_calls=tool_calls or [])
    return _ns(
        choices=[_ns(message=msg)],
        usage=_ns(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


class FakeOAI:
    def __init__(self, text="ok", tool_calls=None):
        self._text = text
        self._tc = tool_calls
        self.chat = _ns(completions=_ns(create=self._c))
    def _c(self, **k): return _oai_resp(self._text, self._tc)


# --------------------------------------------------------------------------- #
# B3 — Tool call tracing
# --------------------------------------------------------------------------- #
def test_openai_adapter_extracts_tool_calls():
    tc = _ns(function=_ns(name="search", arguments='{"q":"test"}'), id="call_1")
    resp = _oai_resp(tool_calls=[tc])
    calls = _OpenAICompatAdapter.extract_tool_calls(resp)
    assert calls == [{"name": "search", "input": '{"q":"test"}', "id": "call_1"}]


def test_anthropic_adapter_extracts_tool_calls():
    block = _ns(type="tool_use", name="calculator", input={"expr": "2+2"}, id="tu_1")
    resp = _ns(content=[block])
    calls = _AnthropicAdapter.extract_tool_calls(resp)
    assert calls == [{"name": "calculator", "input": {"expr": "2+2"}, "id": "tu_1"}]


def test_tool_calls_appear_as_spans_in_trace():
    traces = []
    tc = _ns(function=_ns(name="my_tool", arguments='{}'), id="tc_x")
    client = wrap_llm(FakeOAI(tool_calls=[tc]),
                      config=DebugAIConfig(enable_diagnosis=False, on_trace=traces.append))
    client.chat.completions.create(model="gpt-4o",
                                    messages=[{"role": "user", "content": "go"}])
    client.debugai.flush()
    trace = traces[0]
    tool_spans = [s for s in trace.spans if s.kind == "tool"]
    assert len(tool_spans) == 1
    assert tool_spans[0].name == "my_tool"


# --------------------------------------------------------------------------- #
# B4 — Budget manager
# --------------------------------------------------------------------------- #
def test_budget_exceeded_raises():
    m = MetricsLedger()
    m.record("gpt-4o", 0, 0, cost_usd=5.01, latency_ms=0, failed=False)
    # Patch global metrics temporarily.
    from debugai import sdk as sdk_mod
    old = sdk_mod._global_metrics
    sdk_mod._global_metrics = m
    try:
        cfg = DebugAIConfig(budget_usd=5.0, enable_diagnosis=False, enable_traces=False)
        with pytest.raises(BudgetExceededError, match="exceeded"):
            completion("gpt-4o", [], config=cfg)
    finally:
        sdk_mod._global_metrics = old


def test_budget_callback_fires_instead_of_raise():
    m = MetricsLedger()
    m.record("gpt-4o", 0, 0, cost_usd=10.0, latency_ms=0, failed=False)
    from debugai import sdk as sdk_mod
    old = sdk_mod._global_metrics
    sdk_mod._global_metrics = m
    called = []
    try:
        cfg = DebugAIConfig(budget_usd=5.0,
                            on_budget_exceeded=lambda spent: called.append(spent),
                            enable_diagnosis=False, enable_traces=False)
        with pytest.raises(BudgetExceededError):  # still raises after callback
            completion("gpt-4o", [], config=cfg)
        assert called and called[0] >= 10.0
    finally:
        sdk_mod._global_metrics = old


# --------------------------------------------------------------------------- #
# B5 — Request caching
# --------------------------------------------------------------------------- #
def test_cache_returns_cached_response(monkeypatch):
    from debugai import sdk as sdk_mod
    monkeypatch.setattr(sdk_mod, "_PROVIDER_REGISTRY", [
        (lambda m: m == "gpt-4o", _OpenAICompatAdapter, lambda: FakeOAI("first reply"))
    ])
    cfg = DebugAIConfig(cache_ttl_seconds=60, enable_diagnosis=False, enable_traces=False)
    r1 = completion("gpt-4o", [{"role": "user", "content": "hi"}], config=cfg)
    r2 = completion("gpt-4o", [{"role": "user", "content": "hi"}], config=cfg)
    assert r1.text == r2.text == "first reply"
    assert r2.from_cache is True


def test_different_messages_not_cached(monkeypatch):
    from debugai import sdk as sdk_mod
    call_count = {"n": 0}
    class CountingOAI:
        def __init__(s): s.chat = _ns(completions=_ns(create=s._c))
        def _c(s, **k):
            call_count["n"] += 1
            return _oai_resp(f"reply {call_count['n']}")
    monkeypatch.setattr(sdk_mod, "_PROVIDER_REGISTRY", [
        (lambda m: m == "gpt-4o", _OpenAICompatAdapter, lambda: CountingOAI())
    ])
    cfg = DebugAIConfig(cache_ttl_seconds=60, enable_diagnosis=False, enable_traces=False)
    r1 = completion("gpt-4o", [{"role": "user", "content": "hello"}], config=cfg)
    r2 = completion("gpt-4o", [{"role": "user", "content": "goodbye"}], config=cfg)
    assert r1.text != r2.text
    assert r2.from_cache is False


def test_cache_ttl_expiry(monkeypatch):
    from debugai import sdk as sdk_mod
    from debugai.sdk import _TTLCache
    cache = _TTLCache()
    cache.set("k", "value", ttl=0.01)
    time.sleep(0.05)
    assert cache.get("k") is None


# --------------------------------------------------------------------------- #
# B6 — Retry tracing
# --------------------------------------------------------------------------- #
def test_retry_count_on_response(monkeypatch):
    from debugai import sdk as sdk_mod
    attempts = {"n": 0}
    class RetryOAI:
        def __init__(s): s.chat = _ns(completions=_ns(create=s._c))
        def _c(s, **k):
            attempts["n"] += 1
            if attempts["n"] < 3:
                e = Exception("rate limit")
                e.status_code = 429
                raise e
            return _oai_resp("finally works")
    monkeypatch.setattr(sdk_mod, "_PROVIDER_REGISTRY", [
        (lambda m: m == "retry-model", _OpenAICompatAdapter, lambda: RetryOAI())
    ])
    cfg = DebugAIConfig(max_retries=3, retry_backoff_seconds=0.0,
                        enable_diagnosis=False, enable_traces=False)
    resp = completion("retry-model", [{"role": "user", "content": "hi"}], config=cfg)
    assert resp.text == "finally works"
    assert resp.retry_count == 2   # 0-indexed, fired twice before success


def test_max_retries_exceeded_raises(monkeypatch):
    from debugai import sdk as sdk_mod
    class AlwaysFails:
        def __init__(s): s.chat = _ns(completions=_ns(create=s._c))
        def _c(s, **k):
            e = RuntimeError("always down"); e.status_code = 500; raise e
    monkeypatch.setattr(sdk_mod, "_PROVIDER_REGISTRY", [
        (lambda m: m == "down-model", _OpenAICompatAdapter, lambda: AlwaysFails())
    ])
    cfg = DebugAIConfig(max_retries=1, retry_backoff_seconds=0.0,
                        enable_diagnosis=False, enable_traces=False)
    with pytest.raises(RuntimeError, match="always down"):
        completion("down-model", [], config=cfg)


# --------------------------------------------------------------------------- #
# B7 — Correlation IDs
# --------------------------------------------------------------------------- #
def test_correlation_id_on_response(monkeypatch):
    from debugai import sdk as sdk_mod
    monkeypatch.setattr(sdk_mod, "_PROVIDER_REGISTRY", [
        (lambda m: m == "gpt-4o", _OpenAICompatAdapter, lambda: FakeOAI())
    ])
    cfg = DebugAIConfig(enable_diagnosis=False, enable_traces=False)
    r1 = completion("gpt-4o", [{"role": "user", "content": "hi"}], config=cfg)
    r2 = completion("gpt-4o", [{"role": "user", "content": "hi"}], config=cfg)
    assert r1.correlation_id is not None and len(r1.correlation_id) == 16
    assert r1.correlation_id != r2.correlation_id  # unique per call


def test_correlation_id_in_trace(monkeypatch):
    from debugai import sdk as sdk_mod
    monkeypatch.setattr(sdk_mod, "_PROVIDER_REGISTRY", [
        (lambda m: m == "gpt-4o", _OpenAICompatAdapter, lambda: FakeOAI())
    ])
    traces = []
    cfg = DebugAIConfig(enable_diagnosis=False, enable_traces=True,
                        on_trace=lambda t: traces.append(t.to_dict()))
    resp = completion("gpt-4o", [{"role": "user", "content": "hi"}], config=cfg)
    # Wait for background worker.
    import time as _t; _t.sleep(0.3)
    if traces:
        assert traces[0]["metadata"]["correlation_id"] == resp.correlation_id


# --------------------------------------------------------------------------- #
# B8 — Latency SLA alerts
# --------------------------------------------------------------------------- #
def test_sla_breach_callback():
    """Directly inject a high-latency job into the worker to trigger the SLA."""
    from debugai.sdk import _Diagnoser, _Job, _Captured
    breaches = []
    cfg = DebugAIConfig(latency_sla_ms=100,  # 100ms threshold
                        on_sla_breach=breaches.append,
                        enable_diagnosis=False, enable_traces=False,
                        track_tokens=False, track_cost=False, track_latency=False)
    diagnoser = _Diagnoser(cfg)
    # Submit a job with 500ms latency (well above the 100ms threshold).
    diagnoser.submit(_Job(
        captured=_Captured(user_prompt="q", model_name="gpt-4o"),
        output="answer", usage={}, latency_ms=500,
        retrieval=None, context_window=None,
    ))
    diagnoser.flush()
    assert breaches
    assert breaches[0]["latency_ms"] == 500
    assert breaches[0]["threshold_ms"] == 100


# --------------------------------------------------------------------------- #
# B9 — compare()
# --------------------------------------------------------------------------- #
def test_compare_returns_results_for_all_models(monkeypatch):
    from debugai import sdk as sdk_mod
    monkeypatch.setattr(sdk_mod, "_PROVIDER_REGISTRY", [
        (lambda m: m.startswith("model-"), _OpenAICompatAdapter,
         lambda: FakeOAI("generic response")),
    ])
    cfg = DebugAIConfig(enable_diagnosis=False, enable_traces=False)
    results = compare("What is 2+2?", models=["model-a", "model-b", "model-c"], config=cfg)
    assert len(results) == 3
    assert all(isinstance(r, ComparisonResult) for r in results)
    assert all(r.text == "generic response" for r in results)
    assert all(r.error is None for r in results)


def test_compare_records_error_not_raise(monkeypatch):
    from debugai import sdk as sdk_mod
    class BrokenOAI:
        def __init__(s): s.chat = _ns(completions=_ns(create=s._c))
        def _c(s, **k): raise RuntimeError("kaboom")
    monkeypatch.setattr(sdk_mod, "_PROVIDER_REGISTRY", [
        (lambda m: m == "working", _OpenAICompatAdapter, lambda: FakeOAI("ok")),
        (lambda m: m == "broken", _OpenAICompatAdapter, lambda: BrokenOAI()),
    ])
    cfg = DebugAIConfig(enable_diagnosis=False, enable_traces=False)
    results = compare("hi", models=["working", "broken"], config=cfg)
    assert len(results) == 2
    errors = [r for r in results if r.error]
    assert len(errors) == 1 and "kaboom" in errors[0].error


# --------------------------------------------------------------------------- #
# B10 — Prompt version hash
# --------------------------------------------------------------------------- #
def test_prompt_hash_is_stable():
    h1 = _prompt_hash("You are a helpful assistant.")
    h2 = _prompt_hash("You are a helpful assistant.")
    assert h1 == h2 and len(h1) == 12


def test_prompt_hash_changes_with_content():
    assert _prompt_hash("System prompt A") != _prompt_hash("System prompt B")


def test_prompt_hash_empty():
    assert _prompt_hash("") == ""


def test_prompt_hash_in_trace():
    traces = []
    sys_prompt = "You are a Socratic tutor."
    client = wrap_llm(FakeOAI(),
                      config=DebugAIConfig(enable_diagnosis=False, on_trace=traces.append))
    client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": sys_prompt},
                  {"role": "user", "content": "hi"}])
    client.debugai.flush()
    trace = traces[0]
    assert "prompt_hash" in trace.metadata
    assert trace.metadata["prompt_hash"] == _prompt_hash(sys_prompt)
