"""In-memory diagnosis store with JSON persistence (Step 6 MVP).

The architecture calls for PostgreSQL at scale; for the MVP a process-local
ring buffer persisted to a JSON file is enough to drive the dashboard and
survive restarts.
"""

from __future__ import annotations

import json
import os
import threading
from collections import Counter
from pathlib import Path

from server.paths import data_path

_DATA = data_path("diagnoses.json")
_MAX = 500


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + rename so a crash mid-write can't corrupt the
    store (a partial JSON file would otherwise be silently reset on load)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


class DiagnosisStore:
    def __init__(self, path: Path = _DATA, maxlen: int = _MAX):
        self._path = path
        self._max = maxlen
        self._lock = threading.Lock()
        self._items: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text())
            return data[-self._max:] if isinstance(data, list) else []
        except Exception:  # missing / corrupt / unreadable → start clean
            return []

    def _persist(self) -> None:
        _atomic_write(self._path, json.dumps(self._items[-self._max:], indent=2))

    def add(self, record: dict) -> dict:
        with self._lock:
            self._items.append(record)
            del self._items[:-self._max]
            self._persist()
        return record

    def list(self, owner: str | None = None, failure: str | None = None,
             limit: int = 100) -> list[dict]:
        with self._lock:
            items = list(reversed(self._items))
        if owner is not None:
            items = [r for r in items if r.get("owner") == owner]
        if failure:
            if failure == "healthy":
                items = [r for r in items if r["diagnosis"].get("healthy")]
            else:
                items = [
                    r for r in items
                    if (r["diagnosis"].get("primary") or {}).get("failure") == failure
                ]
        return items[:limit]

    def get(self, diagnosis_id: str, owner: str | None = None) -> dict | None:
        with self._lock:
            for r in self._items:
                if r.get("id") == diagnosis_id and (owner is None or r.get("owner") == owner):
                    return r
        return None

    def stats(self, owner: str | None = None) -> dict:
        with self._lock:
            items = [r for r in self._items if owner is None or r.get("owner") == owner]
        counts: Counter = Counter()
        for r in items:
            d = r["diagnosis"]
            key = "healthy" if d.get("healthy") else (d.get("primary") or {}).get(
                "failure", "unknown"
            )
            counts[key] += 1
        total = len(items)
        failing = total - counts.get("healthy", 0)
        return {
            "total": total,
            "failing": failing,
            "healthy": counts.get("healthy", 0),
            "by_failure": dict(counts),
        }

    def purge(self, owner: str) -> None:
        with self._lock:
            self._items = [r for r in self._items if r.get("owner") != owner]
            self._persist()

    def clear(self) -> None:
        with self._lock:
            self._items = []
            self._persist()


_TRACES = data_path("traces.json")


class TraceStore:
    """Observability trace store (Langfuse-style) with JSON persistence."""

    def __init__(self, path: Path = _TRACES, maxlen: int = _MAX):
        self._path = path
        self._max = maxlen
        self._lock = threading.Lock()
        self._items: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text())
            return data[-self._max:] if isinstance(data, list) else []
        except Exception:  # missing / corrupt / unreadable → start clean
            return []

    def _persist(self) -> None:
        _atomic_write(self._path, json.dumps(self._items[-self._max:]))

    def add(self, trace: dict) -> dict:
        with self._lock:
            self._items.append(trace)
            del self._items[:-self._max]
            self._persist()
        return trace

    def get(self, trace_id: str, owner: str | None = None) -> dict | None:
        with self._lock:
            for t in self._items:
                if t.get("id") == trace_id and (owner is None or t.get("owner") == owner):
                    return t
        return None

    def list(self, owner: str | None = None, session: str | None = None,
             status: str | None = None, limit: int = 100) -> list[dict]:
        with self._lock:
            items = list(reversed(self._items))
        if owner is not None:
            items = [t for t in items if t.get("owner") == owner]
        if session is not None:
            items = [t for t in items if (t.get("session_id") or "") == session]
        if status:
            items = [t for t in items if t.get("status") == status]
        return items[:limit]

    def sessions(self, owner: str | None = None) -> list[dict]:
        with self._lock:
            items = [t for t in self._items if owner is None or t.get("owner") == owner]
        groups: dict[str, dict] = {}
        for t in items:
            sid = t.get("session_id") or "(no session)"
            g = groups.setdefault(sid, {"session_id": sid, "traces": 0, "failing": 0,
                                        "total_tokens": 0, "cost_usd": 0.0, "last": None})
            g["traces"] += 1
            g["failing"] += 1 if t.get("status") == "failing" else 0
            g["total_tokens"] += t.get("total_tokens", 0)
            g["cost_usd"] = round(g["cost_usd"] + t.get("cost_usd", 0.0), 6)
            g["last"] = t.get("timestamp") or g["last"]
        return sorted(groups.values(), key=lambda g: g["traces"], reverse=True)

    def stats(self, owner: str | None = None) -> dict:
        with self._lock:
            items = [t for t in self._items if owner is None or t.get("owner") == owner]
        n = len(items)
        lat = sorted(t.get("duration_ms", 0) for t in items)
        tokens = sum(t.get("total_tokens", 0) for t in items)
        cost = round(sum(t.get("cost_usd", 0.0) for t in items), 6)
        failing = sum(1 for t in items if t.get("status") == "failing")

        def pct(p):
            if not lat:
                return 0
            return round(lat[min(len(lat) - 1, int(len(lat) * p))], 1)

        return {
            "traces": n, "failing": failing,
            "sessions": len({t.get("session_id") or "(no session)" for t in items}),
            "total_tokens": tokens, "cost_usd": cost,
            "latency_p50_ms": pct(0.50), "latency_p95_ms": pct(0.95),
        }

    def purge(self, owner: str) -> None:
        with self._lock:
            self._items = [t for t in self._items if t.get("owner") != owner]
            self._persist()

    def clear(self) -> None:
        with self._lock:
            self._items = []
            self._persist()
