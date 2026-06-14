"""SDK-level debug report artifact tests."""

from debugai import debug_report, example_cases, get_example, list_examples
from debugai.report import format_debug_report


def test_examples_cover_core_debugger_failures():
    ids = {x["id"] for x in list_examples()}
    assert {
        "rag_hallucination",
        "retrieval_failure",
        "schema_violation",
        "tool_call_failure",
        "citation_failure",
        "ambiguous_prompt",
    } <= ids
    assert len(example_cases()) == len(ids)


def test_debug_report_returns_failure_evidence_and_fix():
    case = get_example("schema_violation")["case"]
    report = debug_report(**case, rerun=lambda s, u, c, t: '{"status":"ok","answer":"done"}')
    assert report["status"] == "failing"
    assert report["failure"] == "schema_violation"
    assert report["evidence"]
    assert report["fix_report"]["verdict"] == "verified"


def test_format_debug_report_is_log_friendly():
    case = get_example("tool_call_failure")["case"]
    report = debug_report(**case)
    text = format_debug_report(report)
    assert "Failure: tool_call_failure" in text
    assert "Evidence:" in text
    assert "Fix:" in text
