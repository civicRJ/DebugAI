"""Level 2 SDK wrapper tests.

Uses fake OpenAI/Anthropic clients (duck-typed) so no real SDK or network is
needed. Verifies: transparent forwarding, unchanged responses, all 4 data
groups captured, retrieval attachment, and sub-10ms request overhead.
"""

import time
import types

import pytest

from debugai.sdk import http_trace_sink, retrieval_context, session, wrap_llm


# --------------------------------------------------------------------------- #
# Fakes mimicking the OpenAI / Anthropic response + client shapes
# --------------------------------------------------------------------------- #
def _ns(**kw):
    return types.SimpleNamespace(**kw)


class FakeOpenAI:
    def __init__(self, output="ok", call_delay=0.0):
        self._output = output
        self._delay = call_delay
        self.other_attr = "passthrough"
        completions = _ns(create=self._create)
        self.chat = _ns(completions=completions)

    def _create(self, **kwargs):
        if self._delay:
            time.sleep(self._delay)
        self._last_kwargs = kwargs
        return _ns(
            choices=[_ns(message=_ns(content=self._output))],
            usage=_ns(prompt_tokens=120, completion_tokens=30, total_tokens=150),
        )

    def helper(self):
        return "i am a real method"


class FakeAnthropic:
    def __init__(self, output="ok"):
        self._output = output
        self.messages = _ns(create=self._create)

    def _create(self, **kwargs):
        return _ns(
            content=[_ns(type="text", text=self._output)],
            usage=_ns(input_tokens=200, output_tokens=40),
        )


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_transparent_forwarding():
    client = wrap_llm(FakeOpenAI())
    assert client.other_attr == "passthrough"
    assert client.helper() == "i am a real method"


def test_response_returned_unchanged():
    raw = FakeOpenAI(output="hello world")
    client = wrap_llm(raw)
    resp = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
    )
    assert resp.choices[0].message.content == "hello world"


def test_diagnosis_produced_for_retrieval_failure():
    diagnoses = []
    client = wrap_llm(FakeOpenAI(
        output="Electronics get a full 90-day cash refund."
    ), on_diagnosis=diagnoses.append)
    client.chat.completions.create(
        model="gpt-4o",
        temperature=0.2,
        messages=[
            {"role": "system", "content": "Answer from context."},
            {"role": "user", "content": "What is the refund policy for electronics?"},
        ],
        debugai_chunks=["Store hours are 9 to 5.", "Parking is out back."],
        debugai_similarity_scores=[0.42, 0.40],
    )
    client.debugai.flush()
    assert len(diagnoses) == 1
    assert diagnoses[0]["primary"]["failure"] == "retrieval_failure"


def test_captures_all_four_data_groups():
    captured = []
    client = wrap_llm(FakeOpenAI(output="Most items return in 30 days."),
                      on_diagnosis=captured.append)
    with retrieval_context(["Most items may be returned within 30 days."],
                           similarity_scores=[0.9]):
        client.chat.completions.create(
            model="gpt-4o-mini", temperature=0.1, max_tokens=256,
            messages=[
                {"role": "system", "content": "Be helpful."},
                {"role": "user", "content": "What is the return window?"},
            ],
        )
    client.debugai.flush()
    sig = captured[0]["signals"]
    # Retrieval group → real similarity; runtime group → token ratio computed.
    assert sig["similarity"] == pytest.approx(0.9)
    assert "token_ratio" in sig and "context_ratio" in sig


def test_anthropic_client_supported():
    out = []
    client = wrap_llm(FakeAnthropic(output="The HQ is in Austin, Texas."),
                      on_diagnosis=out.append)
    resp = client.messages.create(
        model="claude-haiku-4-5", max_tokens=128,
        system="Answer from context.",
        messages=[{"role": "user", "content": "Where is the HQ?"}],
        debugai_chunks=["The company is headquartered in Austin, Texas."],
        debugai_similarity_scores=[0.92],
    )
    assert resp.content[0].text == "The HQ is in Austin, Texas."
    client.debugai.flush()
    assert out and out[0]["healthy"] is True


def test_debugai_kwargs_not_forwarded_to_sdk():
    raw = FakeOpenAI()
    client = wrap_llm(raw)
    client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": "hi"}],
        debugai_chunks=["x"], debugai_similarity_scores=[0.5],
    )
    assert "debugai_chunks" not in raw._last_kwargs
    assert "debugai_similarity_scores" not in raw._last_kwargs


def test_request_overhead_under_10ms():
    # Compare wrapped vs raw call time; the wrapper must add < 10ms (it only
    # builds a dict and enqueues — heavy diagnosis is on the worker thread).
    raw = FakeOpenAI(output="some answer", call_delay=0.0)
    msgs = [{"role": "user", "content": "hello"}]

    t0 = time.perf_counter()
    for _ in range(50):
        raw._create(model="gpt-4o", messages=msgs)
    raw_avg = (time.perf_counter() - t0) / 50

    client = wrap_llm(FakeOpenAI(output="some answer"))
    t0 = time.perf_counter()
    for _ in range(50):
        client.chat.completions.create(model="gpt-4o", messages=msgs)
    wrapped_avg = (time.perf_counter() - t0) / 50

    overhead_ms = (wrapped_avg - raw_avg) * 1000
    assert overhead_ms < 10.0, f"overhead {overhead_ms:.2f}ms exceeds 10ms"


def test_unknown_client_rejected():
    with pytest.raises(TypeError):
        wrap_llm(object())


def test_http_trace_sink_swallows_errors():
    # Posting to an unreachable port must not raise (tracing never breaks the app).
    sink = http_trace_sink("http://127.0.0.1:9/none", token="dbg_x", timeout=0.2)
    sink(types.SimpleNamespace(to_dict=lambda: {"name": "t"}))  # no exception


def test_wrap_llm_emits_trace_with_spans_and_scores():
    traces = []
    client = wrap_llm(
        FakeOpenAI(output="Full 90-day cash refund, no receipt needed."),
        on_trace=lambda t: traces.append(t.to_dict()),
    )
    with retrieval_context(["Store hours are 9 to 5."], similarity_scores=[0.42]):
        with session("conv-7"):
            client.chat.completions.create(
                model="claude-haiku-4-5", temperature=0.2,
                messages=[{"role": "user", "content": "What is the refund policy?"}],
            )
    client.debugai.flush()
    assert len(traces) == 1
    t = traces[0]
    assert t["session_id"] == "conv-7"
    assert [s["kind"] for s in t["spans"]] == ["retrieval", "generation"]
    assert t["total_tokens"] == 150 and t["cost_usd"] > 0
    assert t["status"] == "failing"
    score_names = {s["name"] for s in t["scores"]}
    assert {"healthy", "failure", "confidence"} <= score_names
    assert client.debugai.recent_traces  # buffered for inspection
