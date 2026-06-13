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
