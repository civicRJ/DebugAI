"""Accuracy benchmark for the DebugAI rule engine.

Runs every labeled case through `analyze()` (deterministic, no LLM) and reports
overall accuracy, a confusion matrix, and per-class precision / recall / F1.

    python scripts/benchmark.py                      # failures.json + eval.json
    python scripts/benchmark.py path/to/cases.json   # custom labeled file(s)
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # runnable as a plain script

from debugai import analyze
DEFAULT = [ROOT / "tests" / "dataset" / "failures.json",
           ROOT / "tests" / "dataset" / "eval.json"]


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text()).get("cases", [])


def _predict(case: dict) -> str:
    kw = {k: v for k, v in case.items() if k not in ("id", "expected", "_comment")}
    r = analyze(explain_with_llm=False, **kw)
    return "healthy" if r["healthy"] else r["primary"]["failure"]


def run(paths: list[Path]) -> float:
    cases = [c for p in paths if p.exists() for c in _load(p)]
    if not cases:
        print("no labeled cases found")
        return 0.0
    y_true, y_pred, misses = [], [], []
    for c in cases:
        exp, got = c["expected"], _predict(c)
        y_true.append(exp)
        y_pred.append(got)
        if exp != got:
            misses.append((c.get("id", c.get("label", "?")), exp, got))

    labels = sorted(set(y_true) | set(y_pred))
    n = len(y_true)
    correct = sum(a == b for a, b in zip(y_true, y_pred))
    cm = collections.Counter(zip(y_true, y_pred))

    print(f"\n=== DebugAI benchmark — {n} labeled cases ===\n")
    print(f"Overall accuracy: {correct}/{n} = {correct / n:.1%}\n")

    print("Confusion matrix (rows = expected, cols = predicted):")
    w = max(len(l) for l in labels) + 1
    print(" " * w + " | " + " ".join(f"{l[:6]:>6}" for l in labels))
    for a in labels:
        row = " ".join(f"{cm.get((a, b), 0):>6}" for b in labels)
        print(f"{a:>{w}} | {row}")

    print("\nPer-class precision / recall / F1:")
    print(f"  {'label':<22} {'prec':>6} {'rec':>6} {'f1':>6} {'n':>4}")
    for l in labels:
        tp = cm.get((l, l), 0)
        pred_l = sum(1 for p in y_pred if p == l)
        true_l = sum(1 for t in y_true if t == l)
        prec = tp / pred_l if pred_l else 0.0
        rec = tp / true_l if true_l else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        print(f"  {l:<22} {prec:>6.2f} {rec:>6.2f} {f1:>6.2f} {true_l:>4}")

    if misses:
        print("\nMisclassified:")
        for mid, exp, got in misses:
            print(f"  {mid:<20} expected {exp:<18} got {got}")
    return correct / n


if __name__ == "__main__":
    args = [Path(a) for a in sys.argv[1:]] or DEFAULT
    acc = run(args)
    raise SystemExit(0 if acc >= 0.8 else 1)
