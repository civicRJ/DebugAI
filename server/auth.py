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
import os
import re
import secrets
import threading
import time
from pathlib import Path

import base64
import struct

from cryptography.fernet import Fernet
from sqlalchemy import inspect
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


def _requires_key_secret() -> bool:
    return bool(os.environ.get("DATABASE_URL") or os.environ.get("DEBUGAI_REQUIRE_KEY_SECRET"))


def _has_key_secret() -> bool:
    return bool(os.environ.get("DEBUGAI_KEY_SECRET"))


def _encrypt(value: str) -> str:
    if _requires_key_secret() and not _has_key_secret():
        raise AuthError("DEBUGAI_KEY_SECRET is required before storing user LLM keys.")
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")


_SESSION_TTL = 30 * 24 * 3600  # 30 days
_EMAIL_TOKEN_TTL = 24 * 3600
_RESET_TOKEN_TTL = 60 * 60
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
                    created_at REAL NOT NULL,
                    email_verified INTEGER NOT NULL DEFAULT 0
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    created_at REAL NOT NULL DEFAULT 0,
                    last_used REAL
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
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS email_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id    TEXT NOT NULL,
                    purpose    TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    used_at    REAL
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_mfa (
                    user_id    TEXT PRIMARY KEY,
                    secret_enc TEXT NOT NULL,
                    enabled    INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS orgs (
                    id           TEXT PRIMARY KEY,
                    name         TEXT NOT NULL,
                    owner_id     TEXT NOT NULL,
                    plan         TEXT NOT NULL DEFAULT 'free',
                    created_at   REAL NOT NULL
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS org_memberships (
                    org_id    TEXT NOT NULL,
                    user_id   TEXT NOT NULL,
                    role      TEXT NOT NULL DEFAULT 'member',
                    joined_at REAL NOT NULL,
                    PRIMARY KEY (org_id, user_id)
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS org_invites (
                    token      TEXT PRIMARY KEY,
                    org_id     TEXT NOT NULL,
                    email      TEXT NOT NULL,
                    role       TEXT NOT NULL DEFAULT 'member',
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id       TEXT PRIMARY KEY,
                    active_org_id TEXT
                )
            """))
        self._ensure_columns()

    def _ensure_columns(self) -> None:
        """Add columns for older local/prod databases without destructive migrations."""
        insp = inspect(self._engine)
        users = {c["name"] for c in insp.get_columns("users")}
        sessions = {c["name"] for c in insp.get_columns("sessions")}
        with self._lock, self._engine.begin() as conn:
            if "email_verified" not in users:
                conn.execute(text("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0"))
            if "created_at" not in sessions:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN created_at REAL NOT NULL DEFAULT 0"))
            if "last_used" not in sessions:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN last_used REAL"))

    @staticmethod
    def _public(row) -> dict:
        return {"id": row.id, "email": row.email, "name": row.name,
                "created_at": row.created_at,
                "email_verified": bool(getattr(row, "email_verified", 0))}

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
	                "INSERT INTO users (id,email,name,pw_hash,pw_salt,created_at,email_verified) "
                    "VALUES (:id,:email,:name,:pw_hash,:pw_salt,:created_at,:email_verified)"
	                ), {"id": uid, "email": email, "name": name,
	                    "pw_hash": _hash_password(password, salt),
	                    "pw_salt": salt.hex(), "created_at": time.time(),
                        "email_verified": 0})
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

    def get_user_by_email(self, email: str) -> dict | None:
        email = (email or "").strip().lower()
        with self._engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM users WHERE email=:email"),
                               {"email": email}).fetchone()
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
            email_verified = row.email_verified if new_email == row.email else 0
            if new_password:
                salt = secrets.token_bytes(16)
                pw_hash, pw_salt = _hash_password(new_password, salt), salt.hex()
            try:
                conn.execute(text(
                    "UPDATE users SET name=:name,email=:email,pw_hash=:pw_hash,"
                    "pw_salt=:pw_salt,email_verified=:email_verified WHERE id=:id"
                ), {"name": new_name, "email": new_email, "pw_hash": pw_hash,
                    "pw_salt": pw_salt, "email_verified": email_verified, "id": user_id})
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
            conn.execute(text("DELETE FROM email_tokens WHERE user_id=:id"), {"id": user_id})
            conn.execute(text("DELETE FROM user_mfa WHERE user_id=:id"), {"id": user_id})
            conn.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})

    # ── Sessions ─────────────────────────────────────────────────────────────
    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock, self._engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO sessions (token,user_id,expires_at,created_at,last_used) "
                "VALUES (:token,:user_id,:expires_at,:created_at,:last_used)"
            ),
	                         {"token": token, "user_id": user_id,
	                          "expires_at": now + _SESSION_TTL,
                              "created_at": now, "last_used": now})
        return token

    def user_for_token(self, token: str | None) -> dict | None:
        if not token:
            return None
        with self._engine.connect() as conn:
            row = conn.execute(text(
                "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token=:token AND s.expires_at > :now"
            ), {"token": token, "now": time.time()}).fetchone()
        if row is not None:
            with self._lock, self._engine.begin() as conn:
                conn.execute(text("UPDATE sessions SET last_used=:now WHERE token=:token"),
                             {"now": time.time(), "token": token})
        return self._public(row) if row else None

    def delete_session(self, token: str | None) -> None:
        if not token:
            return
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("DELETE FROM sessions WHERE token=:token"), {"token": token})

    def list_sessions(self, user_id: str, current_token: str | None = None) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT token, created_at, last_used, expires_at FROM sessions "
                "WHERE user_id=:uid AND expires_at>:now ORDER BY last_used DESC"
            ), {"uid": user_id, "now": time.time()}).fetchall()
        return [
            {"id": self._token_hash(r.token)[:16], "created_at": r.created_at,
             "last_used": r.last_used, "expires_at": r.expires_at,
             "current": bool(current_token and hmac.compare_digest(r.token, current_token))}
            for r in rows
        ]

    def revoke_session(self, user_id: str, session_id: str, current_token: str | None = None) -> None:
        with self._lock, self._engine.begin() as conn:
            rows = conn.execute(text("SELECT token FROM sessions WHERE user_id=:uid"),
                                {"uid": user_id}).fetchall()
            for r in rows:
                if self._token_hash(r.token)[:16] == session_id:
                    if current_token and hmac.compare_digest(r.token, current_token):
                        return
                    conn.execute(text("DELETE FROM sessions WHERE token=:token"), {"token": r.token})
                    return

    def delete_other_sessions(self, user_id: str, current_token: str | None) -> None:
        with self._lock, self._engine.begin() as conn:
            if current_token:
                conn.execute(text("DELETE FROM sessions WHERE user_id=:uid AND token<>:token"),
                             {"uid": user_id, "token": current_token})
            else:
                conn.execute(text("DELETE FROM sessions WHERE user_id=:uid"), {"uid": user_id})

    # ── Email verification + password reset ───────────────────────────────────
    def create_email_token(self, user_id: str, purpose: str, ttl: int | None = None) -> str:
        if purpose not in ("verify_email", "password_reset", "mfa_login"):
            raise AuthError("Unsupported token purpose.")
        token = secrets.token_urlsafe(32)
        now = time.time()
        expires = now + (ttl or (_RESET_TOKEN_TTL if purpose == "password_reset" else _EMAIL_TOKEN_TTL))
        with self._lock, self._engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM email_tokens WHERE user_id=:uid AND purpose=:purpose"
            ), {"uid": user_id, "purpose": purpose})
            conn.execute(text(
                "INSERT INTO email_tokens (token_hash,user_id,purpose,expires_at,created_at,used_at) "
                "VALUES (:h,:uid,:purpose,:expires,:created,NULL)"
            ), {"h": self._token_hash(token), "uid": user_id, "purpose": purpose,
                "expires": expires, "created": now})
        return token

    def create_password_reset_token(self, email: str) -> tuple[str, dict] | None:
        email = (email or "").strip().lower()
        with self._engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM users WHERE email=:email"),
                               {"email": email}).fetchone()
        if row is None:
            _hash_password("", b"0" * 16)
            return None
        user = self._public(row)
        return self.create_email_token(user["id"], "password_reset"), user

    def verify_email_token(self, token: str) -> dict:
        user = self._consume_email_token(token, "verify_email")
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("UPDATE users SET email_verified=1 WHERE id=:uid"),
                         {"uid": user["id"]})
            row = conn.execute(text("SELECT * FROM users WHERE id=:uid"),
                               {"uid": user["id"]}).fetchone()
        return self._public(row)

    # ── MFA (TOTP) ─────────────────────────────────────────────────────────────
    @staticmethod
    def generate_mfa_secret() -> str:
        return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")

    @staticmethod
    def _totp(secret: str, counter: int) -> str:
        padded = secret.upper() + "=" * ((8 - len(secret) % 8) % 8)
        key = base64.b32decode(padded)
        msg = struct.pack(">Q", counter)
        digest = hmac.new(key, msg, hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
        return f"{code % 1_000_000:06d}"

    @classmethod
    def verify_totp(cls, secret: str, code: str, now: float | None = None) -> bool:
        code = "".join(c for c in (code or "") if c.isdigit())
        if len(code) != 6:
            return False
        counter = int((now or time.time()) // 30)
        return any(hmac.compare_digest(cls._totp(secret, counter + drift), code)
                   for drift in (-1, 0, 1))

    def mfa_status(self, user_id: str) -> dict:
        with self._engine.connect() as conn:
            row = conn.execute(text("SELECT enabled, updated_at FROM user_mfa WHERE user_id=:uid"),
                               {"uid": user_id}).fetchone()
        return {"enabled": bool(row and row.enabled), "updated_at": row.updated_at if row else None}

    def mfa_enabled(self, user_id: str) -> bool:
        return self.mfa_status(user_id)["enabled"]

    def setup_mfa(self, user_id: str) -> str:
        secret = self.generate_mfa_secret()
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO user_mfa (user_id, secret_enc, enabled, updated_at)
                VALUES (:uid, :secret, 0, :now)
                ON CONFLICT (user_id) DO UPDATE
                    SET secret_enc=excluded.secret_enc, enabled=0, updated_at=excluded.updated_at
            """), {"uid": user_id, "secret": _encrypt(secret), "now": time.time()})
        return secret

    def _mfa_secret(self, user_id: str) -> str | None:
        with self._engine.connect() as conn:
            row = conn.execute(text("SELECT secret_enc FROM user_mfa WHERE user_id=:uid"),
                               {"uid": user_id}).fetchone()
        if not row:
            return None
        try:
            return _decrypt(row.secret_enc)
        except Exception:
            return None

    def enable_mfa(self, user_id: str, code: str) -> None:
        secret = self._mfa_secret(user_id)
        if not secret or not self.verify_totp(secret, code):
            raise AuthError("Invalid MFA code.")
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("UPDATE user_mfa SET enabled=1, updated_at=:now WHERE user_id=:uid"),
                         {"uid": user_id, "now": time.time()})

    def disable_mfa(self, user_id: str, code: str) -> None:
        secret = self._mfa_secret(user_id)
        if not secret or not self.verify_totp(secret, code):
            raise AuthError("Invalid MFA code.")
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("DELETE FROM user_mfa WHERE user_id=:uid"), {"uid": user_id})

    def verify_mfa_login(self, challenge: str, code: str) -> dict:
        user = self._consume_email_token(challenge, "mfa_login")
        secret = self._mfa_secret(user["id"])
        if not secret or not self.verify_totp(secret, code):
            raise AuthError("Invalid MFA code.")
        return user

    def reset_password(self, token: str, new_password: str) -> dict:
        self._validate("reset@example.com", "Reset", new_password)
        user = self._consume_email_token(token, "password_reset")
        salt = secrets.token_bytes(16)
        with self._lock, self._engine.begin() as conn:
            conn.execute(text(
                "UPDATE users SET pw_hash=:pw_hash,pw_salt=:pw_salt,email_verified=1 WHERE id=:uid"
            ), {"pw_hash": _hash_password(new_password, salt), "pw_salt": salt.hex(),
                "uid": user["id"]})
            conn.execute(text("DELETE FROM sessions WHERE user_id=:uid"), {"uid": user["id"]})
            row = conn.execute(text("SELECT * FROM users WHERE id=:uid"),
                               {"uid": user["id"]}).fetchone()
        return self._public(row)

    def _consume_email_token(self, token: str, purpose: str) -> dict:
        h = self._token_hash(token or "")
        now = time.time()
        with self._lock, self._engine.begin() as conn:
            row = conn.execute(text(
                "SELECT t.token_hash, u.* FROM email_tokens t JOIN users u ON u.id=t.user_id "
                "WHERE t.token_hash=:h AND t.purpose=:purpose AND t.used_at IS NULL AND t.expires_at>:now"
            ), {"h": h, "purpose": purpose, "now": now}).fetchone()
            if row is None:
                raise AuthError("Invalid or expired token.")
            conn.execute(text("UPDATE email_tokens SET used_at=:now WHERE token_hash=:h"),
                         {"now": now, "h": h})
        return self._public(row)

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

    # ── Orgs ─────────────────────────────────────────────────────────────────
    def create_org(self, name: str, owner_id: str) -> dict:
        name = (name or "").strip()
        if not name:
            raise AuthError("Organisation name is required.")
        oid = "o_" + secrets.token_hex(8)
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("INSERT INTO orgs VALUES (:id,:name,:owner_id,:plan,:ts)"),
                         {"id": oid, "name": name, "owner_id": owner_id,
                          "plan": "free", "ts": time.time()})
            conn.execute(text("INSERT INTO org_memberships VALUES (:oid,:uid,'owner',:ts)"),
                         {"oid": oid, "uid": owner_id, "ts": time.time()})
        return {"id": oid, "name": name, "plan": "free", "role": "owner"}

    def get_org(self, org_id: str) -> dict | None:
        with self._engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM orgs WHERE id=:id"), {"id": org_id}).fetchone()
        return {"id": row.id, "name": row.name, "plan": row.plan, "owner_id": row.owner_id} if row else None

    def list_user_orgs(self, user_id: str) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT o.id, o.name, o.plan, m.role FROM orgs o "
                "JOIN org_memberships m ON m.org_id=o.id "
                "WHERE m.user_id=:uid ORDER BY o.created_at"), {"uid": user_id}).fetchall()
        return [{"id": r.id, "name": r.name, "plan": r.plan, "role": r.role} for r in rows]

    def list_org_members(self, org_id: str) -> list[dict]:
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT u.id, u.name, u.email, m.role, m.joined_at "
                "FROM org_memberships m JOIN users u ON u.id=m.user_id "
                "WHERE m.org_id=:oid ORDER BY m.joined_at"), {"oid": org_id}).fetchall()
        return [{"id": r.id, "name": r.name, "email": r.email,
                 "role": r.role, "joined_at": r.joined_at} for r in rows]

    def user_org_role(self, org_id: str, user_id: str) -> str | None:
        """Return the user's role in the org, or None if not a member."""
        with self._engine.connect() as conn:
            row = conn.execute(text(
                "SELECT role FROM org_memberships WHERE org_id=:oid AND user_id=:uid"),
                {"oid": org_id, "uid": user_id}).fetchone()
        return row.role if row else None

    def remove_org_member(self, org_id: str, user_id: str) -> None:
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("DELETE FROM org_memberships WHERE org_id=:oid AND user_id=:uid"),
                         {"oid": org_id, "uid": user_id})

    # ── Invites ──────────────────────────────────────────────────────────────
    def create_invite(self, org_id: str, email: str, role: str = "member",
                      ttl: int = 7 * 24 * 3600) -> str:
        email = email.strip().lower()
        if not _EMAIL_RE.match(email):
            raise AuthError("Enter a valid email address.")
        token = secrets.token_urlsafe(32)
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("INSERT INTO org_invites VALUES (:tok,:oid,:email,:role,:now,:exp)"),
                         {"tok": token, "oid": org_id, "email": email, "role": role,
                          "now": time.time(), "exp": time.time() + ttl})
        return token

    def get_invite(self, token: str) -> dict | None:
        with self._engine.connect() as conn:
            row = conn.execute(text(
                "SELECT i.*, o.name as org_name FROM org_invites i "
                "JOIN orgs o ON o.id=i.org_id WHERE i.token=:tok AND i.expires_at>:now"),
                {"tok": token, "now": time.time()}).fetchone()
        if not row:
            return None
        return {"org_id": row.org_id, "org_name": row.org_name, "email": row.email,
                "role": row.role, "expires_at": row.expires_at}

    def accept_invite(self, token: str, user_id: str) -> dict:
        invite = self.get_invite(token)
        if not invite:
            raise AuthError("Invite not found or expired.")
        with self._lock, self._engine.begin() as conn:
            existing = conn.execute(text(
                "SELECT 1 FROM org_memberships WHERE org_id=:oid AND user_id=:uid"),
                {"oid": invite["org_id"], "uid": user_id}).fetchone()
            if not existing:
                conn.execute(text("INSERT INTO org_memberships VALUES (:oid,:uid,:role,:ts)"),
                             {"oid": invite["org_id"], "uid": user_id,
                              "role": invite["role"], "ts": time.time()})
            conn.execute(text("DELETE FROM org_invites WHERE token=:tok"), {"tok": token})
        return invite

    # ── Active workspace (personal ↔ org switcher) ───────────────────────────
    def get_active_workspace(self, user_id: str) -> str | None:
        """Return active org_id or None (= personal workspace)."""
        with self._engine.connect() as conn:
            row = conn.execute(text(
                "SELECT active_org_id FROM user_preferences WHERE user_id=:uid"),
                {"uid": user_id}).fetchone()
        return row.active_org_id if row else None

    def set_active_workspace(self, user_id: str, org_id: str | None) -> None:
        """Set active workspace. org_id=None → personal."""
        if org_id and not self.user_org_role(org_id, user_id):
            raise AuthError("Not a member of this organisation.")
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO user_preferences (user_id, active_org_id) VALUES (:uid, :oid)
                ON CONFLICT (user_id) DO UPDATE SET active_org_id=excluded.active_org_id
            """), {"uid": user_id, "oid": org_id})

    def clear(self) -> None:
        """Test helper — wipe all users, sessions, tokens, and keys."""
        with self._lock, self._engine.begin() as conn:
            conn.execute(text("DELETE FROM sessions"))
            conn.execute(text("DELETE FROM api_tokens"))
            conn.execute(text("DELETE FROM email_tokens"))
            conn.execute(text("DELETE FROM user_mfa"))
            conn.execute(text("DELETE FROM user_keys"))
            conn.execute(text("DELETE FROM org_memberships"))
            conn.execute(text("DELETE FROM org_invites"))
            conn.execute(text("DELETE FROM orgs"))
            conn.execute(text("DELETE FROM user_preferences"))
            conn.execute(text("DELETE FROM users"))
