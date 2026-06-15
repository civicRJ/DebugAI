"""Database abstraction — SQLite (default) or PostgreSQL (when DATABASE_URL is set).

SQLAlchemy Core is used for PostgreSQL so connection pooling and dialect
differences are handled automatically. SQLite path is kept for local dev:
no Docker, no services required.

Usage:
    from server.db import get_engine, DATABASE_URL
    engine = get_engine()
"""

from __future__ import annotations

import os

DATABASE_URL: str | None = os.environ.get("DATABASE_URL")


def get_engine():
    """Return a SQLAlchemy engine. Postgres when DATABASE_URL is set, else SQLite."""
    if DATABASE_URL:
        from sqlalchemy import create_engine
        return create_engine(
            DATABASE_URL,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,    # verify connections before use
            pool_recycle=1800,     # recycle connections every 30 min
        )
    # SQLite fallback for local dev — stored in DATA_DIR/debugai.db
    from pathlib import Path
    from sqlalchemy import create_engine
    from server.paths import DATA_DIR
    return create_engine(
        f"sqlite:///{DATA_DIR / 'debugai.db'}",
        connect_args={"check_same_thread": False},
    )


def backend_name() -> str:
    """Return the active database backend name without exposing credentials."""
    return "postgres" if DATABASE_URL else "sqlite"


def status() -> dict:
    """Check database connectivity for health/debug endpoints."""
    from sqlalchemy import text
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"backend": backend_name(), "connected": True}
    except Exception as e:
        return {"backend": backend_name(), "connected": False, "error": e.__class__.__name__}
