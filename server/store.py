"""Diagnosis and trace stores — JSON file (dev) or PostgreSQL (prod).

When DATABASE_URL is set (see server/db.py), stores use SQLAlchemy with
PostgreSQL and the rolling 500-item window becomes a SQL LIMIT. When
DATABASE_URL is not set, the existing JSON file stores are used so local
dev works with zero services.
"""

from __future__ import annotations

import json
import os
import time
import threading
import uuid
from collections import Counter
from pathlib import Path

from server.db import DATABASE_URL
from server.paths import data_path

_DATA = data_path("diagnoses.json")
_TRACES = data_path("traces.json")
_LEADS = data_path("leads.json")
_FEEDBACK = data_path("feedback.json")
_TRACTION = data_path("traction_interviews.json")
_MAX = 500


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _haystack(record: dict) -> str:
    inp = record.get("input") or {}
    primary = (record.get("diagnosis") or {}).get("primary") or {}
    parts = [inp.get("prompt"), inp.get("output"), record.get("issue"),
             record.get("label"), primary.get("failure")]
    return " ".join(p for p in parts if p).lower()


# ──────────────────────────────────────────────────────────────────────────────
# JSON-based stores (local dev / no DATABASE_URL)
# ──────────────────────────────────────────────────────────────────────────────

class _JsonDiagnosisStore:
    def __init__(self, path: Path = _DATA, maxlen: int = _MAX):
        self._path = path
        self._max = maxlen
        self._lock = threading.Lock()
        self._items: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text())
            return data[-self._max:] if isinstance(data, list) else []
        except Exception:
            return []

    def _persist(self) -> None:
        _atomic_write(self._path, json.dumps(self._items[-self._max:], indent=2))

    def add(self, record: dict) -> dict:
        with self._lock:
            self._items.append(record)
            del self._items[:-self._max]
            self._persist()
        return record

    def get(self, diagnosis_id: str, owner: str | None = None) -> dict | None:
        with self._lock:
            for r in self._items:
                if r.get("id") == diagnosis_id and (owner is None or r.get("owner") == owner):
                    return r
        return None

    def list(self, owner: str | None = None, failure: str | None = None,
             q: str | None = None, limit: int = 100) -> list[dict]:
        with self._lock:
            items = list(reversed(self._items))
        if owner is not None:
            items = [r for r in items if r.get("owner") == owner]
        if failure:
            if failure == "healthy":
                items = [r for r in items if r["diagnosis"].get("healthy")]
            else:
                items = [r for r in items if (r["diagnosis"].get("primary") or {}).get("failure") == failure]
        if q:
            ql = q.lower()
            items = [r for r in items if ql in _haystack(r)]
        return items[:limit]

    def stats(self, owner: str | None = None) -> dict:
        with self._lock:
            items = [r for r in self._items if owner is None or r.get("owner") == owner]
        counts: Counter = Counter()
        for r in items:
            d = r["diagnosis"]
            key = "healthy" if d.get("healthy") else (d.get("primary") or {}).get("failure", "unknown")
            counts[key] += 1
        total = len(items)
        return {"total": total, "failing": total - counts.get("healthy", 0),
                "healthy": counts.get("healthy", 0), "by_failure": dict(counts)}

    def purge(self, owner: str) -> None:
        with self._lock:
            self._items = [r for r in self._items if r.get("owner") != owner]
            self._persist()

    def clear(self) -> None:
        with self._lock:
            self._items = []
            self._persist()


class _JsonTraceStore:
    def __init__(self, path: Path = _TRACES, maxlen: int = _MAX):
        self._path = path
        self._max = maxlen
        self._lock = threading.Lock()
        self._items: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text())
            return data[-self._max:] if isinstance(data, list) else []
        except Exception:
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
        def pct(p):
            if not lat: return 0
            return round(lat[min(len(lat) - 1, int(len(lat) * p))], 1)
        return {
            "traces": n, "failing": sum(1 for t in items if t.get("status") == "failing"),
            "sessions": len({t.get("session_id") or "(no session)" for t in items}),
            "total_tokens": sum(t.get("total_tokens", 0) for t in items),
            "cost_usd": round(sum(t.get("cost_usd", 0.0) for t in items), 6),
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


class _JsonLeadStore:
    def __init__(self, path: Path = _LEADS, maxlen: int = 2_000):
        self._path = path
        self._max = maxlen
        self._lock = threading.Lock()
        self._items: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text())
            return data[-self._max:] if isinstance(data, list) else []
        except Exception:
            return []

    def _persist(self) -> None:
        _atomic_write(self._path, json.dumps(self._items[-self._max:], indent=2))

    def add(self, lead: dict) -> dict:
        email = (lead.get("email") or "").strip().lower()
        now = time.time()
        record = {
            "email": email,
            "name": (lead.get("name") or "").strip(),
            "company": (lead.get("company") or "").strip(),
            "role": (lead.get("role") or "").strip(),
            "use_case": (lead.get("use_case") or "").strip(),
            "source": (lead.get("source") or "landing").strip()[:80],
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            for item in self._items:
                if item.get("email") == email:
                    item.update({k: v for k, v in record.items() if v or k in {"updated_at", "source"}})
                    item["updated_at"] = now
                    self._persist()
                    return item
            self._items.append(record)
            del self._items[:-self._max]
            self._persist()
        return record

    def list(self, limit: int = 100) -> list[dict]:
        with self._lock:
            return list(reversed(self._items))[:limit]

    def stats(self) -> dict:
        with self._lock:
            items = list(self._items)
        return {
            "total": len(items),
            "by_role": dict(Counter(i.get("role") or "unknown" for i in items)),
            "recent": list(reversed(items))[:10],
        }

    def clear(self) -> None:
        with self._lock:
            self._items = []
            self._persist()


class _JsonFeedbackStore:
    def __init__(self, path: Path = _FEEDBACK, maxlen: int = 5_000):
        self._path = path
        self._max = maxlen
        self._lock = threading.Lock()
        self._items: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text())
            return data[-self._max:] if isinstance(data, list) else []
        except Exception:
            return []

    def _persist(self) -> None:
        _atomic_write(self._path, json.dumps(self._items[-self._max:], indent=2))

    def add(self, item: dict) -> dict:
        record = {**item, "created_at": item.get("created_at") or time.time()}
        with self._lock:
            self._items.append(record)
            del self._items[:-self._max]
            self._persist()
        return record

    def list(self, owner: str | None = None, limit: int = 500) -> list[dict]:
        with self._lock:
            items = list(reversed(self._items))
        if owner is not None:
            items = [i for i in items if i.get("owner") == owner]
        return items[:limit]

    def stats(self, owner: str | None = None) -> dict:
        items = self.list(owner=owner, limit=self._max)
        by_failure: dict[str, Counter] = {}
        for item in items:
            failure = item.get("failure") or "unknown"
            c = by_failure.setdefault(failure, Counter())
            c["total"] += 1
            c["accepted"] += 1 if item.get("accepted") else 0
            c["rejected"] += 0 if item.get("accepted") else 1
            if item.get("fix_worked") is True:
                c["fix_worked"] += 1
            elif item.get("fix_worked") is False:
                c["fix_failed"] += 1
        return {
            "total": len(items),
            "by_failure": {
                failure: {
                    **dict(c),
                    "accept_rate": round(c["accepted"] / (c["total"] or 1), 4),
                    "fix_success_rate": (
                        round(c["fix_worked"] / (c["fix_worked"] + c["fix_failed"]), 4)
                        if c["fix_worked"] + c["fix_failed"] else None
                    ),
                }
                for failure, c in by_failure.items()
            },
        }

    def purge(self, owner: str) -> None:
        with self._lock:
            self._items = [i for i in self._items if i.get("owner") != owner]
            self._persist()

    def clear(self) -> None:
        with self._lock:
            self._items = []
            self._persist()


class _JsonTractionStore:
    def __init__(self, path: Path = _TRACTION, maxlen: int = 5_000):
        self._path = path
        self._max = maxlen
        self._lock = threading.Lock()
        self._items: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self._path.read_text())
            return data[-self._max:] if isinstance(data, list) else []
        except Exception:
            return []

    def _persist(self) -> None:
        _atomic_write(self._path, json.dumps(self._items[-self._max:], indent=2))

    @staticmethod
    def _record(item: dict, existing: dict | None = None) -> dict:
        now = time.time()
        base = dict(existing or {})
        base.update({
            "lead_email": (item.get("lead_email") or "").strip().lower(),
            "contact_name": (item.get("contact_name") or "").strip(),
            "company": (item.get("company") or "").strip(),
            "source": (item.get("source") or "manual").strip()[:80],
            "failure_summary": (item.get("failure_summary") or "").strip(),
            "failure_type": (item.get("failure_type") or "").strip(),
            "diagnosis_accepted": item.get("diagnosis_accepted"),
            "fix_worked": item.get("fix_worked"),
            "would_pay": item.get("would_pay"),
            "repeat_usage": item.get("repeat_usage"),
            "status": (item.get("status") or "new").strip(),
            "notes": (item.get("notes") or "").strip(),
            "updated_at": now,
        })
        base.setdefault("id", item.get("id") or uuid.uuid4().hex)
        base.setdefault("created_at", now)
        return base

    def add(self, item: dict) -> dict:
        record = self._record(item)
        with self._lock:
            self._items.append(record)
            del self._items[:-self._max]
            self._persist()
        return record

    def update(self, item_id: str, item: dict) -> dict | None:
        with self._lock:
            for idx, existing in enumerate(self._items):
                if existing.get("id") == item_id:
                    self._items[idx] = self._record(item, existing=existing)
                    self._persist()
                    return self._items[idx]
        return None

    def list(self, limit: int = 100) -> list[dict]:
        with self._lock:
            return list(reversed(self._items))[:limit]

    def stats(self) -> dict:
        items = self.list(limit=self._max)
        total = len(items)
        submitted = sum(1 for i in items if i.get("failure_summary"))
        accepted = sum(1 for i in items if i.get("diagnosis_accepted") is True)
        fixes = [i for i in items if i.get("fix_worked") is not None]
        would_pay = sum(1 for i in items if i.get("would_pay") is True)
        repeat_usage = sum(1 for i in items if i.get("repeat_usage") is True)
        by_status = Counter(i.get("status") or "new" for i in items)
        by_failure = Counter(i.get("failure_type") or "unknown" for i in items)
        return {
            "total": total,
            "failures_submitted": submitted,
            "diagnosis_accepted": accepted,
            "fix_worked": sum(1 for i in fixes if i.get("fix_worked") is True),
            "would_pay": would_pay,
            "repeat_usage": repeat_usage,
            "accept_rate": round(accepted / (submitted or 1), 4),
            "fix_success_rate": round(sum(1 for i in fixes if i.get("fix_worked") is True) / (len(fixes) or 1), 4),
            "would_pay_rate": round(would_pay / (total or 1), 4),
            "by_status": dict(by_status),
            "by_failure": dict(by_failure),
            "recent": items[:25],
        }

    def clear(self) -> None:
        with self._lock:
            self._items = []
            self._persist()


# ──────────────────────────────────────────────────────────────────────────────
# PostgreSQL-backed stores (when DATABASE_URL is set)
# ──────────────────────────────────────────────────────────────────────────────

class _PgDiagnosisStore:
    """PostgreSQL-backed diagnosis store.  Schema created on first use.
    Keeps the same public API as _JsonDiagnosisStore."""

    def __init__(self):
        from server.db import get_engine
        from sqlalchemy import text
        self._engine = get_engine()
        self._text = text
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(self._text("""
                CREATE TABLE IF NOT EXISTS diagnoses (
                    id          TEXT        PRIMARY KEY,
                    owner       TEXT        NOT NULL DEFAULT '',
                    timestamp   TEXT,
                    label       TEXT,
                    issue       TEXT,
                    session_id  TEXT,
                    input_data  TEXT        NOT NULL DEFAULT '{}',
                    diagnosis   TEXT        NOT NULL DEFAULT '{}',
                    ui_data     TEXT
                )
            """))
            conn.execute(self._text(
                "CREATE INDEX IF NOT EXISTS diagnoses_owner_ts ON diagnoses (owner, timestamp DESC)"))

    def _row_to_dict(self, row) -> dict:
        return {
            "id": row.id, "owner": row.owner, "timestamp": row.timestamp,
            "label": row.label, "issue": row.issue,
            "input": json.loads(row.input_data or "{}"),
            "diagnosis": json.loads(row.diagnosis or "{}"),
            "ui": json.loads(row.ui_data or "null"),
        }

    def add(self, record: dict) -> dict:
        with self._engine.begin() as conn:
            conn.execute(self._text("""
                INSERT INTO diagnoses (id, owner, timestamp, label, issue, session_id,
                    input_data, diagnosis, ui_data)
                VALUES (:id, :owner, :ts, :label, :issue, :session_id,
                    :input_data, :diagnosis, :ui_data)
                ON CONFLICT (id) DO NOTHING
            """), {
                "id": record.get("id"), "owner": record.get("owner", ""),
                "ts": record.get("timestamp"), "label": record.get("label"),
                "issue": record.get("issue"),
                "session_id": record.get("input", {}).get("session_id"),
                "input_data": json.dumps(record.get("input", {})),
                "diagnosis": json.dumps(record.get("diagnosis", {})),
                "ui_data": json.dumps(record.get("ui")),
            })
            # Rolling window: delete oldest beyond MAX per owner
            owner = record.get("owner", "")
            conn.execute(self._text("""
                DELETE FROM diagnoses WHERE id IN (
                    SELECT id FROM diagnoses WHERE owner=:owner
                    ORDER BY timestamp DESC OFFSET :max
                )
            """), {"owner": owner, "max": _MAX})
        return record

    def get(self, diagnosis_id: str, owner: str | None = None) -> dict | None:
        with self._engine.connect() as conn:
            q = "SELECT * FROM diagnoses WHERE id=:id"
            params: dict = {"id": diagnosis_id}
            if owner is not None:
                q += " AND owner=:owner"; params["owner"] = owner
            row = conn.execute(self._text(q), params).fetchone()
        return self._row_to_dict(row) if row else None

    def list(self, owner: str | None = None, failure: str | None = None,
             q: str | None = None, limit: int = 100) -> list[dict]:
        query = "SELECT * FROM diagnoses WHERE 1=1"
        params: dict = {"limit": limit}
        if owner is not None:
            query += " AND owner=:owner"; params["owner"] = owner
        query += " ORDER BY timestamp DESC LIMIT :limit"
        with self._engine.connect() as conn:
            rows = conn.execute(self._text(query), params).fetchall()
        items = [self._row_to_dict(r) for r in rows]
        if failure:
            if failure == "healthy":
                items = [r for r in items if r["diagnosis"].get("healthy")]
            else:
                items = [r for r in items if (r["diagnosis"].get("primary") or {}).get("failure") == failure]
        if q:
            ql = q.lower()
            items = [r for r in items if ql in _haystack(r)]
        return items

    def stats(self, owner: str | None = None) -> dict:
        items = self.list(owner=owner, limit=_MAX)
        counts: Counter = Counter()
        for r in items:
            d = r["diagnosis"]
            key = "healthy" if d.get("healthy") else (d.get("primary") or {}).get("failure", "unknown")
            counts[key] += 1
        total = len(items)
        return {"total": total, "failing": total - counts.get("healthy", 0),
                "healthy": counts.get("healthy", 0), "by_failure": dict(counts)}

    def purge(self, owner: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(self._text("DELETE FROM diagnoses WHERE owner=:owner"), {"owner": owner})

    def clear(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(self._text("DELETE FROM diagnoses"))


class _PgTraceStore:
    """PostgreSQL-backed trace store. Same public API as _JsonTraceStore."""

    def __init__(self):
        from server.db import get_engine
        from sqlalchemy import text
        self._engine = get_engine()
        self._text = text
        self._max = 5_000
        self._init_schema()

    def _init_schema(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(self._text("""
                CREATE TABLE IF NOT EXISTS traces (
                    id          TEXT PRIMARY KEY,
                    owner       TEXT NOT NULL DEFAULT '',
                    timestamp   TEXT,
                    session_id  TEXT,
                    status      TEXT,
                    model       TEXT,
                    duration_ms REAL,
                    total_tokens INTEGER,
                    cost_usd    REAL,
                    spans       TEXT,
                    scores      TEXT,
                    metadata    TEXT
                )
            """))
            conn.execute(self._text(
                "CREATE INDEX IF NOT EXISTS traces_owner_ts ON traces (owner, timestamp DESC)"))

    def _row_to_dict(self, row) -> dict:
        return {
            "id": row.id, "owner": row.owner, "timestamp": row.timestamp,
            "session_id": row.session_id, "status": row.status, "model": row.model,
            "duration_ms": row.duration_ms, "total_tokens": row.total_tokens,
            "cost_usd": row.cost_usd,
            "spans": json.loads(row.spans or "[]"),
            "scores": json.loads(row.scores or "[]"),
            "metadata": json.loads(row.metadata or "{}"),
        }

    def add(self, trace: dict) -> dict:
        with self._engine.begin() as conn:
            conn.execute(self._text("""
                INSERT INTO traces (id,owner,timestamp,session_id,status,model,
                    duration_ms,total_tokens,cost_usd,spans,scores,metadata)
                VALUES (:id,:owner,:ts,:session_id,:status,:model,
                    :dur,:tokens,:cost,:spans,:scores,:meta)
                ON CONFLICT (id) DO NOTHING
            """), {
                "id": trace.get("id"), "owner": trace.get("owner", ""),
                "ts": trace.get("timestamp"),
                "session_id": trace.get("session_id"),
                "status": trace.get("status"), "model": trace.get("model"),
                "dur": trace.get("duration_ms"), "tokens": trace.get("total_tokens"),
                "cost": trace.get("cost_usd"),
                "spans": json.dumps(trace.get("spans", [])),
                "scores": json.dumps(trace.get("scores", [])),
                "meta": json.dumps(trace.get("metadata", {})),
            })
            owner = trace.get("owner", "")
            conn.execute(self._text("""
                DELETE FROM traces WHERE id IN (
                    SELECT id FROM traces WHERE owner=:owner
                    ORDER BY timestamp DESC OFFSET :max
                )
            """), {"owner": owner, "max": _MAX})
        return trace

    def get(self, trace_id: str, owner: str | None = None) -> dict | None:
        with self._engine.connect() as conn:
            q = "SELECT * FROM traces WHERE id=:id"
            params: dict = {"id": trace_id}
            if owner is not None:
                q += " AND owner=:owner"; params["owner"] = owner
            row = conn.execute(self._text(q), params).fetchone()
        return self._row_to_dict(row) if row else None

    def list(self, owner: str | None = None, session: str | None = None,
             status: str | None = None, limit: int = 100) -> list[dict]:
        q = "SELECT * FROM traces WHERE 1=1"
        params: dict = {"limit": limit}
        if owner is not None:
            q += " AND owner=:owner"; params["owner"] = owner
        if session is not None:
            q += " AND session_id=:session"; params["session"] = session
        if status:
            q += " AND status=:status"; params["status"] = status
        q += " ORDER BY timestamp DESC LIMIT :limit"
        with self._engine.connect() as conn:
            rows = conn.execute(self._text(q), params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def sessions(self, owner: str | None = None) -> list[dict]:
        items = self.list(owner=owner, limit=_MAX)
        groups: dict[str, dict] = {}
        for t in items:
            sid = t.get("session_id") or "(no session)"
            g = groups.setdefault(sid, {"session_id": sid, "traces": 0, "failing": 0,
                                        "total_tokens": 0, "cost_usd": 0.0, "last": None})
            g["traces"] += 1
            g["failing"] += 1 if t.get("status") == "failing" else 0
            g["total_tokens"] += t.get("total_tokens") or 0
            g["cost_usd"] = round(g["cost_usd"] + (t.get("cost_usd") or 0.0), 6)
            g["last"] = t.get("timestamp") or g["last"]
        return sorted(groups.values(), key=lambda g: g["traces"], reverse=True)

    def stats(self, owner: str | None = None) -> dict:
        items = self.list(owner=owner, limit=_MAX)
        n = len(items)
        lat = sorted(t.get("duration_ms") or 0 for t in items)
        def pct(p):
            if not lat: return 0
            return round(lat[min(len(lat) - 1, int(len(lat) * p))], 1)
        return {
            "traces": n, "failing": sum(1 for t in items if t.get("status") == "failing"),
            "sessions": len({t.get("session_id") or "(no session)" for t in items}),
            "total_tokens": sum(t.get("total_tokens") or 0 for t in items),
            "cost_usd": round(sum(t.get("cost_usd") or 0.0 for t in items), 6),
            "latency_p50_ms": pct(0.50), "latency_p95_ms": pct(0.95),
        }

    def purge(self, owner: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(self._text("DELETE FROM traces WHERE owner=:owner"), {"owner": owner})

    def clear(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(self._text("DELETE FROM traces"))


class _PgLeadStore:
    def __init__(self):
        from server.db import get_engine
        from sqlalchemy import text
        self._engine = get_engine()
        self._text = text
        self._max = 5_000
        self._init_schema()

    def _init_schema(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(self._text("""
                CREATE TABLE IF NOT EXISTS beta_leads (
                    email      TEXT PRIMARY KEY,
                    name       TEXT NOT NULL DEFAULT '',
                    company    TEXT NOT NULL DEFAULT '',
                    role       TEXT NOT NULL DEFAULT '',
                    use_case   TEXT NOT NULL DEFAULT '',
                    source     TEXT NOT NULL DEFAULT 'landing',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """))
            conn.execute(self._text(
                "CREATE INDEX IF NOT EXISTS beta_leads_updated ON beta_leads (updated_at DESC)"))

    @staticmethod
    def _row_to_dict(row) -> dict:
        return {
            "email": row.email, "name": row.name, "company": row.company,
            "role": row.role, "use_case": row.use_case, "source": row.source,
            "created_at": row.created_at, "updated_at": row.updated_at,
        }

    def add(self, lead: dict) -> dict:
        now = time.time()
        record = {
            "email": (lead.get("email") or "").strip().lower(),
            "name": (lead.get("name") or "").strip(),
            "company": (lead.get("company") or "").strip(),
            "role": (lead.get("role") or "").strip(),
            "use_case": (lead.get("use_case") or "").strip(),
            "source": (lead.get("source") or "landing").strip()[:80],
            "created_at": now,
            "updated_at": now,
        }
        with self._engine.begin() as conn:
            conn.execute(self._text("""
                INSERT INTO beta_leads (email,name,company,role,use_case,source,created_at,updated_at)
                VALUES (:email,:name,:company,:role,:use_case,:source,:created_at,:updated_at)
                ON CONFLICT (email) DO UPDATE SET
                    name=excluded.name,
                    company=excluded.company,
                    role=excluded.role,
                    use_case=excluded.use_case,
                    source=excluded.source,
                    updated_at=excluded.updated_at
            """), record)
        return record

    def list(self, limit: int = 100) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(self._text(
                "SELECT * FROM beta_leads ORDER BY updated_at DESC LIMIT :limit"),
                {"limit": limit}).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def stats(self) -> dict:
        items = self.list(limit=2_000)
        return {
            "total": len(items),
            "by_role": dict(Counter(i.get("role") or "unknown" for i in items)),
            "recent": items[:10],
        }

    def clear(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(self._text("DELETE FROM beta_leads"))


class _PgTractionStore:
    def __init__(self):
        from server.db import get_engine
        from sqlalchemy import text
        self._engine = get_engine()
        self._text = text
        self._max = 5_000
        self._init_schema()

    def _init_schema(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(self._text("""
                CREATE TABLE IF NOT EXISTS traction_interviews (
                    id                  TEXT PRIMARY KEY,
                    lead_email          TEXT NOT NULL DEFAULT '',
                    contact_name        TEXT NOT NULL DEFAULT '',
                    company             TEXT NOT NULL DEFAULT '',
                    source              TEXT NOT NULL DEFAULT 'manual',
                    failure_summary     TEXT NOT NULL DEFAULT '',
                    failure_type        TEXT NOT NULL DEFAULT '',
                    diagnosis_accepted  BOOLEAN,
                    fix_worked          BOOLEAN,
                    would_pay           BOOLEAN,
                    repeat_usage        BOOLEAN,
                    status              TEXT NOT NULL DEFAULT 'new',
                    notes               TEXT NOT NULL DEFAULT '',
                    created_at          REAL NOT NULL,
                    updated_at          REAL NOT NULL
                )
            """))
            conn.execute(self._text(
                "CREATE INDEX IF NOT EXISTS traction_interviews_updated ON traction_interviews (updated_at DESC)"))

    @staticmethod
    def _clean(item: dict, item_id: str | None = None) -> dict:
        now = time.time()
        return {
            "id": item_id or item.get("id") or uuid.uuid4().hex,
            "lead_email": (item.get("lead_email") or "").strip().lower(),
            "contact_name": (item.get("contact_name") or "").strip(),
            "company": (item.get("company") or "").strip(),
            "source": (item.get("source") or "manual").strip()[:80],
            "failure_summary": (item.get("failure_summary") or "").strip(),
            "failure_type": (item.get("failure_type") or "").strip(),
            "diagnosis_accepted": item.get("diagnosis_accepted"),
            "fix_worked": item.get("fix_worked"),
            "would_pay": item.get("would_pay"),
            "repeat_usage": item.get("repeat_usage"),
            "status": (item.get("status") or "new").strip(),
            "notes": (item.get("notes") or "").strip(),
            "created_at": item.get("created_at") or now,
            "updated_at": now,
        }

    @staticmethod
    def _row_to_dict(row) -> dict:
        return {
            "id": row.id,
            "lead_email": row.lead_email,
            "contact_name": row.contact_name,
            "company": row.company,
            "source": row.source,
            "failure_summary": row.failure_summary,
            "failure_type": row.failure_type,
            "diagnosis_accepted": row.diagnosis_accepted,
            "fix_worked": row.fix_worked,
            "would_pay": row.would_pay,
            "repeat_usage": row.repeat_usage,
            "status": row.status,
            "notes": row.notes,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def add(self, item: dict) -> dict:
        record = self._clean(item)
        with self._engine.begin() as conn:
            conn.execute(self._text("""
                INSERT INTO traction_interviews (
                    id,lead_email,contact_name,company,source,failure_summary,
                    failure_type,diagnosis_accepted,fix_worked,would_pay,
                    repeat_usage,status,notes,created_at,updated_at
                )
                VALUES (
                    :id,:lead_email,:contact_name,:company,:source,:failure_summary,
                    :failure_type,:diagnosis_accepted,:fix_worked,:would_pay,
                    :repeat_usage,:status,:notes,:created_at,:updated_at
                )
            """), record)
        return record

    def update(self, item_id: str, item: dict) -> dict | None:
        existing = None
        with self._engine.connect() as conn:
            row = conn.execute(self._text(
                "SELECT * FROM traction_interviews WHERE id=:id"), {"id": item_id}).fetchone()
            if row:
                existing = self._row_to_dict(row)
        if existing is None:
            return None
        record = self._clean({**existing, **item, "created_at": existing.get("created_at")}, item_id=item_id)
        with self._engine.begin() as conn:
            conn.execute(self._text("""
                UPDATE traction_interviews SET
                    lead_email=:lead_email,
                    contact_name=:contact_name,
                    company=:company,
                    source=:source,
                    failure_summary=:failure_summary,
                    failure_type=:failure_type,
                    diagnosis_accepted=:diagnosis_accepted,
                    fix_worked=:fix_worked,
                    would_pay=:would_pay,
                    repeat_usage=:repeat_usage,
                    status=:status,
                    notes=:notes,
                    updated_at=:updated_at
                WHERE id=:id
            """), record)
        return record

    def list(self, limit: int = 100) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(self._text(
                "SELECT * FROM traction_interviews ORDER BY updated_at DESC LIMIT :limit"),
                {"limit": limit}).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def stats(self) -> dict:
        return _JsonTractionStore.stats(self)  # type: ignore[misc]

    def clear(self) -> None:
        with self._engine.begin() as conn:
            conn.execute(self._text("DELETE FROM traction_interviews"))


# ──────────────────────────────────────────────────────────────────────────────
# Public constructors — pick the right backend automatically
# ──────────────────────────────────────────────────────────────────────────────

def DiagnosisStore() -> "_JsonDiagnosisStore | _PgDiagnosisStore":
    """Return the appropriate diagnosis store for the current environment."""
    if DATABASE_URL:
        return _PgDiagnosisStore()
    return _JsonDiagnosisStore()


def TraceStore() -> "_JsonTraceStore | _PgTraceStore":
    """Return the appropriate trace store for the current environment."""
    if DATABASE_URL:
        return _PgTraceStore()
    return _JsonTraceStore()


def LeadStore() -> "_JsonLeadStore | _PgLeadStore":
    """Return the beta lead store for traction capture."""
    if DATABASE_URL:
        return _PgLeadStore()
    return _JsonLeadStore()


def FeedbackStore() -> _JsonFeedbackStore:
    return _JsonFeedbackStore()


def TractionStore() -> "_JsonTractionStore | _PgTractionStore":
    """Return the traction interview store for YC/customer discovery metrics."""
    if DATABASE_URL:
        return _PgTractionStore()
    return _JsonTractionStore()
