"""Provider routing table + new adapters."""

import os
import types

import pytest

from debugai import DebugAIConfig, completion, register_provider
from debugai.providers import PROVIDER_ROUTES, make_client, route_for
from debugai.sdk import _AnthropicAdapter, _CohereAdapter, _OpenAICompatAdapter, _validate_json_schema


# ---------------------------------------------------------------------------
# Routing table
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("model,expected_name", [
    ("gpt-4o", "OpenAI"),
    ("gpt-4.1-mini", "OpenAI"),
    ("o1-mini", "OpenAI"),
    ("o4-mini", "OpenAI"),
    ("claude-haiku-4-5", "Anthropic"),
    ("claude-3-5-sonnet-20241022", "Anthropic"),
    ("gemini-2.0-flash", "Google Gemini"),
    ("gemini-1.5-pro-001", "Google Gemini"),
    ("google/gemini-flash", "Google Gemini"),
    ("groq/llama-3.3-70b-versatile", "Groq"),
    ("together/llama-3.3-70b", "Together AI"),
    ("mistral/mistral-large-latest", "Mistral AI"),
    ("openrouter/openai/gpt-4o", "OpenRouter"),
    ("azure/my-deployment", "Azure OpenAI"),
    ("cohere/command-r-plus", "Cohere"),
    ("command-r-plus-08-2024", "Cohere"),
    ("ollama/qwen2.5:7b", "Ollama (local)"),
    ("ollama/llama3.2", "Ollama (local)"),
    ("qwen2.5", "Ollama (Qwen)"),
    ("llama3.2", "Ollama (Llama)"),
    ("phi3.5", "Ollama (Phi)"),
    ("deepseek-coder:7b", "Ollama (DeepSeek)"),
    ("gemma2:9b", "Ollama (Gemma)"),
])
def test_route_for_correct_provider(model, expected_name):
    route = route_for(model)
    assert route is not None, f"No route for {model!r}"
    assert route.name == expected_name, f"{model!r}: expected {expected_name!r}, got {route.name!r}"


def test_route_for_unknown_returns_none():
    assert route_for("my-custom-model-xyz") is None


def test_route_adapter_types():
    from debugai.providers import _ADAPTER_MAP
    # All adapters in the table must be recognized.
    adapter_types = {"openai", "anthropic", "openai_compat", "ollama", "cohere"}
    for route in PROVIDER_ROUTES:
        assert route.adapter in adapter_types, f"{route.prefix}: unknown adapter {route.adapter!r}"


# ---------------------------------------------------------------------------
# _OpenAICompatAdapter
# ---------------------------------------------------------------------------
def test_openai_compat_adapter_matches_openai_client():
    class FakeOAI:
        def __init__(s):
            s.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=lambda **k: None))
    assert _OpenAICompatAdapter.matches(FakeOAI())


def test_openai_compat_adapter_does_not_match_anthropic_client():
    class FakeAnthropic:
        messages = types.SimpleNamespace(create=lambda **k: None)
    assert not _OpenAICompatAdapter.matches(FakeAnthropic())


# ---------------------------------------------------------------------------
# _CohereAdapter
# ---------------------------------------------------------------------------
def test_cohere_adapter_matches():
    class FakeCohere:
        chat = lambda **k: None
        embed = lambda **k: None
    assert _CohereAdapter.matches(FakeCohere())


def test_cohere_adapter_does_not_match_anthropic():
    class FakeAnthropic:
        messages = types.SimpleNamespace(create=lambda **k: None)
        chat = lambda **k: None
        embed = lambda **k: None
    # Has .messages so not matched by Cohere
    assert not _CohereAdapter.matches(FakeAnthropic())


def test_cohere_from_response():
    text_block = types.SimpleNamespace(text="Hello from Cohere")
    message = types.SimpleNamespace(content=[text_block])
    tokens = types.SimpleNamespace(input_tokens=10, output_tokens=5)
    meta = types.SimpleNamespace(tokens=tokens)
    resp = types.SimpleNamespace(message=message, meta=meta)
    text, usage = _CohereAdapter.from_response(resp)
    assert text == "Hello from Cohere"
    assert usage == {"prompt": 10, "completion": 5, "total": 15}


# ---------------------------------------------------------------------------
# completion() provider routing with fake clients
# ---------------------------------------------------------------------------
def _fake_oai_resp(text="ok"):
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=text))],
        usage=types.SimpleNamespace(prompt_tokens=5, completion_tokens=3, total_tokens=8),
    )


class FakeOllamaClient:
    def __init__(self, text="qwen says hello"):
        self._text = text
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=lambda **k: _fake_oai_resp(text)))


def test_completion_ollama_model(monkeypatch):
    """ollama/qwen2.5 routes to _OpenAICompatAdapter via the Ollama base_url."""
    from debugai import sdk as sdk_mod
    from debugai.sdk import _OpenAICompatAdapter as OC

    monkeypatch.setattr(sdk_mod, "_PROVIDER_REGISTRY", [])
    monkeypatch.setattr(sdk_mod, "_default_providers", lambda: [])

    register_provider(
        matches=lambda m: m.startswith("ollama/") or m.startswith("qwen"),
        adapter=OC,
        client_factory=lambda: FakeOllamaClient("qwen says hello"),
    )
    cfg = DebugAIConfig(enable_diagnosis=False, enable_traces=False)
    resp = completion("ollama/qwen2.5", [{"role": "user", "content": "hi"}], config=cfg)
    assert resp.text == "qwen says hello"
    assert resp.model == "ollama/qwen2.5"
    assert resp.cost_usd == 0.0  # local model = no cost


def test_completion_gemini_model(monkeypatch):
    """gemini-* routes through _OpenAICompatAdapter."""
    from debugai import sdk as sdk_mod
    from debugai.sdk import _OpenAICompatAdapter as OC

    monkeypatch.setattr(sdk_mod, "_PROVIDER_REGISTRY", [])
    monkeypatch.setattr(sdk_mod, "_default_providers", lambda: [])

    register_provider(
        matches=lambda m: m.startswith("gemini"),
        adapter=OC,
        client_factory=lambda: FakeOllamaClient("gemini says hello"),
    )
    cfg = DebugAIConfig(enable_diagnosis=False, enable_traces=False)
    resp = completion("gemini-2.0-flash", [{"role": "user", "content": "hi"}], config=cfg)
    assert resp.text == "gemini says hello"


# ---------------------------------------------------------------------------
# Fallback routing (B1)
# ---------------------------------------------------------------------------
def test_fallback_used_when_primary_fails(monkeypatch):
    from debugai import sdk as sdk_mod
    from debugai.sdk import _OpenAICompatAdapter as OC

    monkeypatch.setattr(sdk_mod, "_PROVIDER_REGISTRY", [])
    monkeypatch.setattr(sdk_mod, "_default_providers", lambda: [])

    call_count = {"n": 0}

    class FailingClient:
        chat = types.SimpleNamespace(completions=types.SimpleNamespace(
            create=lambda **k: (_ for _ in ()).throw(ConnectionError("rate limit"))))

    class FallbackClient:
        chat = types.SimpleNamespace(completions=types.SimpleNamespace(
            create=lambda **k: _fake_oai_resp("fallback answer")))

    register_provider(
        matches=lambda m: m == "primary-model",
        adapter=OC, client_factory=lambda: FailingClient())
    register_provider(
        matches=lambda m: m == "backup-model",
        adapter=OC, client_factory=lambda: FallbackClient())

    cfg = DebugAIConfig(enable_diagnosis=False, enable_traces=False,
                        fallbacks=["backup-model"])
    resp = completion("primary-model", [{"role": "user", "content": "hi"}], config=cfg)
    assert resp.text == "fallback answer"
    assert resp.model == "backup-model"
    assert resp.fallback_attempts[0][0] == "primary-model"


def test_no_fallback_raises_original_error(monkeypatch):
    from debugai import sdk as sdk_mod
    from debugai.sdk import _OpenAICompatAdapter as OC

    monkeypatch.setattr(sdk_mod, "_PROVIDER_REGISTRY", [])
    monkeypatch.setattr(sdk_mod, "_default_providers", lambda: [])

    class FailingClient:
        chat = types.SimpleNamespace(completions=types.SimpleNamespace(
            create=lambda **k: (_ for _ in ()).throw(RuntimeError("server down"))))

    register_provider(matches=lambda m: m == "bad-model", adapter=OC,
                      client_factory=lambda: FailingClient())
    cfg = DebugAIConfig(enable_diagnosis=False, enable_traces=False)
    with pytest.raises(RuntimeError, match="server down"):
        completion("bad-model", [{"role": "user", "content": "hi"}], config=cfg)


# ---------------------------------------------------------------------------
# JSON schema validation (B2)
# ---------------------------------------------------------------------------
def test_validate_json_schema_valid():
    schema = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
    assert _validate_json_schema('{"answer": "hello"}', schema) == []


def test_validate_json_schema_missing_required():
    schema = {"type": "object", "required": ["answer"]}
    v = _validate_json_schema('{"other": "x"}', schema)
    assert any("answer" in s for s in v)


def test_validate_json_schema_wrong_type():
    schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
    v = _validate_json_schema('{"count": "five"}', schema)
    assert any("count" in s for s in v)


def test_validate_json_schema_not_json():
    v = _validate_json_schema("not json at all", {"type": "object"})
    assert any("not valid JSON" in s for s in v)


def test_validate_json_schema_empty_is_always_valid():
    assert _validate_json_schema('{"anything": true}', {}) == []


def test_config_schema_violation_callback():
    """DebugAIConfig.response_schema fires on_schema_violation in background worker."""
    import types as _types
    from debugai.sdk import wrap_llm

    violations_received = []
    def fake_create(**k):
        return _types.SimpleNamespace(
            choices=[_types.SimpleNamespace(message=_types.SimpleNamespace(content='not json'))],
            usage=_types.SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2))

    class FakeOAI:
        def __init__(s): s.chat = _types.SimpleNamespace(
            completions=_types.SimpleNamespace(create=fake_create))

    schema = {"type": "object", "required": ["result"]}
    cfg = DebugAIConfig(enable_diagnosis=False, enable_traces=False,
                        response_schema=schema,
                        on_schema_violation=lambda txt, vs: violations_received.extend(vs))
    client = wrap_llm(FakeOAI(), config=cfg)
    client.chat.completions.create(model="gpt-4o", messages=[{"role":"user","content":"q"}])
    client.debugai.flush()
    assert violations_received  # schema violation was detected and reported
