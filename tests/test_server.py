"""API tests for the dashboard backend (FastAPI TestClient)."""

import os

os.environ["DEBUGAI_NO_SEED"] = "1"  # don't auto-seed (model load) during tests

import pytest
from fastapi.testclient import TestClient

from server.app import SESSION_COOKIE, app, auth_store, store, trace_store


@pytest.fixture()
def client(tmp_path):
    store.clear()
    trace_store.clear()
    auth_store.clear()
    c = TestClient(app)
    with c:
        # every data endpoint now requires a session — register + auto-login
        r = c.post("/api/auth/register",
                   json={"email": "test@example.com", "name": "Test", "password": "password123"})
        assert r.status_code == 200
        yield c
    store.clear()
    trace_store.clear()
    auth_store.clear()


def test_analyze_stores_and_returns_ui(client):
    r = client.post("/api/analyze", json={
        "prompt": "What is the refund policy for electronics?",
        "output": "Electronics get a full 90-day cash refund.",
        "chunks": ["Store hours are 9 to 5.", "Parking is out back."],
        "similarity_scores": [0.42, 0.40],
        "temperature": 0.2,
        "label": "test",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["diagnosis"]["primary"]["failure"] == "retrieval_failure"
    assert body["ui"]["severity"] == "critical"
    assert len(body["ui"]["signals"]) == 8
    assert "id" in body and "timestamp" in body


def test_stats_and_filter(client):
    client.post("/api/analyze", json={
        "prompt": "Where is the HQ?",
        "output": "The company is headquartered in Austin, Texas.",
        "chunks": ["The company is headquartered in Austin, Texas."],
        "similarity_scores": [0.9],
        "temperature": 0.0,
    })
    client.post("/api/analyze", json={
        "prompt": "What is the refund policy?",
        "output": "Full cash refund within 90 days.",
        "chunks": ["Store hours are 9 to 5."],
        "similarity_scores": [0.2],
        "temperature": 0.1,
    })
    stats = client.get("/api/stats").json()
    assert stats["total"] == 2
    assert stats["healthy"] >= 1 and stats["failing"] >= 1

    only_rf = client.get("/api/diagnoses?failure=retrieval_failure").json()["items"]
    assert all(
        i["diagnosis"]["primary"]["failure"] == "retrieval_failure" for i in only_rf
    )


def test_thresholds_endpoint_and_calibration_records(client):
    # Fresh store → cold regime, defaults.
    t0 = client.get("/api/thresholds").json()
    assert t0["regime"] == "cold"
    assert t0["total_requests"] == 0

    # A healthy request should grow the baseline.
    client.post("/api/analyze", json={
        "prompt": "Where is the HQ?",
        "output": "The company is headquartered in Austin, Texas.",
        "chunks": ["The company is headquartered in Austin, Texas."],
        "similarity_scores": [0.9],
        "temperature": 0.0,
    })
    t1 = client.get("/api/thresholds").json()
    assert t1["total_requests"] == 1
    assert t1["healthy_baseline"] == 1
    assert {s["field"] for s in t1["signals"]} >= {"similarity_min", "latency_high_ms"}


def test_fix_endpoint_runs_loop(client):
    r = client.post("/api/analyze", json={
        "prompt": "What does Section 4 of the contract require?",
        "output": "Section 4 requires arbitration in Delaware under the Marbury Clause and a $50,000 penalty.",
        "chunks": ["Section 4 covers confidentiality between the parties.",
                   "The contract is governed by California law."],
        "similarity_scores": [0.66, 0.59],
        "temperature": 0.75,
    })
    diag_id = r.json()["id"]
    assert r.json()["diagnosis"]["primary"]["failure"] == "hallucination"

    fix = client.post(f"/api/fix/{diag_id}?simulate=true").json()
    assert fix["agent"] == "Prompt Rule Agent"
    assert fix["verdict"] == "verified"
    assert fix["rerun_mode"] == "simulated"
    assert fix["tests_passed"] == fix["tests_total"]


def test_fix_endpoint_404_for_unknown(client):
    assert client.post("/api/fix/nope").status_code == 404


def test_debug_endpoint_one_shot_diagnose_and_fix(client):
    r = client.post("/api/debug", json={
        "issue": "My chatbot answers from outside the retrieved context.",
        "system_prompt": "You are a support assistant.",
        "prompt": "What is the refund policy for opened electronics?",
        "output": "Opened electronics get a full 90-day cash refund and Galaxy items get a 1-year guarantee.",
        "chunks": ["Returns: most items may be returned within 30 days with a receipt.",
                   "Store hours are 9am to 5pm."],
        "similarity_scores": [0.44, 0.31],
        "temperature": 0.7,
    }).json()
    # Diagnosis recorded with the issue, and a fix proposed+verified in one shot.
    assert r["record"]["issue"].startswith("My chatbot")
    assert r["record"]["diagnosis"]["healthy"] is False
    assert r["fix"] is not None
    assert r["fix"]["verdict"] in ("verified", "mitigated", "escalated", "failed")
    assert r["fix"]["agent"]


def test_analyze_creates_linked_trace(client):
    client.post("/api/analyze", json={
        "prompt": "What is the refund policy?",
        "output": "Full cash refund within 90 days.",
        "chunks": ["Store hours are 9 to 5."],
        "similarity_scores": [0.2],
        "temperature": 0.1,
        "session_id": "s-test",
        "model_name": "claude-haiku-4-5",
    })
    traces = client.get("/api/traces").json()["items"]
    assert len(traces) == 1
    t = traces[0]
    assert t["session_id"] == "s-test"
    assert [s["kind"] for s in t["spans"]] == ["retrieval", "generation"]
    assert t["status"] == "failing"
    assert t["total_tokens"] > 0

    # detail, sessions, metrics
    assert client.get(f"/api/traces/{t['id']}").status_code == 200
    assert client.get("/api/traces/nope").status_code == 404
    sessions = client.get("/api/sessions").json()["items"]
    assert any(s["session_id"] == "s-test" for s in sessions)
    stats = client.get("/api/observability/stats").json()
    assert stats["traces"] == 1 and stats["failing"] == 1
    assert "latency_p95_ms" in stats and "cost_usd" in stats


def test_trace_ingest_endpoint(client):
    t = client.post("/api/traces", json={
        "name": "external", "session_id": "ext", "status": "ok",
        "spans": [{"kind": "generation"}], "scores": [], "total_tokens": 42,
    }).json()
    assert t["id"]
    assert client.get("/api/traces?session=ext").json()["items"][0]["total_tokens"] == 42


def test_input_bounds_and_limits_enforced(client):
    # Oversized prompt rejected by validation.
    big = client.post("/api/analyze", json={"prompt": "x" * 50_000, "output": "y"})
    assert big.status_code == 422
    # limit query param is clamped to [1, 500].
    assert client.get("/api/diagnoses?limit=99999").status_code == 422
    assert client.get("/api/traces?limit=0").status_code == 422


def test_errors_do_not_leak_internals(client):
    # A malformed-but-valid request that trips the engine returns a generic message.
    r = client.post("/api/analyze", json={"prompt": "", "output": "x"})
    # empty prompt → engine raises; detail must be generic, not a stack/exception string.
    assert r.status_code in (400, 422)
    if r.status_code == 400:
        assert r.json()["detail"] == "analysis failed"


def test_health_endpoint_is_public(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_gated_pages_are_no_store(client):
    # client fixture is authenticated → dashboard served with no-store so the
    # browser can't show a cached page after logout.
    assert client.get("/dashboard").headers.get("cache-control") == "no-store"


def test_security_headers_present(client):
    h = client.get("/").headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in h and "frame-ancestors 'none'" in h["Content-Security-Policy"]


def _fresh_client():
    c = TestClient(app)
    c.__enter__()
    return c


def test_register_login_logout_me():
    auth_store.clear()
    with TestClient(app) as c:
        r = c.post("/api/auth/register", json={"email": "a@b.com", "name": "Ada", "password": "password123"})
        assert r.status_code == 200 and r.json()["email"] == "a@b.com"
        assert SESSION_COOKIE in r.cookies or c.cookies.get(SESSION_COOKIE)
        assert c.get("/api/auth/me").json()["name"] == "Ada"
        c.post("/api/auth/logout")
        assert c.get("/api/auth/me").status_code == 401


def test_register_validation_and_duplicate():
    auth_store.clear()
    with TestClient(app) as c:
        assert c.post("/api/auth/register", json={"email": "x", "name": "N", "password": "password123"}).status_code == 400
        assert c.post("/api/auth/register", json={"email": "a@b.com", "name": "N", "password": "short"}).status_code == 400
        assert c.post("/api/auth/register", json={"email": "a@b.com", "name": "N", "password": "password123"}).status_code == 200
        dup = c.post("/api/auth/register", json={"email": "a@b.com", "name": "N", "password": "password123"})
        assert dup.status_code == 400


def test_bad_login_rejected():
    auth_store.clear()
    with TestClient(app) as c:
        c.post("/api/auth/register", json={"email": "a@b.com", "name": "N", "password": "password123"})
        c.post("/api/auth/logout")
        assert c.post("/api/auth/login", json={"email": "a@b.com", "password": "wrong"}).status_code == 401


def test_account_update_and_password_change():
    auth_store.clear()
    with TestClient(app) as c:
        c.post("/api/auth/register", json={"email": "a@b.com", "name": "Ada", "password": "password123"})
        # wrong current password rejected
        assert c.patch("/api/account", json={"name": "New", "current_password": "nope"}).status_code == 403
        ok = c.patch("/api/account", json={"name": "Ada B", "new_password": "newpassword9",
                                           "current_password": "password123"})
        assert ok.status_code == 200 and ok.json()["name"] == "Ada B"
        c.post("/api/auth/logout")
        # new password works, old does not
        assert c.post("/api/auth/login", json={"email": "a@b.com", "password": "password123"}).status_code == 401
        assert c.post("/api/auth/login", json={"email": "a@b.com", "password": "newpassword9"}).status_code == 200


def test_per_user_data_isolation():
    auth_store.clear(); store.clear(); trace_store.clear()
    a = _fresh_client(); b = _fresh_client()
    try:
        a.post("/api/auth/register", json={"email": "a@x.com", "name": "A", "password": "password123"})
        b.post("/api/auth/register", json={"email": "b@x.com", "name": "B", "password": "password123"})
        a.post("/api/analyze", json={"prompt": "refund?", "output": "Full cash refund in 90 days.",
                                     "chunks": ["Store hours 9-5."], "similarity_scores": [0.2], "temperature": 0.1})
        assert a.get("/api/stats").json()["total"] == 1
        assert b.get("/api/stats").json()["total"] == 0          # B can't see A's data
        assert b.get("/api/diagnoses").json()["items"] == []
        assert b.get("/api/traces").json()["items"] == []
    finally:
        a.__exit__(None, None, None); b.__exit__(None, None, None)
    auth_store.clear(); store.clear(); trace_store.clear()


def test_account_delete_purges_data():
    auth_store.clear(); store.clear(); trace_store.clear()
    with TestClient(app) as c:
        c.post("/api/auth/register", json={"email": "a@b.com", "name": "A", "password": "password123"})
        c.post("/api/analyze", json={"prompt": "q", "output": "a"})
        assert c.get("/api/stats").json()["total"] == 1
        c.request("DELETE", "/api/account")
        # session revoked → data endpoints now 401
        assert c.get("/api/stats").status_code == 401


def test_api_token_grants_programmatic_access(client):
    # `client` is logged in as test@example.com. Mint a token...
    tok = client.post("/api/account/tokens", json={"name": "ci"}).json()
    assert tok["token"].startswith("dbg_")
    client.post("/api/analyze", json={"prompt": "q", "output": "a"})  # one diagnosis for this user

    # ...then a fresh client with NO cookie authenticates via the token header.
    with TestClient(app) as svc:
        assert svc.get("/api/stats").status_code == 401          # no creds
        r = svc.get("/api/stats", headers={"X-API-Key": tok["token"]})
        assert r.status_code == 200 and r.json()["total"] >= 1   # sees the user's data
        # Bearer form also works
        assert svc.get("/api/stats", headers={"Authorization": "Bearer " + tok["token"]}).status_code == 200

    # revoke → token no longer works
    listed = client.get("/api/account/tokens").json()["items"]
    client.delete("/api/account/tokens/" + listed[0]["id"])
    with TestClient(app) as svc:
        assert svc.get("/api/stats", headers={"X-API-Key": tok["token"]}).status_code == 401


def test_data_endpoints_require_auth():
    # No session → 401 on data endpoints; home stays public.
    auth_store.clear()
    with TestClient(app) as c:
        unauth = c.get("/api/stats")
        assert unauth.status_code == 401
        assert unauth.headers["X-Frame-Options"] == "DENY"  # headers still applied
        assert c.get("/").status_code == 200
        # gated app pages redirect to /login (TestClient follows → lands on login)
        r = c.get("/dashboard")
        assert r.status_code == 200 and "Sign in" in r.text


def test_oversized_body_rejected(client):
    big = "x" * (5 * 1024 * 1024)
    r = client.post("/api/analyze", content=big.encode(),
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_rate_limit_returns_429():
    # Test the limiter in isolation (deterministic, no full-app reload).
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from server.security import RateLimitMiddleware

    async def ok(_request):
        return JSONResponse({"ok": True})

    mini = Starlette(routes=[Route("/api/x", ok), Route("/page", ok)])
    mini.add_middleware(RateLimitMiddleware, per_minute=3)
    with TestClient(mini) as c:
        api_codes = [c.get("/api/x").status_code for _ in range(5)]
        assert api_codes.count(200) == 3 and api_codes.count(429) == 2
        r = c.get("/api/x")
        assert "Retry-After" in r.headers
        # non-/api paths are never rate limited
        assert all(c.get("/page").status_code == 200 for _ in range(10))


def test_trace_ingest_ignores_unknown_fields(client):
    t = client.post("/api/traces", json={
        "name": "ext", "session_id": "s", "total_tokens": 5,
        "evil": "<script>", "id": "attacker-set", "spans": [{"kind": "generation"}],
    }).json()
    assert t["id"] != "attacker-set"   # server assigns the id
    assert "evil" not in t              # extra fields dropped


def test_clear(client):
    client.post("/api/analyze", json={"prompt": "q", "output": "a"})
    assert client.get("/api/stats").json()["total"] == 1
    client.delete("/api/diagnoses")
    assert client.get("/api/stats").json()["total"] == 0


def test_site_pages_and_assets_served(client):
    # Home page
    home = client.get("/")
    assert home.status_code == 200 and "DebugAI" in home.text
    # Dashboard page
    dash = client.get("/dashboard")
    assert dash.status_code == 200 and "Diagnosis Dashboard" in dash.text
    # Design system + landing assets reachable via /ds mount
    for path in [
        "/ds/_ds_bundle.js", "/ds/styles.css",
        "/ds/templates/landing/landing.css",
        "/ds/templates/landing/sections-hero.jsx",
        "/static/dashboard.jsx",
    ]:
        assert client.get(path).status_code == 200, path
