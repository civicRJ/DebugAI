from debugai import analyze_agent_trace


def _failure(report):
    return report["diagnosis"]["primary"]["failure"]


def test_detects_tool_call_loop():
    report = analyze_agent_trace(
        events=[
            {"type": "tool_call", "tool": "search", "args": {"q": "refund policy"}},
            {"type": "tool_result", "tool": "search", "output": "30-day unopened electronics policy"},
            {"type": "tool_call", "tool": "search", "args": {"q": "refund policy"}},
            {"type": "tool_result", "tool": "search", "output": "30-day unopened electronics policy"},
            {"type": "tool_call", "tool": "search", "args": {"q": "refund policy"}},
        ],
        goal="Resolve customer refund request",
    )
    assert _failure(report) == "tool_call_loop"
    assert report["fix"]["agent"] == "Agent Runtime Fix Agent"


def test_detects_wrong_and_missing_tool():
    report = analyze_agent_trace(
        events=[
            {"type": "tool_call", "tool": "weather", "args": {"city": "Boston"}},
            {"type": "final", "output": "Refund approved."},
        ],
        goal="Check refund eligibility",
        expected_tools=["refund_order"],
    )
    failures = [i["failure"] for i in report["issues"]]
    assert "wrong_tool_selected" in failures
    assert "missing_tool_call" in failures


def test_detects_tool_result_ignored():
    report = analyze_agent_trace(
        events=[
            {"type": "tool_call", "tool": "search", "args": {"q": "opened electronics refund"}},
            {"type": "tool_result", "tool": "search", "output": "Opened electronics are not refundable. Unopened items have a 30-day window."},
            {"type": "final", "output": "Opened electronics get a 90-day cash refund."},
        ],
        goal="Answer refund policy",
        expected_tools=["search"],
    )
    assert "tool_result_ignored" in [i["failure"] for i in report["issues"]]


def test_detects_approval_gate_missing():
    report = analyze_agent_trace(
        events=[
            {"type": "llm", "output": "I will issue the refund now."},
            {"type": "tool_call", "tool": "refund_order", "args": {"order_id": "ord_123"}},
        ],
        goal="Issue refund only after explicit approval",
        expected_tools=["refund_order"],
    )
    assert "approval_gate_missing" in [i["failure"] for i in report["issues"]]


def test_detects_runaway_budget():
    report = analyze_agent_trace(
        events=[{"type": "llm", "output": f"step {i}", "tokens": 100} for i in range(6)],
        goal="Answer concisely",
        max_steps=3,
        max_tokens=300,
    )
    assert _failure(report) == "runaway_cost_latency"


def test_healthy_agent_trace_not_flagged():
    report = analyze_agent_trace(
        events=[
            {"type": "tool_call", "tool": "search", "args": {"q": "refund policy electronics"}},
            {"type": "tool_result", "tool": "search", "output": "Electronics can be returned unopened within 30 days."},
            {"type": "final", "output": "Electronics can be returned unopened within 30 days."},
        ],
        goal="Answer refund policy for electronics",
        expected_tools=["search"],
        max_steps=8,
    )
    assert report["healthy"] is True
    assert report["diagnosis"]["primary"] is None
