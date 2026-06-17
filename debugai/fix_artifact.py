"""Executable fix artifacts.

The fix loop already proposes/verifies a candidate. This module turns the
diagnosis + fix into a portable regression artifact that teams can save in CI.
"""

from __future__ import annotations

from typing import Any

from debugai.schema import CaptureRecord


def regression_artifact(diagnosis: dict[str, Any], record: CaptureRecord,
                        fix_report: dict[str, Any] | None = None) -> dict[str, Any]:
    primary = diagnosis.get("primary") or {}
    failure = primary.get("failure")
    test_results = (fix_report or {}).get("test_results") or []
    tests = []
    if test_results:
        for tr in test_results:
            tests.append({
                "input": tr.get("input"),
                "category": tr.get("category", "regression"),
                "must_contain": tr.get("must_contain", []),
                "must_not_contain": tr.get("must_not_contain", []),
                "runs": tr.get("runs", 1),
            })
    else:
        tests.append({
            "input": record.user_prompt,
            "category": "regression",
            "must_not_contain": [],
            "must_contain": [],
            "runs": 1,
        })

    return {
        "name": f"debugai_{failure or 'healthy'}_regression",
        "failure": failure,
        "expected_after": {
            "healthy": True,
            "must_not_fail_as": failure,
            "max_confidence": 0.30,
        },
        "case": {
            "prompt": record.user_prompt,
            "system_prompt": record.system_prompt,
            "chunks": record.retrieved_chunks,
            "similarity_scores": record.similarity_scores,
            "retrieval_query": record.retrieval_query,
            "temperature": record.temperature,
            "response_schema": record.response_schema,
            "tools_expected": record.tools_expected,
        },
        "tests": tests,
        "pytest_snippet": (
            "def test_debugai_regression():\n"
            "    from debugai import analyze\n"
            "    result = analyze(prompt=CASE['prompt'], output=rerun_app(CASE), "
            "chunks=CASE.get('chunks'), similarity_scores=CASE.get('similarity_scores'), "
            "system_prompt=CASE.get('system_prompt', ''), explain_with_llm=False)\n"
            f"    assert result['healthy'] or result['primary']['failure'] != {failure!r}\n"
        ),
    }
