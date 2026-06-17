"""Failure corpus evaluation.

This module lets teams keep a growing labeled corpus of LLM failures and run it
against the deterministic diagnosis engine. It is intentionally simple JSON so
cases can be copied from production traces, GitHub issues, or customer reports.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from debugai.analyze import analyze
from debugai.report import analyze_kwargs


def load_corpus(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict) and "cases" in data:
        cases = data["cases"]
    elif isinstance(data, list):
        cases = data
    elif isinstance(data, dict):
        cases = [data]
    else:
        raise ValueError("corpus must be a case, a list, or {'cases': [...]}")
    if not all(isinstance(c, dict) for c in cases):
        raise ValueError("every corpus case must be an object")
    return cases


def _expected(case: dict[str, Any]) -> str:
    return (
        case.get("expected_failure")
        or case.get("expected")
        or case.get("failure")
        or "healthy"
    )


def evaluate_corpus(cases: list[dict[str, Any]], *, explain_with_llm: bool = False) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    misses: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    confusion: dict[str, Counter[str]] = defaultdict(Counter)

    for i, case in enumerate(cases):
        label = case.get("id") or case.get("label") or f"case-{i + 1}"
        expected = _expected(case)
        diag = analyze(explain_with_llm=explain_with_llm, **analyze_kwargs(case))
        got = "healthy" if diag.get("healthy") else (diag.get("primary") or {}).get("failure", "unknown")
        ok = got == expected
        counts["correct" if ok else "incorrect"] += 1
        confusion[expected][got] += 1
        row = {
            "id": label,
            "expected": expected,
            "got": got,
            "ok": ok,
            "confidence": None if diag.get("healthy") else (diag.get("primary") or {}).get("confidence"),
        }
        results.append(row)
        if not ok:
            misses.append(row)

    total = len(cases)
    correct = counts["correct"]
    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "misses": misses,
        "results": results,
        "confusion": {k: dict(v) for k, v in confusion.items()},
    }


def evaluate_corpus_file(path: str | Path, *, explain_with_llm: bool = False) -> dict[str, Any]:
    return evaluate_corpus(load_corpus(path), explain_with_llm=explain_with_llm)
