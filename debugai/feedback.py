"""Confidence feedback tracker.

Deterministic confidence gets better when users tell us whether a diagnosis was
right and whether the fix worked. This tracker is intentionally tiny and can be
used by the SDK, server, or offline analysis.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class FeedbackEvent:
    diagnosis_id: str
    failure: str
    accepted: bool
    fix_worked: bool | None = None
    confidence: float | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FeedbackTracker:
    def __init__(self, events: list[dict[str, Any]] | None = None):
        self.events = [FeedbackEvent(**e) for e in (events or [])]

    def record(self, event: FeedbackEvent | dict[str, Any]) -> FeedbackEvent:
        if isinstance(event, dict):
            event = FeedbackEvent(**event)
        self.events.append(event)
        return event

    def stats(self) -> dict[str, Any]:
        by_failure: dict[str, Counter[str]] = defaultdict(Counter)
        for event in self.events:
            c = by_failure[event.failure]
            c["total"] += 1
            c["accepted"] += 1 if event.accepted else 0
            c["rejected"] += 0 if event.accepted else 1
            if event.fix_worked is True:
                c["fix_worked"] += 1
            elif event.fix_worked is False:
                c["fix_failed"] += 1
        out = {}
        for failure, c in by_failure.items():
            total = c["total"] or 1
            fix_total = c["fix_worked"] + c["fix_failed"]
            out[failure] = {
                **dict(c),
                "accept_rate": round(c["accepted"] / total, 4),
                "fix_success_rate": round(c["fix_worked"] / fix_total, 4) if fix_total else None,
            }
        return {"total": len(self.events), "by_failure": out}
