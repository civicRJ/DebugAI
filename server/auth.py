"""Authentication store — users + sessions in SQLite (dev) or PostgreSQL (prod).

Root-cause note (session disappearing in production):
The session cookie is set by _set_session() in app.py.  When deployed behind a
reverse proxy (nginx/Caddy), FastAPI sees the *internal* HTTP scheme even though
the browser communicates over HTTPS.  `secure=request.url.scheme == "https"` then
evaluates to False, and modern browsers silently drop non-Secure cookies on HTTPS
pages.  Fix: honour X-Forwarded-Proto when DEBUGAI_TRUST_PROXY env var is set.
This file (auth.py) is correct — the fix lives in app.py:_set_session().

Storage: uses SQLAlchemy Core so the same code works for SQLite (local dev,
no DATABASE_URL set) and PostgreSQL (production, DATABASE_URL set). Connection
pooling is configured in server/db.py.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from pathlib import Path

import base64

from cryptography.fernet import Fernet
from sqlalchemy import text

from server.db import get_engine


def _fernet() -> Fernet:
    """Return a Fernet cipher keyed from DEBUGAI_KEY_SECRET.
    If unset, derives a deterministic dev key from the DB path — never use in
    production without setting the env var."""
    secret = os.environ.get("DEBUGAI_KEY_SECRET")
    if secret:
        key = base64.urlsafe_b64encode(secret.encode("utf-8").ljust(32, b"\0")[:32])
    else:
        import hashlib
        h = hashlib.sha256(b"debugai-dev-insecure-key-change-in-prod").digest()
        key = base64.urlsafe_b64encode(h)
    return Fernet(key)


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")


_SESSION_TTL = 30 * 24 * 3600  # 30 days
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_N, _R, _P, _DKLEN = 16384, 8, 1, 32


class AuthError(ValueError):
    pass


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt,
                          n=_N, r=_R, p=_P, dklen=_DKLEN).hex()


class AuthStore:
    def __init__(self, db_path=None):
        """db_path is accepted for test fixtures (overrides the default engine)."""
        self._lock = threading.Lock()
        if db_path is not None:
            # Test-only path: use a dedicated SQLite file at db_path.
            from sqlalchemy import create_engine
            self._engine = create_engine(
                f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        else:
            self._engine = get_engine()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    pw_hash TEXT NOT NULL,
                    pw_salt TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS api_tokens (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL,
                    created_at REAL NOT NULL,
                    last_used REAL
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_keys (
                    user_id  TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    key_enc  TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (user_id, provider)
                )
            """))

    @staticmethod
    def _public(row) -> dict:
        return {"id": row.id, "email": row.email, "name": row.name,
                "created_at": row.created_at}

    @staticmethod
    def _validate(email: str, name: str, password: str | None) -> None:
        if not _EMAIL_RE.match((email or "").strip()):
            raise AuthError("Enter a valid email address.")
        if not (name or "").strip():
            raise AuthError("Name is required.")
        if password is not None and len(password) < 8:
            raise AuthError("Password must be at least 8 characters.")

    # ── Users ────────────────────────────────────────────────────────────────
    def is_staff(self, user_id: str) -> bool:
        """Check if a user has staff/admin access."""
        with self._engine.connect() as conn:
            # Staff list from env var — comma-separated user IDs or emails
            staff = set(s.strip() for s in os.environ.get("DEBUGAI_STAFF", "").split(",") if s.strip())
            if not staff:
                return False
            row = conn.execute(text("SELECT email FROM users WHERE id=:id"), {"id": user_id}).fetchone()
            return bool(row and (user_id in staff or row.email in staff))

    def user_count(self) -> int:
        with self._engine.connect() as conn:
            return conn.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0

    def recent_users(self, limit: int = 10) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, email, name, created_at FROM users ORDER BY created_at DESC LIMIT :n"),
                {"n": limit}).fetchall()
        return [{"id": r.id, "email": r.email, "name": r.name, "created_at": r.created_at} for r in rows]

    def register(self, email: str, name: str, password: str) -> dict:
        email = (email or "").strip().lower()
        name = (name or "").strip()
        self._validate(email, name, password)
        uid = secrets.token_hex(8)
        salt = secrets.token_bytes(16)
        with self._lock, self._engine.begin() as conn:
            try:
                conn.execute(text(
                    "INSERT INTO users VALUES (:id,:email,:name,:pw_hash,:pw_salt,:created_at)"
                ), {"id": uid, "email": email, "name": name,
                    "pw_hash": _hash_password(password, salt),
                    "pw_salt": salt.hex(), "created_at": time.time()})
            except Exception as e:
                if "unique" in str(e).lower() or "UNIQUE" in str(e):
                    raise AuthError("An account with that email already exists.")
                raise
            row = conn.execute(text("SELECT * FROM users WHERE id=:id"), {"id": uid}).fetchone()
        return self._public(row)

    def authenticate(self, email: str, password: str) -> dict | None:
        email = (email or "").strip().lower()
        with self._engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM users WHERE email=:email"), {"email": email}).fetchone()
        if row is None:
            _hash_password(password or "", b"0" * 16)
            return None
        actual = _hash_password(password or "", bytes.fromhex(row.pw_salt))
        if not hmac.compare_digest(row.pw_hash, actual):
            return None
        return self._public(row)

    def get_user(self, user_id: str) -> dict | None:
        with self._engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM users WHERE id=:id"), {"id": user_id}).fetchone()
        return self._public(row) if row else None

    def update_user(self, user_id: str, *, name: str | None = None,
                    email: str | None = None, new_password: str | None = None) -> dict:
        with self._lock, self._engine.begin() as conn:
            row = conn.execute(text("SELECT * FROM users WHERE id=:id"), {"id": user_id}).fetchone()
            if row is None:
                raise AuthError("Account not found.")
            new_name = (name if name is not None else row.name).strip()
            new_email = (email if email is not None else row.email).strip().lower()
            self._validate(new_email, new_name, new_password)
            pw_hash, pw_salt = row.pw_hash, row.pw_salt
            if new_password:
                salt = secrets.token_bytes(16)
                pw_hash, pw_salt = _hash_password(new_password, salt), salt.hex()
            try:
                conn.execute(text(
                    "UPDATE users SET name=:name,email=:email,pw_hash=:pw_hash,pw_salt=:pw_salt WHERE id=:id"
                ), {"name": new_name, "email": new_email, "pw_hash": pw_hash, "pw_salt": pw_salt, "id": user_id})
            except Exception as e:
                if "unique" in str(e).lower() or "UNIQUE" in str(e):
                    raise AuthError("That email is already in use.")
                raise
            updated = conn.execute(text("SELECT * FROM users WHERE id=:id"), {"id": user_id}).fetchone()
        return self._public(updated)

    def delete_user(self, user_id: str) -> None:
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("DELETE FROM sessions WHERE user_id=:id"), {"id": user_id})
            conn.execute(text("DELETE FROM api_tokens WHERE user_id=:id"), {"id": user_id})
            conn.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})

    # ── Sessions ─────────────────────────────────────────────────────────────
    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("INSERT INTO sessions VALUES (:token,:user_id,:expires_at)"),
                         {"token": token, "user_id": user_id,
                          "expires_at": time.time() + _SESSION_TTL})
        return token

    def user_for_token(self, token: str | None) -> dict | None:
        if not token:
            return None
        with self._engine.connect() as conn:
            row = conn.execute(text(
                "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token=:token AND s.expires_at > :now"
            ), {"token": token, "now": time.time()}).fetchone()
        return self._public(row) if row else None

    def delete_session(self, token: str | None) -> None:
        if not token:
            return
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("DELETE FROM sessions WHERE token=:token"), {"token": token})

    # ── API tokens ────────────────────────────────────────────────────────────
    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_api_token(self, user_id: str, name: str) -> dict:
        name = (name or "token").strip()[:80] or "token"
        token = "dbg_" + secrets.token_urlsafe(32)
        tid = secrets.token_hex(8)
        with self._lock, self._engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO api_tokens VALUES (:id,:user_id,:name,:token_hash,:created_at,:last_used)"
            ), {"id": tid, "user_id": user_id, "name": name,
                "token_hash": self._token_hash(token), "created_at": time.time(), "last_used": None})
        return {"id": tid, "name": name, "token": token}

    def list_api_tokens(self, user_id: str) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id,name,created_at,last_used FROM api_tokens "
                "WHERE user_id=:id ORDER BY created_at DESC"
            ), {"id": user_id}).fetchall()
        return [{"id": r.id, "name": r.name, "created_at": r.created_at,
                 "last_used": r.last_used} for r in rows]

    def revoke_api_token(self, user_id: str, token_id: str) -> None:
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("DELETE FROM api_tokens WHERE id=:id AND user_id=:uid"),
                         {"id": token_id, "uid": user_id})

    def user_for_api_token(self, token: str | None) -> dict | None:
        if not token:
            return None
        h = self._token_hash(token)
        with self._engine.connect() as conn:
            row = conn.execute(text(
                "SELECT u.* FROM api_tokens t JOIN users u ON u.id = t.user_id "
                "WHERE t.token_hash=:h"
            ), {"h": h}).fetchone()
            if row is not None:
                with self._lock, self._engine.begin() as c:
                    c.execute(text("UPDATE api_tokens SET last_used=:now WHERE token_hash=:h"),
                              {"now": time.time(), "h": h})
        return self._public(row) if row else None

    # ── Per-user LLM API keys (encrypted at rest) ────────────────────────────
    SUPPORTED_PROVIDERS = ("openai", "anthropic")

    def set_user_key(self, user_id: str, provider: str, api_key: str) -> None:
        """Encrypt and store a user's API key for the given provider."""
        if provider not in self.SUPPORTED_PROVIDERS:
            raise AuthError(f"Unsupported provider: {provider}")
        enc = _encrypt(api_key.strip())
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO user_keys (user_id, provider, key_enc, updated_at)
                VALUES (:uid, :prov, :enc, :now)
                ON CONFLICT (user_id, provider) DO UPDATE
                    SET key_enc=excluded.key_enc, updated_at=excluded.updated_at
            """), {"uid": user_id, "prov": provider, "enc": enc, "now": time.time()})

    def get_user_key(self, user_id: str, provider: str) -> str | None:
        """Return the decrypted API key, or None if not set."""
        with self._engine.connect() as conn:
            row = conn.execute(text(
                "SELECT key_enc FROM user_keys WHERE user_id=:uid AND provider=:prov"),
                {"uid": user_id, "prov": provider}).fetchone()
        if row is None:
            return None
        try:
            return _decrypt(row.key_enc)
        except Exception:
            return None

    def get_user_keys(self, user_id: str) -> dict:
        """Return metadata (provider → {set, updated_at}) — never the key itself."""
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT provider, updated_at FROM user_keys WHERE user_id=:uid"),
                {"uid": user_id}).fetchall()
        return {r.provider: {"set": True, "updated_at": r.updated_at} for r in rows}

    def delete_user_key(self, user_id: str, provider: str) -> None:
        with self._lock, self._engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM user_keys WHERE user_id=:uid AND provider=:prov"),
                {"uid": user_id, "prov": provider})

    def clear(self) -> None:
        """Test helper — wipe all users, sessions, tokens, and keys."""
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("DELETE FROM sessions"))
            conn.execute(text("DELETE FROM api_tokens"))
            conn.execute(text("DELETE FROM user_keys"))
            conn.execute(text("DELETE FROM users"))
