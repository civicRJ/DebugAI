"""API tests for the dashboard backend (FastAPI TestClient)."""

import os

os.environ["DEBUGAI_NO_SEED"] = "1"  # don't auto-seed (model load) during tests

import pytest
from fastapi.testclient import TestClient

from server.app import (
    AnalyzeRequest, SESSION_COOKIE, app, auth_store, feedback_store, lead_store,
    store, trace_store, traction_store,
)


@pytest.fixture()
def client(tmp_path):
    store.clear()
    trace_store.clear()
    lead_store.clear()
    feedback_store.clear()
    traction_store.clear()
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
    lead_store.clear()
    feedback_store.clear()
    traction_store.clear()
    auth_store.clear()


def test_beta_lead_capture_is_public_and_dedupes(client):
    r = client.post("/api/beta/leads", json={
        "email": "Founder@Example.com",
        "name": "Founder",
        "company": "Acme AI",
        "role": "Founder / engineering lead",
        "use_case": "RAG support bot gives wrong policy answers.",
    })
    assert r.status_code == 200
    assert r.json()["lead"]["email"] == "founder@example.com"

    r2 = client.post("/api/beta/leads", json={
        "email": "founder@example.com",
        "company": "Acme Labs",
        "role": "RAG / agent builder",
    })
    assert r2.status_code == 200
    leads = lead_store.list()
    assert len(leads) == 1
    assert leads[0]["company"] == "Acme Labs"


def test_admin_stats_include_traction_funnel(client, monkeypatch):
    monkeypatch.setenv("DEBUGAI_STAFF", "test@example.com")
    client.post("/api/beta/leads", json={
        "email": "lead@example.com",
        "role": "AI product engineer",
        "use_case": "Agent tool calls fail silently.",
    })
    client.post("/api/account/tokens", json={"name": "local-sdk"})
    client.post("/api/analyze", json={
        "prompt": "What is the refund policy?",
        "output": "Full cash refund within 90 days.",
        "chunks": ["Store hours are 9 to 5."],
        "similarity_scores": [0.2],
        "temperature": 0.1,
    })

    r = client.get("/api/admin/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["leads"]["total"] == 1
    assert body["funnel"]["leads"] == 1
    assert body["activation"]["users_with_api_tokens"] == 1
    assert body["activation"]["activated_product_users"] == 1
    assert body["traction"]["failures_submitted"] == 0


def test_admin_tracks_real_failure_interviews(client, monkeypatch):
    monkeypatch.setenv("DEBUGAI_STAFF", "test@example.com")
    r = client.post("/api/admin/traction/interviews", json={
        "lead_email": "founder@example.com",
        "contact_name": "Founder",
        "company": "Acme AI",
        "source": "dev.to",
        "failure_summary": "RAG bot gave a 90-day refund answer from a 30-day policy.",
        "failure_type": "hallucination",
        "diagnosis_accepted": True,
        "fix_worked": True,
        "would_pay": True,
        "repeat_usage": False,
        "status": "fixed",
        "notes": "Would pay if it catches this in CI.",
    })
    assert r.status_code == 200
    item = r.json()["item"]
    assert item["lead_email"] == "founder@example.com"

    stats = client.get("/api/admin/stats").json()["traction"]
    assert stats["failures_submitted"] == 1
    assert stats["diagnosis_accepted"] == 1
    assert stats["fix_worked"] == 1
    assert stats["would_pay"] == 1
    assert stats["repeat_usage"] == 0
    assert stats["recent"][0]["failure_type"] == "hallucination"

    updated = client.patch(f"/api/admin/traction/interviews/{item['id']}", json={
        **item,
        "repeat_usage": True,
        "notes": "Asked for SDK install help.",
    })
    assert updated.status_code == 200
    assert client.get("/api/admin/stats").json()["traction"]["repeat_usage"] == 1


def test_admin_traction_requires_staff(client):
    r = client.post("/api/admin/traction/interviews", json={
        "failure_summary": "A bad output from a RAG bot.",
    })
    assert r.status_code == 403


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


def test_seed_endpoint_includes_new_debugger_failures(client):
    r = client.post("/api/seed")
    assert r.status_code == 200
    stats = client.get("/api/stats").json()
    by_failure = stats["by_failure"]
    assert by_failure["schema_violation"] >= 1
    assert by_failure["tool_call_failure"] >= 1
    assert by_failure["citation_failure"] >= 1
    assert by_failure["ambiguous_prompt"] >= 1


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


def test_fix_does_not_use_server_env_keys(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-server-key-must-not-be-used")
    r = client.post("/api/analyze", json={
        "prompt": "What is the refund policy?",
        "output": "Full cash refund within 90 days.",
        "chunks": ["Store hours are 9 to 5."],
        "similarity_scores": [0.2],
        "temperature": 0.1,
    })
    diag_id = r.json()["id"]
    fix = client.post(f"/api/fix/{diag_id}?simulate=false").json()
    assert fix["rerun_mode"] == "proposed"
    assert fix["after_output"] is None
    assert fix["reverified"] is False


def test_diagnosis_does_not_use_server_env_keys(client, monkeypatch):
    import debugai.explainer as explainer_mod
    import debugai.judge as judge_mod

    monkeypatch.setenv("OPENAI_API_KEY", "sk-server-key-must-not-be-used")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-server-key-must-not-be-used")

    def no_env_explainer(api_key=None):
        assert api_key == ""
        return None

    def no_env_judge(*_args, **_kwargs):
        raise AssertionError("server OpenAI key should not be used")

    monkeypatch.setattr(explainer_mod, "_client", no_env_explainer)
    monkeypatch.setattr(judge_mod, "_openai_judge", no_env_judge)

    analyzed = client.post("/api/analyze", json={
        "prompt": "What is the refund policy?",
        "output": "Full cash refund within 90 days.",
        "chunks": ["Store hours are 9 to 5."],
        "similarity_scores": [0.2],
        "explain_with_llm": True,
    })
    assert analyzed.status_code == 200
    assert analyzed.json()["diagnosis"]["explainer_model"] == "deterministic"

    debugged = client.post("/api/debug", json={
        "system_prompt": "You are a Socratic tutor. Ask one question.",
        "prompt": "What is 2 + 2?",
        "output": "The answer is 4.",
        "run_fix": False,
    })
    assert debugged.status_code == 200


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


def test_playground_accepts_schema_and_tool_debug_inputs(client):
    schema = {
        "type": "object",
        "required": ["status", "answer"],
        "properties": {
            "status": {"type": "string", "enum": ["ok", "error"]},
            "answer": {"type": "string"},
        },
    }
    r = client.post("/api/playground", json={
        "prompt": "Classify this ticket and return JSON.",
        "output": '{"status": "maybe"}',
        "response_schema": schema,
        "tools_expected": ["search"],
        "tool_calls": [],
        "run_fix": True,
        "simulate": True,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["diagnosis"]["primary"]["failure"] == "schema_violation"
    assert body["ui"]["title"] == "Schema violation"
    assert body["fix"]["agent"] == "Schema Repair Agent"


def test_agent_trace_endpoint_detects_runtime_failures(client):
    r = client.post("/api/agent-trace", json={
        "goal": "Answer current shipping cutoff",
        "expected_tools": ["search_shipping_cutoff"],
        "max_steps": 8,
        "events": [
            {"type": "tool_call", "tool": "search_shipping_cutoff", "args": {"q": "shipping cutoff"}},
            {"type": "tool_result", "tool": "search_shipping_cutoff", "output": "Cutoff is 3 PM today."},
            {"type": "tool_call", "tool": "search_shipping_cutoff", "args": {"q": "shipping cutoff"}},
            {"type": "tool_result", "tool": "search_shipping_cutoff", "output": "Cutoff is 3 PM today."},
            {"type": "tool_call", "tool": "search_shipping_cutoff", "args": {"q": "shipping cutoff"}},
            {"type": "final", "output": "The cutoff is 8 PM today."},
        ],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["diagnosis"]["primary"]["failure"] == "tool_call_loop"
    assert body["fix"]["agent"] == "Agent Runtime Fix Agent"
    assert body["ui"]["title"] == "Tool Call Loop"


def test_prompt_audit_endpoint_scans_prompt_without_server_env_key(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-server-key-must-not-be-used")
    r = client.post("/api/prompt-audit", json={
        "system_prompt": "You are a helpful support agent. Always answer. Use any tool when needed.",
        "use_case": "Customer support RAG agent",
        "tools": ["refund_order", "send_email"],
        "retrieves_external_content": True,
        "handles_secrets": True,
        "high_risk_actions": ["issue refunds"],
        "dynamic": True,
        "llm": True,
    })
    assert r.status_code == 200
    body = r.json()
    ids = {i["id"] for i in body["issues"]}
    assert body["auditor_model"] == "not_configured"
    assert "missing_untrusted_context_boundary" in ids
    assert "missing_tool_policy" in ids
    assert body["attack_cases"]


def test_prompt_audit_endpoint_uses_model_provider_key(client, monkeypatch):
    import server.app as app_mod

    user = auth_store.get_user_by_email("test@example.com")
    auth_store.set_user_key(user["id"], "openai", "sk-user-openai")
    auth_store.set_user_key(user["id"], "anthropic", "sk-user-anthropic")
    calls = []

    def fake_audit_prompt(**kwargs):
        calls.append(kwargs)
        return {
            "healthy": True,
            "risk_score": 0,
            "grade": "low_risk",
            "issues": [],
            "attack_cases": [],
            "patched_prompt": kwargs["system_prompt"],
            "auditor_model": "fake",
            "summary": "ok",
        }

    monkeypatch.setattr(app_mod, "audit_prompt", fake_audit_prompt)

    r = client.post("/api/prompt-audit", json={
        "system_prompt": "You are a bounded support assistant.",
        "model": "claude-sonnet-4-6",
        "llm": True,
    })
    assert r.status_code == 200
    assert calls[-1]["api_key"] == "sk-user-anthropic"

    r = client.post("/api/prompt-audit", json={
        "system_prompt": "You are a bounded support assistant.",
        "model": "gpt-5.5",
        "llm": True,
    })
    assert r.status_code == 200
    assert calls[-1]["api_key"] == "sk-user-openai"


def test_pipeline_feedback_and_beta_workflow_endpoints(client):
    analyzed = client.post("/api/analyze", json={
        "prompt": "What is the refund policy?",
        "output": "Full cash refund within 90 days.",
        "chunks": ["Store hours are 9 to 5."],
        "similarity_scores": [0.2],
    }).json()

    feedback = client.post("/api/feedback", json={
        "diagnosis_id": analyzed["id"],
        "accepted": True,
        "fix_worked": False,
    })
    assert feedback.status_code == 200
    assert client.get("/api/confidence").json()["by_failure"]["retrieval_failure"]["accepted"] == 1

    pipeline = client.post("/api/pipeline/analyze", json={
        "prompt": "refund policy",
        "stages": [{
            "id": "ret",
            "kind": "retrieval",
            "input": "refund policy",
            "chunks": ["parking only"],
            "similarity_scores": [0.2],
        }],
    })
    assert pipeline.status_code == 200
    assert pipeline.json()["primary"]["failure"] == "retrieval_failure"

    workflow = client.post("/api/beta/debug-workflow", json={
        "system_prompt": "You are a helpful support agent. Always answer.",
        "prompt": "What is the refund policy?",
        "output": "Full cash refund within 90 days.",
        "chunks": ["Store hours are 9 to 5."],
        "similarity_scores": [0.2],
        "use_case": "Customer support RAG bot",
        "retrieves_external_content": True,
        "run_fix": True,
        "simulate": True,
    })
    assert workflow.status_code == 200
    body = workflow.json()
    assert body["record"]["diagnosis"]["healthy"] is False
    assert body["prompt_audit"]["issues"]
    assert body["debug_report"]["regression_artifact"]["expected_after"]["healthy"] is True


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
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok"
    assert body["database"]["backend"] in ("sqlite", "postgres")
    assert body["database"]["connected"] is True


def test_docs_page_is_public(client):
    r = client.get("/docs")
    assert r.status_code == 200
    assert "Use DebugAI locally" in r.text


def test_gated_pages_are_no_store(client):
    # client fixture is authenticated → dashboard served with no-store so the
    # browser can't show a cached page after logout.
    assert client.get("/dashboard").headers.get("cache-control") == "no-store"


def test_login_register_pages_do_not_auto_redirect_when_authenticated(client):
    login = client.get("/login")
    register = client.get("/register")
    assert login.status_code == 200 and "Sign in" in login.text
    assert register.status_code == 200 and "Create account" in register.text


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
        me = c.get("/api/auth/me").json()
        assert me["name"] == "Ada"
        assert "id" not in me and "created_at" not in me
        c.post("/api/auth/logout")
        assert c.get("/api/auth/me").status_code == 401


def test_email_verification_required_flow(monkeypatch):
    auth_store.clear()
    monkeypatch.setenv("DEBUGAI_REQUIRE_EMAIL_VERIFICATION", "1")
    with TestClient(app) as c:
        r = c.post("/api/auth/register",
                   json={"email": "verify@example.com", "name": "Verify", "password": "password123"})
        assert r.status_code == 200
        assert r.json()["needs_verification"] is True
        assert c.get("/api/auth/me").status_code == 401
        blocked = c.post("/api/auth/login",
                         json={"email": "verify@example.com", "password": "password123"})
        assert blocked.status_code == 403

        user = auth_store.get_user_by_email("verify@example.com")
        token = auth_store.create_email_token(user["id"], "verify_email")
        verified = c.post("/api/auth/verify", json={"token": token})
        assert verified.status_code == 200
        assert verified.json()["email_verified"] is True
        assert c.get("/api/auth/me").status_code == 200
    monkeypatch.delenv("DEBUGAI_REQUIRE_EMAIL_VERIFICATION", raising=False)
    auth_store.clear()


def test_email_verification_can_be_disabled_with_database_url(monkeypatch):
    auth_store.clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setenv("DEBUGAI_REQUIRE_EMAIL_VERIFICATION", "0")
    with TestClient(app) as c:
        r = c.post("/api/auth/register",
                   json={"email": "noverify@example.com", "name": "No Verify", "password": "password123"})
        assert r.status_code == 200
        assert r.json()["needs_verification"] is False
        assert c.get("/api/auth/me").status_code == 200
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEBUGAI_REQUIRE_EMAIL_VERIFICATION", raising=False)
    auth_store.clear()


def test_password_reset_and_session_management():
    auth_store.clear()
    with TestClient(app) as c:
        c.post("/api/auth/register",
               json={"email": "reset@example.com", "name": "Reset", "password": "password123"})
        user = auth_store.get_user_by_email("reset@example.com")
        r = c.post("/api/auth/password-reset/request", json={"email": "missing@example.com"})
        assert r.status_code == 200
        assert "eligible" in r.json()["message"]
        token, _ = auth_store.create_password_reset_token("reset@example.com")
        ok = c.post("/api/auth/password-reset/confirm",
                    json={"token": token, "password": "newpassword9"})
        assert ok.status_code == 200
        assert auth_store.authenticate("reset@example.com", "newpassword9") is not None

        extra = auth_store.create_session(user["id"])
        sessions = c.get("/api/auth/sessions").json()["items"]
        assert len(sessions) >= 2
        c.post("/api/auth/logout-others")
        assert auth_store.user_for_token(extra) is None
        assert c.get("/api/auth/me").status_code == 200
    auth_store.clear()


def test_mfa_login_flow():
    auth_store.clear()
    with TestClient(app) as c:
        c.post("/api/auth/register",
               json={"email": "mfa@example.com", "name": "MFA", "password": "password123"})
        setup = c.post("/api/account/mfa/setup").json()
        code = auth_store._totp(setup["secret"], int(__import__("time").time() // 30))
        enabled = c.post("/api/account/mfa/enable", json={"code": code})
        assert enabled.status_code == 200 and enabled.json()["enabled"] is True
        c.post("/api/auth/logout")

        login = c.post("/api/auth/login",
                       json={"email": "mfa@example.com", "password": "password123"})
        assert login.status_code == 202
        assert login.json()["mfa_required"] is True
        assert c.get("/api/auth/me").status_code == 401
        challenge = login.json()["challenge"]
        bad = c.post("/api/auth/mfa/login", json={"challenge": challenge, "code": "000000"})
        assert bad.status_code == 401

        login = c.post("/api/auth/login",
                       json={"email": "mfa@example.com", "password": "password123"}).json()
        ok = c.post("/api/auth/mfa/login",
                    json={"challenge": login["challenge"], "code": code})
        assert ok.status_code == 200
        assert c.get("/api/auth/me").status_code == 200
        disabled = c.post("/api/account/mfa/disable", json={"code": code})
        assert disabled.status_code == 200 and disabled.json()["enabled"] is False
    auth_store.clear()


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
    assert "token" not in listed[0] and "token_hash" not in listed[0]
    client.delete("/api/account/tokens/" + listed[0]["id"])
    with TestClient(app) as svc:
        assert svc.get("/api/stats", headers={"X-API-Key": tok["token"]}).status_code == 401


def test_analyze_request_defaults_to_fast_lazy_mode():
    req = AnalyzeRequest(prompt="q", output="a")
    assert req.lazy is True
    assert req.deep is False


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


def test_csrf_blocks_cross_origin_cookie_posts(monkeypatch):
    auth_store.clear(); store.clear(); trace_store.clear()
    monkeypatch.setenv("DEBUGAI_STRICT_CSRF", "1")
    with TestClient(app, base_url="https://debugai.test") as c:
        r = c.post("/api/auth/register",
                   json={"email": "csrf@example.com", "name": "CSRF", "password": "password123"},
                   headers={"Origin": "https://debugai.test"})
        assert r.status_code == 200
        blocked = c.post("/api/analyze", json={"prompt": "q", "output": "a"},
                         headers={"Origin": "https://evil.test"})
        assert blocked.status_code == 403
        allowed = c.post("/api/analyze", json={"prompt": "q", "output": "a"},
                         headers={"Origin": "https://debugai.test"})
        assert allowed.status_code == 200
    monkeypatch.delenv("DEBUGAI_STRICT_CSRF", raising=False)
    auth_store.clear(); store.clear(); trace_store.clear()


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


def test_org_workspace_trace_and_seed_scoping(client):
    org = client.post("/api/orgs", json={"name": "Acme"}).json()
    client.patch("/api/user/workspace", json={"org_id": org["id"]})

    t = client.post("/api/traces", json={
        "name": "org-trace", "spans": [{"kind": "generation"}],
    }).json()
    assert t["owner"] == org["id"]

    client.post("/api/seed")
    assert client.get("/api/stats").json()["total"] > 0
    client.delete("/api/diagnoses")
    assert client.get("/api/stats").json()["total"] == 0
    assert client.get("/api/traces").json()["items"] == []


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
