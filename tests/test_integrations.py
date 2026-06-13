"""LangChain callback integration (driven directly with fake events — no
langchain dependency required)."""

import types

from debugai.integrations import DebugAICallbackHandler


def _doc(text):
    return types.SimpleNamespace(page_content=text)


def _llm_result(text):
    gen = types.SimpleNamespace(text=text, message=None)
    return types.SimpleNamespace(generations=[[gen]])


def test_handler_detects_ungrounded_answer():
    # Without retriever scores the engine can't judge retrieval quality, but it
    # does catch an answer not grounded in the retrieved chunks.
    out = []
    h = DebugAICallbackHandler(on_diagnosis=out.append)
    h.on_retriever_end([_doc("Store hours are 9 to 5."), _doc("Parking is out back.")])
    h.on_llm_start({}, ["What is the refund policy for electronics?"])
    h.on_llm_end(_llm_result("Electronics get a full 90-day cash refund, no receipt needed."))
    assert len(out) == 1
    assert h.last["healthy"] is False
    assert h.last["primary"]["failure"] in ("hallucination", "entity_gap", "retrieval_failure")
    assert h._chunks == []  # retrieval state resets after each generation


def test_handler_chat_model_and_healthy():
    h = DebugAICallbackHandler()
    h.on_retriever_end([_doc("Most items may be returned within 30 days with a receipt.")])
    msg = types.SimpleNamespace(content="What is the return window?")
    h.on_chat_model_start({}, [[msg]])
    chat_gen = types.SimpleNamespace(text="", message=types.SimpleNamespace(
        content="Most items may be returned within 30 days with a receipt."))
    h.on_llm_end(types.SimpleNamespace(generations=[[chat_gen]]))
    assert h.last is not None and h.last["healthy"] is True


def test_handler_never_raises_on_bad_events():
    h = DebugAICallbackHandler()
    h.on_retriever_end(None)          # no docs
    h.on_llm_end(types.SimpleNamespace(generations=[]))  # empty result → no-op
    assert h.last is None
