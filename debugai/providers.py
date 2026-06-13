"""Provider routing table — maps model name prefixes to (base_url, api_key_env,
adapter_class). Called by ``debugai.completion()`` / ``debugai.acompletion()``.

The key architectural insight: most modern providers speak the OpenAI REST API spec
(same endpoint shape, same response format). A single ``_OpenAICompatAdapter`` covers:
  - Google Gemini (via Google's official OpenAI-compat endpoint)
  - Ollama + any local model (Qwen, Llama, Phi, DeepSeek…)
  - Groq, Together AI, Mistral AI, OpenRouter, Azure OpenAI, LM Studio, vLLM
  - Any custom server that accepts POST /v1/chat/completions

Only Cohere requires a native adapter (different API shape).

All routing is prefix-based on the model name. Users can extend or override the table:
    from debugai import register_provider
    register_provider(matches=lambda m: m.startswith("my-"), adapter=MyAdapter,
                      client_factory=lambda cfg: MyClient(...))
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from debugai.config import DebugAIConfig


@dataclass(frozen=True)
class ProviderRoute:
    prefix: str                     # model name prefix, e.g. "gemini-", "ollama/"
    name: str                       # human name, e.g. "Google Gemini"
    base_url: str | None            # None → use the SDK default
    api_key_env: str | None         # env var name for the API key; None → no key (local)
    adapter: str                    # "openai" | "openai_compat" | "anthropic" | "cohere"
    notes: str = ""


# ---------------------------------------------------------------------------
# The routing table. Checked in order — first prefix match wins.
# ---------------------------------------------------------------------------
PROVIDER_ROUTES: list[ProviderRoute] = [
    # ── OpenAI ──────────────────────────────────────────────────────────────
    ProviderRoute("gpt-",          "OpenAI",        None,                                "OPENAI_API_KEY",     "openai"),
    ProviderRoute("o1-",           "OpenAI",        None,                                "OPENAI_API_KEY",     "openai"),
    ProviderRoute("o3-",           "OpenAI",        None,                                "OPENAI_API_KEY",     "openai"),
    ProviderRoute("o4-",           "OpenAI",        None,                                "OPENAI_API_KEY",     "openai"),
    ProviderRoute("text-",         "OpenAI",        None,                                "OPENAI_API_KEY",     "openai"),

    # ── Anthropic ───────────────────────────────────────────────────────────
    ProviderRoute("claude-",       "Anthropic",     None,                                "ANTHROPIC_API_KEY",  "anthropic"),

    # ── Google Gemini (OpenAI-compat endpoint) ──────────────────────────────
    ProviderRoute("gemini-",       "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "openai_compat"),
    ProviderRoute("google/",       "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", "openai_compat"),

    # ── Groq (fast inference, OpenAI-compat) ────────────────────────────────
    ProviderRoute("groq/",         "Groq",          "https://api.groq.com/openai/v1",    "GROQ_API_KEY",       "openai_compat"),

    # ── Together AI (OpenAI-compat) ─────────────────────────────────────────
    ProviderRoute("together/",     "Together AI",   "https://api.together.xyz/v1",       "TOGETHER_API_KEY",   "openai_compat"),

    # ── Mistral AI (OpenAI-compat) ──────────────────────────────────────────
    ProviderRoute("mistral/",      "Mistral AI",    "https://api.mistral.ai/v1",         "MISTRAL_API_KEY",    "openai_compat"),

    # ── OpenRouter (multi-provider proxy, OpenAI-compat) ────────────────────
    ProviderRoute("openrouter/",   "OpenRouter",    "https://openrouter.ai/api/v1",      "OPENROUTER_API_KEY", "openai_compat"),

    # ── Azure OpenAI (OpenAI-compat + endpoint from env) ────────────────────
    ProviderRoute("azure/",        "Azure OpenAI",  None,                                "AZURE_OPENAI_API_KEY","openai_compat",
                  notes="Set AZURE_OPENAI_ENDPOINT. Model name: 'azure/<deployment-name>'"),

    # ── Cohere (native adapter) ──────────────────────────────────────────────
    ProviderRoute("cohere/",       "Cohere",        None,                                "COHERE_API_KEY",     "cohere"),
    ProviderRoute("command-",      "Cohere",        None,                                "COHERE_API_KEY",     "cohere"),

    # ── Ollama — local models via the Ollama OpenAI-compat server ───────────
    # Any model served by Ollama: qwen2.5, llama3, phi3, deepseek-coder, codellama…
    # Default: http://localhost:11434/v1  (override with OLLAMA_BASE_URL or config.ollama_base_url)
    ProviderRoute("ollama/",       "Ollama (local)",  None,  None, "ollama",
                  notes="Requires Ollama running. Set OLLAMA_BASE_URL if not localhost:11434."),
    # Common local model families also route to Ollama when no prefix given:
    ProviderRoute("qwen",          "Ollama (Qwen)",   None,  None, "ollama"),
    ProviderRoute("llama",         "Ollama (Llama)",  None,  None, "ollama"),
    ProviderRoute("phi",           "Ollama (Phi)",    None,  None, "ollama"),
    ProviderRoute("deepseek",      "Ollama (DeepSeek)",None, None, "ollama"),
    ProviderRoute("codellama",     "Ollama (CodeLlama)",None,None, "ollama"),
    ProviderRoute("gemma",         "Ollama (Gemma)",  None,  None, "ollama"),
    ProviderRoute("mixtral",       "Ollama (Mixtral)",None,  None, "ollama"),
    ProviderRoute("vicuna",        "Ollama (Vicuna)", None,  None, "ollama"),
]


def route_for(model: str) -> ProviderRoute | None:
    """Return the first matching route for a model name, or None."""
    low = model.lower()
    for route in PROVIDER_ROUTES:
        if low.startswith(route.prefix.lower()):
            return route
    return None


def _get_adapter_map():
    """Deferred import to avoid circular imports at module load time."""
    from debugai.sdk import (
        _AnthropicAdapter, _CohereAdapter,
        _OpenAIAdapter, _OpenAICompatAdapter,
    )
    return {
        "openai": _OpenAIAdapter,
        "anthropic": _AnthropicAdapter,
        "openai_compat": _OpenAICompatAdapter,
        "ollama": _OpenAICompatAdapter,
        "cohere": _CohereAdapter,
    }


# Lazily evaluated so there's no circular import at load time.
class _AdapterMapProxy(dict):
    _loaded = False
    def _ensure(self):
        if not self._loaded:
            self.update(_get_adapter_map())
            self._loaded = True
    def get(self, key, default=None):
        self._ensure()
        return super().get(key, default)
    def __getitem__(self, key):
        self._ensure()
        return super().__getitem__(key)


_ADAPTER_MAP = _AdapterMapProxy()


def make_client(route: ProviderRoute, config: "DebugAIConfig") -> Any:
    """Build the provider client from a route + config. All OpenAI-compat clients
    are instantiated via the OpenAI SDK (no per-provider install needed)."""

    if route.adapter == "anthropic":
        from anthropic import Anthropic
        return Anthropic(timeout=60.0, max_retries=2)

    if route.adapter == "cohere":
        try:
            import cohere  # optional; graceful ImportError if not installed
            return cohere.ClientV2(api_key=os.environ.get(route.api_key_env or "COHERE_API_KEY", ""))
        except ImportError:
            raise ImportError(
                "Cohere models require the 'cohere' package: pip install cohere"
            )

    if route.adapter == "ollama":
        from openai import OpenAI
        base_url = (getattr(config, "ollama_base_url", None)
                    or os.environ.get("OLLAMA_BASE_URL")
                    or "http://localhost:11434/v1")
        return OpenAI(base_url=base_url, api_key="ollama", timeout=120.0)

    if route.adapter in ("openai_compat", "openai"):
        from openai import OpenAI
        base_url = route.base_url
        api_key: str | None = None

        if route.adapter == "openai_compat":
            if route.prefix.startswith("azure/"):
                base_url = (os.environ.get("AZURE_OPENAI_ENDPOINT", "")
                            .rstrip("/") + "/openai")
            api_key = (os.environ.get(route.api_key_env, "") if route.api_key_env
                       else "no-key-needed")

        return OpenAI(
            base_url=base_url,
            api_key=api_key or os.environ.get(route.api_key_env or "", ""),
            timeout=60.0,
            max_retries=2,
        )

    raise ValueError(f"Unknown adapter type {route.adapter!r} in routing table.")
