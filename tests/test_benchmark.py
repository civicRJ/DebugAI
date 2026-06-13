"""Quality floor: the rule engine must stay >= 80% on the combined labeled set
(seed + held-out eval). Guards against detector regressions."""

import json
from pathlib import Path

from debugai import analyze

DATA = Path(__file__).resolve().parent / "dataset"


def _accuracy(files):
    cases = [c for f in files for c in json.loads((DATA / f).read_text())["cases"]]
    correct = 0
    for c in cases:
        kw = {k: v for k, v in c.items() if k not in ("id", "expected", "_comment")}
        r = analyze(explain_with_llm=False, **kw)
        got = "healthy" if r["healthy"] else r["primary"]["failure"]
        correct += got == c["expected"]
    return correct, len(cases)


def test_combined_accuracy_floor():
    correct, n = _accuracy(["failures.json", "eval.json"])
    assert correct / n >= 0.80, f"engine accuracy {correct}/{n} below 80% floor"
