"""Authentication store — users + sessions in a stdlib SQLite DB.

Passwords are hashed with scrypt + a per-user random salt (stdlib `hashlib`);
sessions are random opaque tokens stored server-side (so logout / account
deletion truly revoke them). No third-party auth dependencies.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

_DB = Path(__file__).with_name("debugai.db")
_SESSION_TTL = 30 * 24 * 3600  # 30 days
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# scrypt parameters (RFC 7914 interactive-login range).
_N, _R, _P, _DKLEN = 16384, 8, 1, 32


class AuthError(ValueError):
    """Raised for invalid input or auth conflicts (mapped to 4xx by the API)."""


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt,
                          n=_N, r=_R, p=_P, dklen=_DKLEN).hex()


class AuthStore:
    def __init__(self, db_path: Path = _DB):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    pw_hash TEXT NOT NULL,
                    pw_salt TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_tokens (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL,
                    created_at REAL NOT NULL,
                    last_used REAL
                );
                """
            )
            self._conn.commit()

    # --- helpers -----------------------------------------------------------
    @staticmethod
    def _public(row: sqlite3.Row) -> dict:
        return {"id": row["id"], "email": row["email"], "name": row["name"],
                "created_at": row["created_at"]}

    @staticmethod
    def _validate(email: str, name: str, password: str | None) -> None:
        if not _EMAIL_RE.match((email or "").strip()):
            raise AuthError("Enter a valid email address.")
        if not (name or "").strip():
            raise AuthError("Name is required.")
        if password is not None and len(password) < 8:
            raise AuthError("Password must be at least 8 characters.")

    # --- users -------------------------------------------------------------
    def register(self, email: str, name: str, password: str) -> dict:
        email = (email or "").strip().lower()
        name = (name or "").strip()
        self._validate(email, name, password)
        uid = secrets.token_hex(8)
        salt = secrets.token_bytes(16)
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO users VALUES (?,?,?,?,?,?)",
                    (uid, email, name, _hash_password(password, salt), salt.hex(), time.time()),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                raise AuthError("An account with that email already exists.")
            row = self._conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return self._public(row)

    def authenticate(self, email: str, password: str) -> dict | None:
        email = (email or "").strip().lower()
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if row is None:
            # Equalise timing whether or not the email exists.
            _hash_password(password or "", b"0" * 16)
            return None
        expected = row["pw_hash"]
        actual = _hash_password(password or "", bytes.fromhex(row["pw_salt"]))
        if not hmac.compare_digest(expected, actual):
            return None
        return self._public(row)

    def get_user(self, user_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return self._public(row) if row else None

    def update_user(self, user_id: str, *, name: str | None = None,
                    email: str | None = None, new_password: str | None = None) -> dict:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if row is None:
                raise AuthError("Account not found.")
            new_name = (name if name is not None else row["name"]).strip()
            new_email = (email if email is not None else row["email"]).strip().lower()
            self._validate(new_email, new_name, new_password)
            pw_hash, pw_salt = row["pw_hash"], row["pw_salt"]
            if new_password:
                salt = secrets.token_bytes(16)
                pw_hash, pw_salt = _hash_password(new_password, salt), salt.hex()
            try:
                self._conn.execute(
                    "UPDATE users SET name=?, email=?, pw_hash=?, pw_salt=? WHERE id=?",
                    (new_name, new_email, pw_hash, pw_salt, user_id),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                raise AuthError("That email is already in use.")
            updated = self._conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return self._public(updated)

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            self._conn.execute("DELETE FROM api_tokens WHERE user_id=?", (user_id,))
            self._conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            self._conn.commit()

    # --- sessions ----------------------------------------------------------
    def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._conn.execute("INSERT INTO sessions VALUES (?,?,?)",
                               (token, user_id, time.time() + _SESSION_TTL))
            self._conn.commit()
        return token

    def user_for_token(self, token: str | None) -> dict | None:
        if not token:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token=? AND s.expires_at > ?", (token, time.time()),
            ).fetchone()
        return self._public(row) if row else None

    def delete_session(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE token=?", (token,))
            self._conn.commit()

    # --- API tokens (programmatic access, e.g. the wrap_llm SDK) -----------
    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_api_token(self, user_id: str, name: str) -> dict:
        """Create a token. The plaintext is returned ONCE (only its hash is stored)."""
        name = (name or "token").strip()[:80] or "token"
        token = "dbg_" + secrets.token_urlsafe(32)
        tid = secrets.token_hex(8)
        with self._lock:
            self._conn.execute(
                "INSERT INTO api_tokens VALUES (?,?,?,?,?,?)",
                (tid, user_id, name, self._token_hash(token), time.time(), None),
            )
            self._conn.commit()
        return {"id": tid, "name": name, "token": token}

    def list_api_tokens(self, user_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, created_at, last_used FROM api_tokens "
                "WHERE user_id=? ORDER BY created_at DESC", (user_id,),
            ).fetchall()
        return [{"id": r["id"], "name": r["name"], "created_at": r["created_at"],
                 "last_used": r["last_used"]} for r in rows]

    def revoke_api_token(self, user_id: str, token_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM api_tokens WHERE id=? AND user_id=?",
                               (token_id, user_id))
            self._conn.commit()

    def user_for_api_token(self, token: str | None) -> dict | None:
        if not token:
            return None
        h = self._token_hash(token)
        with self._lock:
            row = self._conn.execute(
                "SELECT u.* FROM api_tokens t JOIN users u ON u.id = t.user_id "
                "WHERE t.token_hash=?", (h,),
            ).fetchone()
            if row is not None:
                self._conn.execute("UPDATE api_tokens SET last_used=? WHERE token_hash=?",
                                   (time.time(), h))
                self._conn.commit()
        return self._public(row) if row else None

    def clear(self) -> None:
        """Test helper — wipe all users, sessions, and tokens."""
        with self._lock:
            self._conn.executescript(
                "DELETE FROM sessions; DELETE FROM api_tokens; DELETE FROM users;")
            self._conn.commit()
