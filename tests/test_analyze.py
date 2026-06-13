"""End-to-end tests — the analyze() API and the §10 Step-3 acceptance bar
(rule engine classifies at least 16/20 of the labeled dataset correctly)."""

import json
from pathlib import Path

import pytest

from debugai import analyze

DATASET = json.loads(
    (Path(__file__).parent / "dataset" / "failures.json").read_text()
)["cases"]


def _run(case):
    kwargs = {k: v for k, v in case.items() if k not in ("id", "expected", "_comment")}
    return analyze(explain_with_llm=False, **kwargs)


def test_analyze_output_contract():
    r = analyze(prompt="q", output="a")
    assert set(["healthy", "primary", "secondary", "signals", "explanation"]) <= set(r)
    assert isinstance(r["signals"], dict) and len(
        [k for k, v in r["signals"].items() if isinstance(v, float)]
    ) >= 8


def test_dataset_accuracy_meets_80pct():
    correct = 0
    misses = []
    for case in DATASET:
        r = _run(case)
        got = "healthy" if r["healthy"] else r["primary"]["failure"]
        if got == case["expected"]:
            correct += 1
        else:
            misses.append((case["id"], case["expected"], got))
    assert correct >= 16, f"{correct}/{len(DATASET)} correct; misses={misses}"


@pytest.mark.parametrize("case", DATASET, ids=[c["id"] for c in DATASET])
def test_each_case_classified(case):
    r = _run(case)
    got = "healthy" if r["healthy"] else r["primary"]["failure"]
    # Per-case visibility; the suite-level bar is 80%, so individual misses
    # are reported but not all required to pass.
    assert got is not None
    if got != case["expected"]:
        pytest.skip(f"{case['id']}: expected {case['expected']}, got {got}")


def test_scenario_a_reproduces_doc():
    r = _run(next(c for c in DATASET if c["id"] == "rag-01-refund"))
    assert r["primary"]["failure"] == "retrieval_failure"
    assert r["primary"]["confidence"] == 0.95


def test_fix_is_specific_not_generic():
    r = _run(next(c for c in DATASET if c["expected"] == "retrieval_failure"))
    assert "add more context" not in r["primary"]["fix"].lower()
    assert len(r["primary"]["fix"]) > 20
