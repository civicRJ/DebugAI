"""Unit tests for the SQLite auth store."""

import pytest

from server.auth import AuthError, AuthStore


@pytest.fixture()
def store(tmp_path):
    return AuthStore(db_path=tmp_path / "auth.db")


def test_register_and_authenticate(store):
    u = store.register("Alice@Example.com ", "Alice", "supersecret")
    assert u["email"] == "alice@example.com"  # normalised
    assert "pw_hash" not in u  # never exposed
    assert store.authenticate("alice@example.com", "supersecret")["id"] == u["id"]
    assert store.authenticate("alice@example.com", "wrong") is None
    assert store.authenticate("nobody@example.com", "x") is None


def test_duplicate_email_rejected(store):
    store.register("a@b.com", "A", "password1")
    with pytest.raises(AuthError):
        store.register("a@b.com", "Other", "password2")


def test_validation(store):
    with pytest.raises(AuthError):
        store.register("not-an-email", "A", "password1")
    with pytest.raises(AuthError):
        store.register("a@b.com", "A", "short")  # < 8 chars
    with pytest.raises(AuthError):
        store.register("a@b.com", "", "password1")  # empty name


def test_sessions_lifecycle(store):
    u = store.register("a@b.com", "A", "password1")
    token = store.create_session(u["id"])
    assert store.user_for_token(token)["id"] == u["id"]
    assert store.user_for_token("bogus") is None
    store.delete_session(token)
    assert store.user_for_token(token) is None


def test_update_and_password_change(store):
    u = store.register("a@b.com", "A", "password1")
    store.update_user(u["id"], name="Alice B", new_password="newpassword2")
    assert store.get_user(u["id"])["name"] == "Alice B"
    assert store.authenticate("a@b.com", "password1") is None
    assert store.authenticate("a@b.com", "newpassword2") is not None


def test_delete_user_revokes_sessions(store):
    u = store.register("a@b.com", "A", "password1")
    token = store.create_session(u["id"])
    store.delete_user(u["id"])
    assert store.user_for_token(token) is None
    assert store.get_user(u["id"]) is None


def test_api_tokens(store):
    u = store.register("a@b.com", "A", "password1")
    created = store.create_api_token(u["id"], "ci")
    assert created["token"].startswith("dbg_")
    assert store.user_for_api_token(created["token"])["id"] == u["id"]
    assert store.user_for_api_token("dbg_bogus") is None
    # listing never exposes the secret
    listed = store.list_api_tokens(u["id"])
    assert listed[0]["name"] == "ci" and "token" not in listed[0]
    # revoke
    store.revoke_api_token(u["id"], created["id"])
    assert store.user_for_api_token(created["token"]) is None


def test_delete_user_revokes_tokens(store):
    u = store.register("a@b.com", "A", "password1")
    tok = store.create_api_token(u["id"], "t")["token"]
    store.delete_user(u["id"])
    assert store.user_for_api_token(tok) is None


def test_prod_key_storage_requires_encryption_secret(store, monkeypatch):
    u = store.register("a@b.com", "A", "password1")
    monkeypatch.setenv("DEBUGAI_REQUIRE_KEY_SECRET", "1")
    monkeypatch.delenv("DEBUGAI_KEY_SECRET", raising=False)
    with pytest.raises(AuthError):
        store.set_user_key(u["id"], "openai", "sk-test")

    monkeypatch.setenv("DEBUGAI_KEY_SECRET", "x" * 32)
    store.set_user_key(u["id"], "openai", "sk-test")
    assert store.get_user_key(u["id"], "openai") == "sk-test"


def test_email_verification_and_password_reset_tokens(store):
    u = store.register("a@b.com", "A", "password1")
    assert u["email_verified"] is False
    verify = store.create_email_token(u["id"], "verify_email")
    verified = store.verify_email_token(verify)
    assert verified["email_verified"] is True
    with pytest.raises(AuthError):
        store.verify_email_token(verify)

    reset, user = store.create_password_reset_token("a@b.com")
    assert user["id"] == u["id"]
    session = store.create_session(u["id"])
    updated = store.reset_password(reset, "newpassword9")
    assert updated["email_verified"] is True
    assert store.authenticate("a@b.com", "newpassword9") is not None
    assert store.user_for_token(session) is None
    assert store.create_password_reset_token("missing@example.com") is None


def test_sessions_and_email_change_verification_reset(store):
    u = store.register("a@b.com", "A", "password1")
    verify = store.create_email_token(u["id"], "verify_email")
    store.verify_email_token(verify)
    s1 = store.create_session(u["id"])
    s2 = store.create_session(u["id"])
    sessions = store.list_sessions(u["id"], s1)
    assert len(sessions) == 2
    assert any(s["current"] for s in sessions)
    store.delete_other_sessions(u["id"], s1)
    assert store.user_for_token(s1) is not None
    assert store.user_for_token(s2) is None

    updated = store.update_user(u["id"], email="new@b.com")
    assert updated["email_verified"] is False


def test_mfa_totp_lifecycle(store):
    u = store.register("mfa@example.com", "MFA", "password1")
    secret = store.setup_mfa(u["id"])
    code = store._totp(secret, int(__import__("time").time() // 30))
    store.enable_mfa(u["id"], code)
    assert store.mfa_status(u["id"])["enabled"] is True

    challenge = store.create_email_token(u["id"], "mfa_login", ttl=600)
    assert store.verify_mfa_login(challenge, code)["id"] == u["id"]
    with pytest.raises(AuthError):
        store.verify_mfa_login(challenge, code)

    store.disable_mfa(u["id"], code)
    assert store.mfa_status(u["id"])["enabled"] is False
