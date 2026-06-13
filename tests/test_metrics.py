"""MetricsLedger — thread-safe per-model counters."""

import threading

from debugai.metrics import MetricsLedger


def _make():
    return MetricsLedger()


def test_basic_record_and_snapshot():
    m = _make()
    m.record("gpt-4o", prompt_tokens=100, completion_tokens=50,
             cost_usd=0.001, latency_ms=320.0, failed=False)
    snap = m.snapshot()
    assert snap["requests"] == 1
    assert snap["total_tokens"] == 150
    assert snap["by_model"]["gpt-4o"]["requests"] == 1
    assert snap["by_model"]["gpt-4o"]["cost_usd"] > 0


def test_multiple_models():
    m = _make()
    m.record("gpt-4o", 100, 50, 0.001, 300.0, False)
    m.record("claude-haiku-4-5", 200, 80, 0.0005, 150.0, False)
    m.record("gpt-4o", 120, 60, 0.001, 280.0, True)
    assert m.requests == 3
    assert m.failures == 1
    assert len(m.by_model) == 2
    assert m.by_model["gpt-4o"]["requests"] == 2
    assert m.by_model["gpt-4o"]["failures"] == 1


def test_latency_percentiles():
    m = _make()
    for ms in [100, 200, 300, 400, 500]:
        m.record("gpt-4o", 10, 5, 0.0, float(ms), False)
    assert 200 <= m.latency_p50 <= 320
    assert m.latency_p95 >= 400


def test_reset():
    m = _make()
    m.record("gpt-4o", 100, 50, 0.001, 300.0, False)
    m.reset()
    assert m.requests == 0 and m.by_model == {} and m.total_tokens == 0


def test_thread_safety():
    m = _make()
    errors = []

    def worker():
        try:
            for _ in range(100):
                m.record("gpt-4o", 10, 5, 0.0001, 50.0, False)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert not errors
    assert m.requests == 800


def test_module_level_metrics_singleton():
    """The module-level debugai.metrics updates via wrap_llm background worker."""
    import types
    from debugai.metrics import metrics
    from debugai.config import DebugAIConfig
    from debugai.sdk import wrap_llm

    before = metrics.requests

    class FakeOAI:
        def __init__(s): s.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=s.c))
        def c(s, **k): return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="ok"))],
            usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15))

    cfg = DebugAIConfig(enable_diagnosis=False, enable_traces=False)  # metrics only
    client = wrap_llm(FakeOAI(), config=cfg)
    client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])
    client.debugai.flush()
    assert metrics.requests == before + 1
    assert "gpt-4o-mini" in metrics.by_model
