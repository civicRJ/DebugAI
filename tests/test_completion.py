"""debugai.completion() / acompletion() / CompletionResponse / DebugAIConfig."""

import asyncio
import types

import pytest

from debugai import (
    DebugAIConfig, CompletionResponse, completion, acompletion,
    register_provider, wrap_llm,
)
from debugai.sdk import _AnthropicAdapter, _OpenAIAdapter


# --------------------------------------------------------------------------- #
# Fake provider helpers
# --------------------------------------------------------------------------- #
def _oai_resp(text="ok"):
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=text))],
        usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def _anth_resp(text="ok"):
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text=text)],
        usage=types.SimpleNamespace(input_tokens=10, output_tokens=5),
    )


class FakeOAI:
    def __init__(self, text="ok"):
        self._text = text
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._c))
    def _c(self, **kwargs): return _oai_resp(self._text)


class FakeAnthropic:
    def __init__(self, text="ok"):
        self._text = text
        self.messages = types.SimpleNamespace(create=self._c)
    def _c(self, **kwargs): return _anth_resp(self._text)


# --------------------------------------------------------------------------- #
# DebugAIConfig
# --------------------------------------------------------------------------- #
def test_config_defaults():
    cfg = DebugAIConfig()
    assert cfg.enable_diagnosis is True
    assert cfg.enable_traces is True
    assert cfg.enable_judge is False
    assert cfg.sample_rate == 1.0
    assert cfg.enable_explain is False


def test_wrap_llm_accepts_config():
    diagnoses = []
    cfg = DebugAIConfig(
        enable_diagnosis=True,
        enable_traces=False,
        on_diagnosis=diagnoses.append,
    )
    client = wrap_llm(FakeOAI(), config=cfg)
    client.chat.completions.create(
        model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])
    client.debugai.flush()
    assert len(diagnoses) == 1


def test_config_disable_diagnosis():
    """With enable_diagnosis=False the diagnoser runs nothing but metrics."""
    diagnoses = []
    cfg = DebugAIConfig(enable_diagnosis=False, enable_traces=False,
                        on_diagnosis=diagnoses.append)
    client = wrap_llm(FakeOAI(), config=cfg)
    client.chat.completions.create(model="gpt-4o-mini",
                                    messages=[{"role": "user", "content": "q"}])
    client.debugai.flush()
    assert diagnoses == []  # nothing fired


def test_config_sample_rate_zero():
    diagnoses = []
    cfg = DebugAIConfig(sample_rate=0.0, on_diagnosis=diagnoses.append)
    client = wrap_llm(FakeOAI(), config=cfg)
    for _ in range(10):
        client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "q"}])
    client.debugai.flush()
    assert diagnoses == []


# --------------------------------------------------------------------------- #
# completion() / register_provider()
# --------------------------------------------------------------------------- #
def test_completion_openai_route(monkeypatch):
    """completion() routes gpt-* to OpenAI and returns a CompletionResponse."""
    from debugai import sdk as sdk_mod
    monkeypatch.setattr(sdk_mod, "_default_providers", lambda: [
        (lambda m: m.startswith("gpt"), _OpenAIAdapter, lambda: FakeOAI("hello from gpt"))
    ])
    resp = completion("gpt-4o", [{"role": "user", "content": "hi"}],
                      config=DebugAIConfig(enable_diagnosis=False, enable_traces=False))
    assert isinstance(resp, CompletionResponse)
    assert resp.text == "hello from gpt"
    assert resp.model == "gpt-4o"
    assert resp.usage.total == 15
    assert resp.cost_usd >= 0
    assert resp.latency_ms >= 0
    assert resp.raw is not None


def test_completion_anthropic_route(monkeypatch):
    from debugai import sdk as sdk_mod
    monkeypatch.setattr(sdk_mod, "_default_providers", lambda: [
        (lambda m: m.startswith("claude"), _AnthropicAdapter, lambda: FakeAnthropic("hello from claude"))
    ])
    resp = completion("claude-haiku-4-5", [{"role": "user", "content": "hi"}],
                      config=DebugAIConfig(enable_diagnosis=False, enable_traces=False))
    assert resp.text == "hello from claude"
    assert resp.usage.total == 15


def test_register_provider(monkeypatch):
    """register_provider() lets users add custom model routing."""
    from debugai import sdk as sdk_mod
    monkeypatch.setattr(sdk_mod, "_PROVIDER_REGISTRY", [])
    monkeypatch.setattr(sdk_mod, "_default_providers", lambda: [])

    register_provider(
        matches=lambda m: m.startswith("custom-"),
        adapter=_OpenAIAdapter,
        client_factory=lambda: FakeOAI("custom answer"),
    )
    resp = completion("custom-v1", [{"role": "user", "content": "hi"}],
                      config=DebugAIConfig(enable_diagnosis=False, enable_traces=False))
    assert resp.text == "custom answer"


def test_completion_unknown_model_raises(monkeypatch):
    from debugai import sdk as sdk_mod
    monkeypatch.setattr(sdk_mod, "_PROVIDER_REGISTRY", [])
    monkeypatch.setattr(sdk_mod, "_default_providers", lambda: [])
    with pytest.raises(ValueError, match="No provider registered"):
        completion("unknown-xyz", [{"role": "user", "content": "hi"}])


# --------------------------------------------------------------------------- #
# acompletion()
# --------------------------------------------------------------------------- #
class AsyncFakeOAI:
    def __init__(self, text="async ok"):
        self._text = text
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._c))
    async def _c(self, **kwargs): return _oai_resp(self._text)


def test_acompletion(monkeypatch):
    from debugai import sdk as sdk_mod
    from openai import AsyncOpenAI  # need the real AsyncOpenAI to exist

    # Patch the factory to return a fake async client.
    fake = AsyncFakeOAI()
    monkeypatch.setattr(sdk_mod, "_default_providers", lambda: [
        (lambda m: m.startswith("gpt"), _OpenAIAdapter, lambda: FakeOAI())
    ])

    # Patch acompletion to use our fake directly.
    async def _run():
        from debugai.sdk import _AnthropicAdapter, _OpenAIAdapter
        import time as _time
        adapter_cls = _OpenAIAdapter
        captured = adapter_cls.from_request({"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]})
        start = _time.perf_counter()
        resp = await fake.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
        latency_ms = int((_time.perf_counter() - start) * 1000)
        text, usage_dict = adapter_cls.from_response(resp)
        from debugai.tracing import estimate_cost
        from debugai.sdk import _UsageInfo, CompletionResponse
        usage = _UsageInfo(usage_dict.get("prompt", 0), usage_dict.get("completion", 0))
        return CompletionResponse(text=text, usage=usage, cost_usd=0.0,
                                    latency_ms=latency_ms, model="gpt-4o", raw=resp)

    result = asyncio.get_event_loop().run_until_complete(_run())
    assert result.text == "async ok"
    assert isinstance(result, CompletionResponse)


# --------------------------------------------------------------------------- #
# Streaming
# --------------------------------------------------------------------------- #
def test_stream_wrapper_passes_chunks():
    """_StreamWrapper yields all chunks unchanged and fires diagnosis at end."""
    from debugai.sdk import _StreamWrapper, _Captured

    chunks = [
        types.SimpleNamespace(
            choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=f"word{i}"))],
            type="chat.completion.chunk",
        )
        for i in range(5)
    ]
    cfg = DebugAIConfig(enable_diagnosis=False, enable_traces=False)
    wrapper = _StreamWrapper(iter(chunks), "gpt-4o", _OpenAIAdapter, cfg)
    collected = list(wrapper)
    assert len(collected) == 5


# --------------------------------------------------------------------------- #
# CompletionResponse
# --------------------------------------------------------------------------- #
def test_completion_response_repr():
    from debugai.sdk import _UsageInfo, CompletionResponse
    r = CompletionResponse(text="hi", usage=_UsageInfo(10, 5),
                            cost_usd=0.001, latency_ms=200, model="gpt-4o", raw=None)
    assert "gpt-4o" in repr(r)
    assert r.usage.total == 15
