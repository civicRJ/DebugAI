"""Robustness: degenerate / adversarial inputs must never crash the engine."""

import types

import pytest

from debugai import analyze, wrap_llm
from debugai.judge import judge_instructions
from debugai.signals import compute_signals, estimate_variance
from debugai.schema import CaptureRecord


def _ok(result):
    assert isinstance(result, dict)
    assert "healthy" in result and "signals" in result
    for v in result["signals"].values():
        if isinstance(v, float):
            assert v == v  # not NaN


def test_empty_and_whitespace_output():
    _ok(analyze(prompt="What is the policy?", output="", explain_with_llm=False))
    _ok(analyze(prompt="q", output="   \n\t ", explain_with_llm=False))


def test_non_numeric_and_nan_similarity_scores():
    r = analyze(prompt="q", output="some answer", chunks=["a", "b"],
                similarity_scores=[None, "bad", float("nan"), 0.4],
                explain_with_llm=False)
    _ok(r)
    assert r["signals"]["similarity"] == 0.4  # only the valid score is used


def test_nan_and_string_temperature_dont_propagate():
    assert estimate_variance(CaptureRecord(user_prompt="q", llm_output="a",
                                           temperature=float("nan")))[0] == 0.0
    r = analyze(prompt="q", output="a", temperature=float("nan"), explain_with_llm=False)
    _ok(r)


def test_unicode_emoji_and_long_inputs():
    _ok(analyze(prompt="¿Por qué? 🤔 日本語", output="émïgré 🚀" * 50,
                chunks=["ünïcode 文脈 🌟"], similarity_scores=[0.3], explain_with_llm=False))
    _ok(analyze(prompt="q", output="x " * 20000, chunks=["y " * 5000],
                similarity_scores=[0.6], explain_with_llm=False))


def test_mismatched_chunks_and_scores():
    _ok(analyze(prompt="q", output="a", chunks=["only one chunk"],
                similarity_scores=[0.2, 0.3, 0.4], explain_with_llm=False))


def test_judge_handles_none_user_prompt():
    d = judge_instructions("You are a Socratic tutor; ask one question.", None,
                           "Here is the full answer. What do you think?")
    assert d is not None  # no crash on None user prompt


def test_compute_signals_no_nan_on_degenerate():
    s = compute_signals(CaptureRecord(user_prompt="q", llm_output="",
                                      retrieved_chunks=[], similarity_scores=[]))
    for name, v in s.to_dict().items():
        if isinstance(v, float):
            assert v == v, name


def test_sdk_handles_list_and_none_message_content():
    def ns(**k):
        return types.SimpleNamespace(**k)

    class FakeOpenAI:
        def __init__(s):
            s.chat = ns(completions=ns(create=s.c))
        def c(s, **k):
            return ns(choices=[ns(message=ns(content="ok"))],
                      usage=ns(prompt_tokens=1, completion_tokens=1, total_tokens=2))

    client = wrap_llm(FakeOpenAI())
    # content as a list of parts and as None must not break the wrapped call
    resp = client.chat.completions.create(model="gpt-4o", messages=[
        {"role": "system", "content": None},
        {"role": "user", "content": [{"type": "text", "text": "hi"}, {"type": "text", "text": "there"}]},
    ])
    assert resp.choices[0].message.content == "ok"
    client.debugai.flush()
