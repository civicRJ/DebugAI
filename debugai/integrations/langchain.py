"""LangChain integration — diagnose a RAG/LLM chain automatically.

Attach the callback handler to any LangChain run; it captures the retrieved
documents and the LLM prompt/output, then runs ``analyze()`` on the result and
hands the diagnosis to your sink:

    from debugai.integrations import DebugAICallbackHandler
    handler = DebugAICallbackHandler(on_diagnosis=lambda d: print(d["primary"]))
    chain.invoke(question, config={"callbacks": [handler]})

Works whether or not ``langchain`` is installed — if the LangChain base class is
importable we subclass it (so LangChain dispatches the events); otherwise the
handler is still a usable plain object you can drive directly (and in tests).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from debugai.analyze import analyze

log = logging.getLogger("debugai.integrations.langchain")

# Subclass the real base when available so LangChain routes callbacks to us.
try:  # langchain-core (current)
    from langchain_core.callbacks import BaseCallbackHandler as _Base
except Exception:  # pragma: no cover - optional dep
    try:  # older monolithic langchain
        from langchain.callbacks.base import BaseCallbackHandler as _Base
    except Exception:
        _Base = object


def _doc_text(doc: Any) -> str:
    return getattr(doc, "page_content", None) or (doc.get("page_content", "") if isinstance(doc, dict) else str(doc))


def _gen_text(response: Any) -> str:
    """Pull the generated text out of a LangChain LLMResult (LLM or chat)."""
    gens = getattr(response, "generations", None)
    if not gens:
        return ""
    first = gens[0][0]
    text = getattr(first, "text", "") or ""
    if not text:  # chat models carry it on .message.content
        msg = getattr(first, "message", None)
        content = getattr(msg, "content", "")
        text = content if isinstance(content, str) else " ".join(
            p.get("text", "") for p in content if isinstance(p, dict)
        ) if isinstance(content, list) else str(content or "")
    return text


class DebugAICallbackHandler(_Base):
    """Captures retrieval + generation from a LangChain run and diagnoses it."""

    def __init__(self, on_diagnosis: Callable[[dict], None] | None = None,
                 system_prompt: str = "", judge: bool = False,
                 explain_with_llm: bool = False):
        super().__init__()
        self._on_diagnosis = on_diagnosis
        self._system_prompt = system_prompt
        self._judge = judge
        self._explain = explain_with_llm
        self.last: dict | None = None        # most recent diagnosis, for inspection
        self._prompt: str = ""
        self._chunks: list[str] = []

    # --- LangChain callback hooks -----------------------------------------
    def on_retriever_end(self, documents, **kwargs) -> None:
        try:
            self._chunks = [_doc_text(d) for d in (documents or [])]
        except Exception as e:  # never break the chain
            log.warning("retriever capture failed: %s", e)

    def on_llm_start(self, serialized, prompts, **kwargs) -> None:
        if prompts:
            self._prompt = prompts[-1]

    def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
        # messages: list[list[BaseMessage]]; grab the last human message's text.
        try:
            flat = messages[-1] if messages else []
            for m in reversed(flat):
                content = getattr(m, "content", "")
                if content:
                    self._prompt = content if isinstance(content, str) else str(content)
                    break
        except Exception as e:
            log.warning("chat-start capture failed: %s", e)

    def on_llm_end(self, response, **kwargs) -> None:
        output = _gen_text(response)
        if not (self._prompt or output):
            return
        try:
            self.last = analyze(
                prompt=self._prompt or "(unknown)", output=output,
                system_prompt=self._system_prompt,
                chunks=self._chunks or None,
                explain_with_llm=self._explain, judge=self._judge,
            )
            if self._on_diagnosis is not None:
                self._on_diagnosis(self.last)
        except Exception as e:  # diagnosis must never break the user's chain
            log.warning("DebugAI analyze failed: %s", e)
        finally:
            self._chunks = []  # reset retrieval for the next call
