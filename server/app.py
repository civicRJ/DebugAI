"""DebugAI dashboard backend (Architecture §10, Step 6).

Serves the diagnosis API and the design-system dashboard:

    POST /api/analyze      run the engine on a request, store + return diagnosis
    GET  /api/diagnoses    recent diagnoses (filter by ?failure=)
    GET  /api/stats        counts by failure type
    DELETE /api/diagnoses  clear history
    GET  /                 dashboard (uses Debug_AI design system)

Run:  uvicorn server.app:app --reload
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

log = logging.getLogger("debugai.server")

# Input bounds (defensive — prevent storage blowup / pathological inputs).
MAX_TEXT = 20_000
MAX_CHUNKS = 200
MAX_CHUNK_LEN = 10_000

from debugai import analyze, analyze_pipeline, audit_prompt
from debugai.agents import propose_fix
from debugai.calibration import ThresholdStore
from debugai.examples import example_cases
from debugai.report import debug_report
from debugai.schema import CaptureRecord
from debugai.tracing import Span, Trace, scores_from_diagnosis, status_from_diagnosis
from server.auth import AuthError, AuthStore
from server.db import status as db_status
from server.email import send_email_verification, send_password_reset, send_welcome
from server.paths import data_path
from server.security import install as install_security
from server.store import DiagnosisStore, FeedbackStore, LeadStore, TraceStore
from server.ui_adapter import to_card

ROOT = Path(__file__).resolve().parent.parent
DS_DIR = ROOT / "Debug_AI"
STATIC_DIR = Path(__file__).with_name("static")
DATASET = ROOT / "tests" / "dataset" / "failures.json"
SESSION_COOKIE = "debugai_session"

store = DiagnosisStore()
trace_store = TraceStore()
lead_store = LeadStore()
feedback_store = FeedbackStore()
auth_store = AuthStore()

# Per-user adaptive calibration: one ThresholdStore per account (§7.2).
_tstores: dict[str, ThresholdStore] = {}
_tstores_lock = __import__("threading").Lock()


def tstore_for(owner: str) -> ThresholdStore:
    with _tstores_lock:
        ts = _tstores.get(owner)
        if ts is None:
            safe = "".join(c for c in owner if c.isalnum())[:24] or "anon"
            ts = ThresholdStore(path=data_path(f"thresholds_{safe}.json"))
            _tstores[owner] = ts
        return ts


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n  DebugAI ready:")
    print("    home      → http://127.0.0.1:8000/")
    print("    dashboard → http://127.0.0.1:8000/dashboard\n")
    yield


app = FastAPI(
    title="DebugAI Dashboard",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
install_security(app)


# --------------------------------------------------------------------------- #
# Authentication (SQLite users + server-side sessions, httpOnly cookie)
# --------------------------------------------------------------------------- #
def current_user(request: Request) -> dict | None:
    # Browser session cookie first, then a programmatic API token
    # (Authorization: Bearer <token> or X-API-Key) for the SDK / scripts.
    user = auth_store.user_for_token(request.cookies.get(SESSION_COOKIE))
    if user is not None:
        return user
    authz = request.headers.get("authorization", "")
    token = authz[7:].strip() if authz[:7].lower() == "bearer " else request.headers.get("x-api-key")
    return auth_store.user_for_api_token(token)


def require_user(request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    if _email_verification_required() and not user.get("email_verified"):
        raise HTTPException(status_code=403, detail="email verification required")
    return user


def _client_user(user: dict) -> dict:
    """Minimal browser-facing account payload. Internal handlers keep full rows."""
    return {
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "email_verified": bool(user.get("email_verified", False)),
    }


def _email_verification_required() -> bool:
    explicit = os.environ.get("DEBUGAI_REQUIRE_EMAIL_VERIFICATION")
    if explicit is not None:
        return explicit.strip().lower() in {"1", "true", "yes", "on"}
    return bool(os.environ.get("DATABASE_URL"))


def _hide_account_existence() -> bool:
    explicit = os.environ.get("DEBUGAI_HIDE_ACCOUNT_EXISTENCE")
    if explicit is not None:
        return explicit.strip().lower() in {"1", "true", "yes", "on"}
    return bool(os.environ.get("DATABASE_URL"))


def _send_verification(user: dict) -> None:
    token = auth_store.create_email_token(user["id"], "verify_email")
    import threading
    threading.Thread(target=send_email_verification,
                     args=(user["email"], user["name"], token), daemon=True).start()


def _generic_email_sent() -> dict:
    return {"ok": True, "message": "If the address is eligible, an email has been sent."}


def _set_session(resp: Response, request: Request, user_id: str) -> None:
    token = auth_store.create_session(user_id)
    # When running behind a reverse proxy (nginx/Caddy), FastAPI sees the internal
    # HTTP scheme even though the browser sees HTTPS — so the cookie would be set
    # without Secure and the browser silently drops it on HTTPS connections.
    # Fix: honour X-Forwarded-Proto when DEBUGAI_TRUST_PROXY is set.
    trust_proxy = os.environ.get("DEBUGAI_TRUST_PROXY")
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    is_secure = (
        (bool(trust_proxy) and forwarded_proto == "https")
        or request.url.scheme == "https"
    )
    resp.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="lax",
        secure=is_secure, max_age=30 * 24 * 3600, path="/",
    )


def _clear_session_cookie(resp: Response, request: Request) -> None:
    trust_proxy = os.environ.get("DEBUGAI_TRUST_PROXY")
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    is_secure = (
        (bool(trust_proxy) and forwarded_proto == "https")
        or request.url.scheme == "https"
    )
    resp.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=is_secure
    )


class RegisterIn(BaseModel):
    email: str = Field(max_length=320)
    name: str = Field(max_length=120)
    password: str = Field(max_length=200)
    website: str | None = Field(default=None, max_length=200)


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class EmailIn(BaseModel):
    email: str = Field(max_length=320)


class TokenIn(BaseModel):
    token: str = Field(max_length=300)


class PasswordResetIn(BaseModel):
    token: str = Field(max_length=300)
    password: str = Field(max_length=200)


class MFALoginIn(BaseModel):
    challenge: str = Field(max_length=300)
    code: str = Field(max_length=20)


class MFACodeIn(BaseModel):
    code: str = Field(max_length=20)


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    new_password: str | None = Field(default=None, max_length=200)
    current_password: str = Field(max_length=200)


class BetaLeadIn(BaseModel):
    email: str = Field(max_length=320)
    name: str | None = Field(default="", max_length=120)
    company: str | None = Field(default="", max_length=120)
    role: str | None = Field(default="", max_length=80)
    use_case: str | None = Field(default="", max_length=800)
    source: str | None = Field(default="landing", max_length=80)
    website: str | None = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        email = (value or "").strip().lower()
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            raise ValueError("Enter a valid email address.")
        return email


@app.post("/api/beta/leads")
def api_beta_lead(body: BetaLeadIn):
    # Honeypot: preserve a generic success response for bots.
    if body.website:
        return {"ok": True}
    lead = lead_store.add(body.model_dump())
    return {"ok": True, "lead": {"email": lead["email"]}}


@app.post("/api/auth/register")
def api_register(body: RegisterIn, request: Request, response: Response):
    # Honeypot field: normal users never fill this hidden input.
    if body.website:
        return _generic_email_sent()
    try:
        user = auth_store.register(body.email, body.name, body.password)
    except AuthError as e:
        if _hide_account_existence() and "already exists" in str(e):
            existing = auth_store.get_user_by_email(body.email)
            if existing and _email_verification_required() and not existing.get("email_verified"):
                _send_verification(existing)
            return _generic_email_sent()
        raise HTTPException(status_code=400, detail=str(e))
    if _email_verification_required():
        _send_verification(user)
        return {**_client_user(user), "needs_verification": True}
    _set_session(response, request, user["id"])
    import threading
    threading.Thread(target=send_welcome, args=(user["email"], user["name"]), daemon=True).start()
    return {**_client_user(user), "needs_verification": False}


@app.post("/api/auth/login")
def api_login(body: LoginIn, request: Request, response: Response):
    user = auth_store.authenticate(body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if _email_verification_required() and not user.get("email_verified"):
        _send_verification(user)
        raise HTTPException(status_code=403, detail="Verify your email before signing in. We sent a new link.")
    if auth_store.mfa_enabled(user["id"]):
        challenge = auth_store.create_email_token(user["id"], "mfa_login", ttl=10 * 60)
        return Response(
            content=json.dumps({"mfa_required": True, "challenge": challenge}),
            media_type="application/json",
            status_code=202,
        )
    _set_session(response, request, user["id"])
    return _client_user(user)


@app.post("/api/auth/mfa/login")
def api_mfa_login(body: MFALoginIn, request: Request, response: Response):
    try:
        user = auth_store.verify_mfa_login(body.challenge, body.code)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    _set_session(response, request, user["id"])
    return _client_user(user)


@app.post("/api/auth/verify")
def api_verify_email(body: TokenIn, request: Request, response: Response):
    try:
        user = auth_store.verify_email_token(body.token)
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _set_session(response, request, user["id"])
    import threading
    threading.Thread(target=send_welcome, args=(user["email"], user["name"]), daemon=True).start()
    return _client_user(user)


@app.post("/api/auth/resend-verification")
def api_resend_verification(body: EmailIn):
    user = auth_store.get_user_by_email(body.email)
    if user and not user.get("email_verified"):
        _send_verification(user)
    return _generic_email_sent()


@app.post("/api/auth/password-reset/request")
def api_password_reset_request(body: EmailIn):
    result = auth_store.create_password_reset_token(body.email)
    if result:
        token, user = result
        import threading
        threading.Thread(target=send_password_reset,
                         args=(user["email"], user["name"], token), daemon=True).start()
    return _generic_email_sent()


@app.post("/api/auth/password-reset/confirm")
def api_password_reset_confirm(body: PasswordResetIn, request: Request, response: Response):
    try:
        user = auth_store.reset_password(body.token, body.password)
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _set_session(response, request, user["id"])
    return _client_user(user)


@app.post("/api/auth/logout")
def api_logout(request: Request, response: Response):
    auth_store.delete_session(request.cookies.get(SESSION_COOKIE))
    _clear_session_cookie(response, request)
    return {"ok": True}


@app.get("/api/auth/me")
def api_me(user: dict = Depends(require_user)):
    return _client_user(user)


@app.get("/api/account/mfa")
def api_mfa_status(user: dict = Depends(require_user)):
    return auth_store.mfa_status(user["id"])


@app.post("/api/account/mfa/setup")
def api_mfa_setup(user: dict = Depends(require_user)):
    secret = auth_store.setup_mfa(user["id"])
    label = f"DebugAI:{user['email']}"
    otpauth = f"otpauth://totp/{label}?secret={secret}&issuer=DebugAI"
    return {"secret": secret, "otpauth_url": otpauth}


@app.post("/api/account/mfa/enable")
def api_mfa_enable(body: MFACodeIn, user: dict = Depends(require_user)):
    try:
        auth_store.enable_mfa(user["id"], body.code)
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return auth_store.mfa_status(user["id"])


@app.post("/api/account/mfa/disable")
def api_mfa_disable(body: MFACodeIn, user: dict = Depends(require_user)):
    try:
        auth_store.disable_mfa(user["id"], body.code)
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return auth_store.mfa_status(user["id"])


@app.get("/api/auth/sessions")
def api_sessions_list(request: Request, user: dict = Depends(require_user)):
    return {"items": auth_store.list_sessions(user["id"], request.cookies.get(SESSION_COOKIE))}


@app.delete("/api/auth/sessions/{session_id}")
def api_session_revoke(session_id: str, request: Request, user: dict = Depends(require_user)):
    auth_store.revoke_session(user["id"], session_id, request.cookies.get(SESSION_COOKIE))
    return {"ok": True}


@app.post("/api/auth/logout-others")
def api_logout_others(request: Request, user: dict = Depends(require_user)):
    auth_store.delete_other_sessions(user["id"], request.cookies.get(SESSION_COOKIE))
    return {"ok": True}


@app.patch("/api/account")
def api_account_update(body: AccountUpdate, user: dict = Depends(require_user)):
    if auth_store.authenticate(user["email"], body.current_password) is None:
        raise HTTPException(status_code=403, detail="Current password is incorrect.")
    try:
        updated = auth_store.update_user(user["id"], name=body.name, email=body.email,
                                         new_password=body.new_password)
        if _email_verification_required() and updated["email"] != user["email"]:
            _send_verification(updated)
        return _client_user(updated)
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))


class TokenCreate(BaseModel):
    name: str = Field(default="token", max_length=80)


@app.post("/api/account/tokens")
def api_token_create(body: TokenCreate, user: dict = Depends(require_user)):
    """Create an API token. The plaintext is returned ONCE — store it now."""
    return auth_store.create_api_token(user["id"], body.name)


@app.get("/api/account/tokens")
def api_token_list(user: dict = Depends(require_user)):
    return {"items": auth_store.list_api_tokens(user["id"])}


@app.delete("/api/account/tokens/{token_id}")
def api_token_revoke(token_id: str, user: dict = Depends(require_user)):
    auth_store.revoke_api_token(user["id"], token_id)
    return {"ok": True}


@app.delete("/api/account")
def api_account_delete(request: Request, response: Response, user: dict = Depends(require_user)):
    store.purge(user["id"])
    trace_store.purge(user["id"])
    feedback_store.purge(user["id"])
    with _tstores_lock:
        _tstores.pop(user["id"], None)
    auth_store.delete_user(user["id"])
    _clear_session_cookie(response, request)
    return {"ok": True}


class AnalyzeRequest(BaseModel):
    prompt: str = Field(max_length=MAX_TEXT)
    output: str = Field(max_length=MAX_TEXT)
    system_prompt: str = Field(default="", max_length=MAX_TEXT)
    chunks: list[str] | None = Field(default=None, max_length=MAX_CHUNKS)
    similarity_scores: list[float] | None = Field(default=None, max_length=MAX_CHUNKS)
    retrieval_query: str | None = Field(default=None, max_length=MAX_TEXT)
    temperature: float | None = Field(default=None, ge=0.0, le=4.0)
    max_tokens: int | None = Field(default=None, ge=0, le=10_000_000)
    context_window: int | None = Field(default=None, ge=0, le=100_000_000)
    latency_ms: int | None = Field(default=None, ge=0)
    tool_calls: list[dict] | None = Field(default=None, max_length=200)
    tools_expected: list[str] | None = Field(default=None, max_length=100)
    response_schema: dict | None = None
    model_name: str | None = Field(default=None, max_length=200)
    explain_with_llm: bool = False
    lazy: bool = Field(
        default=True,
        description="skip expensive semantic checks when cheap signals are already decisive",
    )
    deep: bool = Field(
        default=False,
        description="force full semantic analysis; slower but useful for manual audits",
    )
    label: str | None = Field(default=None, description="optional human label")
    issue: str | None = Field(default=None, description="free-text description of the bug")
    session_id: str | None = Field(default=None, description="group traces into a session")

    @field_validator("chunks")
    @classmethod
    def _cap_chunks(cls, v):
        if v is None:
            return v
        return [c[:MAX_CHUNK_LEN] for c in v]


class PromptAuditRequest(BaseModel):
    system_prompt: str = Field(max_length=MAX_TEXT)
    use_case: str = Field(default="", max_length=MAX_TEXT)
    tools: list[str] | None = Field(default=None, max_length=100)
    retrieves_external_content: bool = False
    handles_secrets: bool = False
    output_schema: dict | None = None
    high_risk_actions: list[str] | None = Field(default=None, max_length=100)
    dynamic: bool = True
    llm: bool = False
    model: str | None = Field(default=None, max_length=200)


class PipelineAnalyzeRequest(BaseModel):
    system_prompt: str = Field(default="", max_length=MAX_TEXT)
    prompt: str = Field(default="", max_length=MAX_TEXT)
    output_schema: dict | None = None
    stages: list[dict] = Field(default_factory=list, max_length=100)


class FeedbackIn(BaseModel):
    diagnosis_id: str = Field(max_length=80)
    accepted: bool
    fix_worked: bool | None = None
    note: str = Field(default="", max_length=1000)


def _record(req_dict: dict, diagnosis: dict, owner: str) -> dict:
    return {
        "id": uuid.uuid4().hex[:12],
        "owner": owner,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "label": req_dict.get("label"),
        "issue": req_dict.get("issue"),
        "input": {
            "prompt": req_dict.get("prompt"),
            "output": req_dict.get("output"),
            "issue": req_dict.get("issue"),
            "system_prompt": req_dict.get("system_prompt", ""),
            "model_name": req_dict.get("model_name"),
            "chunks": req_dict.get("chunks") or [],
            "similarity_scores": req_dict.get("similarity_scores") or [],
            "retrieval_query": req_dict.get("retrieval_query"),
            "temperature": req_dict.get("temperature"),
            "max_tokens": req_dict.get("max_tokens"),
            "context_window": req_dict.get("context_window"),
            "latency_ms": req_dict.get("latency_ms"),
            "tool_calls": req_dict.get("tool_calls") or [],
            "tools_expected": req_dict.get("tools_expected") or [],
            "response_schema": req_dict.get("response_schema"),
            "lazy": req_dict.get("lazy", True),
            "deep": req_dict.get("deep", False),
        },
        "diagnosis": diagnosis,
        "ui": to_card(diagnosis),
    }


def _effective_owner(user_id: str) -> str:
    """Return the data-scoping owner: active org_id (prefixed o_…) or user_id."""
    active = auth_store.get_active_workspace(user_id)
    return active if active else user_id


def _run(req: AnalyzeRequest, owner: str, judge: bool = False) -> dict:
    # Adaptive: diagnose with this user's calibrated thresholds, then feed the
    # result back so the baseline keeps learning (§7.2). The instruction-adherence
    # judge (an LLM call) runs only when explicitly requested — i.e. the "Debug a
    # bug" workbench — never on routine /api/analyze or seeding.
    # Keys are always the user's own — never the server's env keys.
    tstore = tstore_for(owner)
    user_openai_key = auth_store.get_user_key(owner, "openai") or ""
    user_anthropic_key = auth_store.get_user_key(owner, "anthropic") or ""
    diagnosis = analyze(
        prompt=req.prompt,
        output=req.output,
        system_prompt=req.system_prompt,
        chunks=req.chunks,
        similarity_scores=req.similarity_scores,
        retrieval_query=req.retrieval_query,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        context_window=req.context_window,
        latency_ms=req.latency_ms,
        tool_calls=req.tool_calls,
        tools_expected=req.tools_expected,
        response_schema=req.response_schema,
        model_name=req.model_name,
        explain_with_llm=req.explain_with_llm,
        lazy=req.lazy and not req.deep,
        thresholds=tstore.current(),
        judge=judge and bool((req.system_prompt or "").strip()),
        openai_api_key=user_openai_key,
        anthropic_api_key=user_anthropic_key,
    )
    tstore.record(diagnosis["signals"], diagnosis["healthy"])
    rec = store.add(_record(req.model_dump(), diagnosis, owner))
    _trace_for(req, rec, owner)
    return rec


def _trace_for(req: AnalyzeRequest, rec: dict, owner: str) -> dict:
    """Build a linked observability trace for a diagnosed request."""
    diagnosis = rec["diagnosis"]
    t = Trace(name=req.label or "diagnosis", session_id=req.session_id,
              model=req.model_name, timestamp=rec["timestamp"])
    t.metadata = {"diagnosis_id": rec["id"], "issue": req.issue}
    if req.chunks:
        sp = Span(name="retrieval", kind="retrieval")
        sp.input = req.retrieval_query or req.prompt
        sp.output = req.chunks
        sp.metadata = {"similarity_scores": req.similarity_scores}
        sp.end_ms = sp.start_ms
        t.add_span(sp)
    gen = Span(name="generation", kind="generation", model=req.model_name)
    gen.input = req.prompt
    gen.output = req.output
    # Approximate tokens from text length (~4 chars/token) when not supplied.
    prompt_chars = len(req.system_prompt or "") + len(req.prompt or "") + sum(len(c) for c in (req.chunks or []))
    gen.set_usage(prompt=max(1, prompt_chars // 4), completion=max(1, len(req.output or "") // 4))
    gen.end_ms = gen.start_ms + float(req.latency_ms or 0)
    t.add_span(gen)
    for tc in req.tool_calls or []:
        sp = Span(name=str(tc.get("name") or "tool"), kind="tool")
        sp.input = tc.get("input")
        sp.metadata = {"id": tc.get("id", ""), "status": tc.get("status", "")}
        sp.end_ms = sp.start_ms
        t.add_span(sp)
    t.diagnosis = diagnosis
    t.scores = scores_from_diagnosis(diagnosis)
    t.status = status_from_diagnosis(diagnosis)
    t.end()
    data = t.to_dict()
    data["owner"] = owner
    return trace_store.add(data)


@app.post("/api/analyze")
def api_analyze(req: AnalyzeRequest, user: dict = Depends(require_user)):
    try:
        return _run(req, _effective_owner(user["id"]))
    except Exception:
        log.exception("analyze failed")
        raise HTTPException(status_code=400, detail="analysis failed")


@app.post("/api/prompt-audit")
def api_prompt_audit(req: PromptAuditRequest, user: dict = Depends(require_user)):
    try:
        owner = _effective_owner(user["id"])
        # Hosted safety: use only the signed-in user's stored OpenAI key.
        user_openai_key = auth_store.get_user_key(owner, "openai") or ""
        return audit_prompt(
            system_prompt=req.system_prompt,
            use_case=req.use_case,
            tools=req.tools or [],
            retrieves_external_content=req.retrieves_external_content,
            handles_secrets=req.handles_secrets,
            output_schema=req.output_schema,
            high_risk_actions=req.high_risk_actions or [],
            dynamic=req.dynamic,
            llm=req.llm,
            model=req.model,
            api_key=user_openai_key,
        )
    except Exception:
        log.exception("prompt audit failed")
        raise HTTPException(status_code=400, detail="prompt audit failed")


@app.post("/api/pipeline/analyze")
def api_pipeline_analyze(req: PipelineAnalyzeRequest, user: dict = Depends(require_user)):
    try:
        return analyze_pipeline(
            req.stages,
            system_prompt=req.system_prompt,
            user_prompt=req.prompt,
            output_schema=req.output_schema,
        )
    except Exception:
        log.exception("pipeline analyze failed")
        raise HTTPException(status_code=400, detail="pipeline analysis failed")


@app.post("/api/feedback")
def api_feedback(body: FeedbackIn, user: dict = Depends(require_user)):
    owner = _effective_owner(user["id"])
    rec = store.get(body.diagnosis_id, owner=owner)
    if rec is None:
        raise HTTPException(status_code=404, detail="diagnosis not found")
    primary = (rec.get("diagnosis") or {}).get("primary") or {}
    event = feedback_store.add({
        "owner": owner,
        "diagnosis_id": body.diagnosis_id,
        "failure": primary.get("failure") or "healthy",
        "confidence": primary.get("confidence"),
        "accepted": body.accepted,
        "fix_worked": body.fix_worked,
        "note": body.note,
    })
    return {"ok": True, "feedback": event, "confidence": feedback_store.stats(owner=owner)}


@app.get("/api/confidence")
def api_confidence(user: dict = Depends(require_user)):
    return feedback_store.stats(owner=_effective_owner(user["id"]))


@app.get("/api/diagnoses")
def api_diagnoses(failure: str | None = None,
                  q: str | None = Query(None, max_length=200),
                  limit: int = Query(100, ge=1, le=500),
                  user: dict = Depends(require_user)):
    return {"items": store.list(owner=_effective_owner(user["id"]), failure=failure, q=q, limit=limit)}


@app.get("/api/health")
def api_health():
    """Liveness/readiness probe (no auth) — used by Docker HEALTHCHECK / LBs."""
    db = db_status()
    return {"status": "ok" if db["connected"] else "degraded", "database": db}


@app.get("/api/stats")
def api_stats(user: dict = Depends(require_user)):
    return store.stats(owner=_effective_owner(user["id"]))


@app.get("/api/auth/debug")
def api_auth_debug(request: Request):
    """Dev-only: diagnose cookie/session state. Only available when DEBUG=true."""
    if not os.environ.get("DEBUG"):
        raise HTTPException(status_code=404)
    user = current_user(request)
    cookie = request.cookies.get(SESSION_COOKIE)
    trust_proxy = os.environ.get("DEBUGAI_TRUST_PROXY")
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return {
        "cookie_present": bool(cookie),
        "cookie_length": len(cookie) if cookie else 0,
        "user": _client_user(user) if user else None,
        "scheme": request.url.scheme,
        "trust_proxy": bool(trust_proxy),
        "forwarded_proto": forwarded_proto,
        "effective_secure": bool(trust_proxy) and forwarded_proto == "https" or request.url.scheme == "https",
    }


@app.get("/api/thresholds")
def api_thresholds(user: dict = Depends(require_user)):
    """Current adaptive-calibration state (regime, baseline, per-signal values)."""
    return tstore_for(_effective_owner(user["id"])).details()


@app.delete("/api/diagnoses")
def api_clear(user: dict = Depends(require_user)):
    owner = _effective_owner(user["id"])
    store.purge(owner)
    trace_store.purge(owner)
    tstore_for(owner).reset()
    return {"ok": True}


# --- observability (traces / sessions / metrics) ---
class TraceIn(BaseModel):
    """Validated trace-ingest shape — prevents storing arbitrary unbounded JSON."""
    model_config = {"extra": "ignore"}

    name: str = Field(default="trace", max_length=200)
    session_id: str | None = Field(default=None, max_length=200)
    status: str = Field(default="ok", max_length=20)
    model: str | None = Field(default=None, max_length=200)
    duration_ms: float = Field(default=0.0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    spans: list[dict] = Field(default_factory=list, max_length=200)
    scores: list[dict] = Field(default_factory=list, max_length=50)
    metadata: dict = Field(default_factory=dict)


@app.post("/api/traces")
def api_ingest_trace(trace: TraceIn, user: dict = Depends(require_user)):
    """Ingest a trace emitted by the SDK (wrap_llm on_trace) or a client."""
    data = trace.model_dump()
    data["id"] = uuid.uuid4().hex[:12]
    data["owner"] = _effective_owner(user["id"])
    data["timestamp"] = datetime.now(timezone.utc).isoformat()
    return trace_store.add(data)


@app.get("/api/traces")
def api_traces(session: str | None = None, status: str | None = None,
               limit: int = Query(100, ge=1, le=500),
               user: dict = Depends(require_user)):
    return {"items": trace_store.list(owner=_effective_owner(user["id"]), session=session,
                                      status=status, limit=limit)}


@app.get("/api/traces/{trace_id}")
def api_trace(trace_id: str, user: dict = Depends(require_user)):
    t = trace_store.get(trace_id, owner=_effective_owner(user["id"]))
    if t is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return t


@app.get("/api/sessions")
def api_sessions(user: dict = Depends(require_user)):
    return {"items": trace_store.sessions(owner=_effective_owner(user["id"]))}


@app.get("/api/observability/stats")
def api_obs_stats(user: dict = Depends(require_user)):
    return trace_store.stats(owner=_effective_owner(user["id"]))


def _grounded_stub(system_prompt, user_prompt, chunks, temperature):
    """Offline demo rerun: a model that answers strictly from the context."""
    ctx = " ".join(chunks)
    return ("Per the provided context: " + ctx) if ctx else "I don't have that information."


def _claude_rerun(api_key: str, model: str = "claude-haiku-4-5-20251001"):
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=30.0, max_retries=2)

    def rerun(system_prompt, user_prompt, chunks, temperature):
        ctx = "\n\n".join(f"[chunk {i}] {c}" for i, c in enumerate(chunks))
        msg = client.messages.create(
            model=model, max_tokens=500,
            system=system_prompt or "Answer the user's question.",
            temperature=temperature if temperature is not None else 1.0,
            messages=[{"role": "user", "content": f"Context:\n{ctx}\n\nQuestion: {user_prompt}"}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    return rerun


def _openai_rerun(api_key: str, model: str | None = None):
    model = model or os.environ.get("DEBUGAI_JUDGE_MODEL", "gpt-5.5")
    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=30.0, max_retries=2)

    def rerun(system_prompt, user_prompt, chunks, temperature):
        ctx = "\n\n".join(f"[chunk {i}] {c}" for i, c in enumerate(chunks))
        content = (f"Context:\n{ctx}\n\n" if ctx else "") + f"Student: {user_prompt}"
        msg = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt or "Answer the question."},
                      {"role": "user", "content": content}],
        )
        return msg.choices[0].message.content or ""

    return rerun


def _rerun_for(simulate: bool, user_id: str):
    """Pick a rerun target.

    Live reruns use only the signed-in user's stored key. Server env keys are not
    used here, so public hosted users cannot spend the operator's LLM credits.
    """
    if simulate:
        return _grounded_stub, "simulated"
    anthropic_key = auth_store.get_user_key(user_id, "anthropic")
    if anthropic_key:
        return _claude_rerun(anthropic_key), "live"
    openai_key = auth_store.get_user_key(user_id, "openai")
    if openai_key:
        return _openai_rerun(openai_key), "live"
    return None, "proposed"


def _capture_from_input(inp: dict) -> CaptureRecord:
    return CaptureRecord(
        user_prompt=inp["prompt"], llm_output=inp["output"],
        system_prompt=inp.get("system_prompt", ""),
        retrieved_chunks=inp.get("chunks") or [],
        similarity_scores=inp.get("similarity_scores") or [],
        retrieval_query=inp.get("retrieval_query"),
        temperature=inp.get("temperature"), max_tokens=inp.get("max_tokens"),
        context_window=inp.get("context_window"), latency_ms=inp.get("latency_ms"),
        tool_calls=inp.get("tool_calls") or [],
        tools_expected=inp.get("tools_expected") or [],
        response_schema=inp.get("response_schema"),
    )


def _run_fix(diagnosis: dict, record: CaptureRecord, simulate: bool, user_id: str) -> dict | None:
    rerun, mode = _rerun_for(simulate, user_id)
    report = propose_fix(diagnosis, record, rerun=rerun)
    if report is None:
        return None
    out = report.to_dict()
    out["rerun_mode"] = mode
    return out


@app.post("/api/fix/{diagnosis_id}")
def api_fix(diagnosis_id: str, simulate: bool = True, user: dict = Depends(require_user)):
    """Run the diagnose-fix-verify loop for a stored diagnosis (§8)."""
    rec = store.get(diagnosis_id, owner=_effective_owner(user["id"]))
    if rec is None:
        raise HTTPException(status_code=404, detail="diagnosis not found")
    out = _run_fix(rec["diagnosis"], _capture_from_input(rec["input"]), simulate, user["id"])
    if out is None:
        return {"verdict": "none", "reason": "no agent for this diagnosis (or healthy)"}
    return out


class DebugRequest(AnalyzeRequest):
    run_fix: bool = True
    simulate: bool = True


class BetaDebugWorkflowRequest(DebugRequest):
    use_case: str = Field(default="", max_length=MAX_TEXT)
    audit_tools: list[str] | None = Field(default=None, max_length=100)
    high_risk_actions: list[str] | None = Field(default=None, max_length=100)
    retrieves_external_content: bool = False
    handles_secrets: bool = False
    stages: list[dict] | None = Field(default=None, max_length=100)


@app.post("/api/debug")
def api_debug(req: DebugRequest, user: dict = Depends(require_user)):
    """One shot: paste a failing case (+ describe the issue) → diagnose → propose
    & verify a fix. Returns the stored diagnosis record and the fix report."""
    if req.session_id is None:
        req.session_id = "debug-workbench"
    try:
        rec = _run(req, _effective_owner(user["id"]), judge=True)  # judge runs ONLY here (Debug a bug)
    except Exception:
        log.exception("debug failed")
        raise HTTPException(status_code=400, detail="diagnosis failed")
    fix = None
    if req.run_fix and not rec["diagnosis"].get("healthy"):
        fix = _run_fix(rec["diagnosis"], _capture_from_input(rec["input"]), req.simulate, user["id"])
    return {"record": rec, "fix": fix}


@app.post("/api/beta/debug-workflow")
def api_beta_debug_workflow(req: BetaDebugWorkflowRequest, user: dict = Depends(require_user)):
    """Beta workflow: diagnose a failing case, propose/verify a fix, audit the
    prompt, analyze pipeline stages when supplied, and return a regression
    artifact the team can save in CI."""
    if req.session_id is None:
        req.session_id = "beta-debug-workflow"
    try:
        rec = _run(req, _effective_owner(user["id"]), judge=True)
    except Exception:
        log.exception("beta debug workflow failed")
        raise HTTPException(status_code=400, detail="diagnosis failed")

    fix = None
    if req.run_fix and not rec["diagnosis"].get("healthy"):
        fix = _run_fix(rec["diagnosis"], _capture_from_input(rec["input"]), req.simulate, user["id"])

    report = debug_report(
        prompt=req.prompt,
        output=req.output,
        system_prompt=req.system_prompt,
        chunks=req.chunks,
        similarity_scores=req.similarity_scores,
        retrieval_query=req.retrieval_query,
        temperature=req.temperature,
        context_window=req.context_window,
        tool_calls=req.tool_calls,
        tools_expected=req.tools_expected,
        response_schema=req.response_schema,
        run_fix=False,
        explain_with_llm=False,
    )
    report["fix_report"] = fix

    prompt_audit = audit_prompt(
        system_prompt=req.system_prompt,
        use_case=req.use_case,
        tools=req.audit_tools or req.tools_expected or [],
        retrieves_external_content=req.retrieves_external_content or bool(req.chunks),
        handles_secrets=req.handles_secrets,
        output_schema=req.response_schema,
        high_risk_actions=req.high_risk_actions or [],
        dynamic=True,
        llm=False,
        api_key="",
    )
    pipeline = analyze_pipeline(
        req.stages or [],
        system_prompt=req.system_prompt,
        user_prompt=req.prompt,
        output_schema=req.response_schema,
    )
    return {
        "record": rec,
        "fix": fix,
        "debug_report": report,
        "prompt_audit": prompt_audit,
        "pipeline": pipeline,
        "next_actions": [
            "Apply the highest-confidence fix.",
            "Save the regression artifact in CI.",
            "Add this case to the failure corpus.",
            "Rerun dynamic prompt attacks before deploy.",
        ],
    }


@app.post("/api/playground")
def api_playground(req: DebugRequest, user: dict = Depends(require_user)):
    """Non-storing analyze + proposed fix — for the live editing playground."""
    try:
        diagnosis = analyze(
            prompt=req.prompt, output=req.output, system_prompt=req.system_prompt,
            chunks=req.chunks, similarity_scores=req.similarity_scores,
            retrieval_query=req.retrieval_query, temperature=req.temperature,
            max_tokens=req.max_tokens, context_window=req.context_window,
            model_name=req.model_name, explain_with_llm=req.explain_with_llm,
            tool_calls=req.tool_calls, tools_expected=req.tools_expected,
            response_schema=req.response_schema,
            thresholds=tstore_for(user["id"]).current(),
            openai_api_key=auth_store.get_user_key(user["id"], "openai") or "",
            anthropic_api_key=auth_store.get_user_key(user["id"], "anthropic") or "",
            # No judge here: the playground auto-analyzes on every keystroke, so an
            # LLM judge call per keystroke would be wasteful. Judge runs only in
            # the "Debug a bug" workbench (/api/debug).
        )
    except Exception:
        log.exception("playground analyze failed")
        raise HTTPException(status_code=400, detail="analysis failed")
    fix = None
    if req.run_fix and not diagnosis.get("healthy"):
        rec = _capture_from_input({
            "prompt": req.prompt, "output": req.output, "system_prompt": req.system_prompt,
            "chunks": req.chunks, "similarity_scores": req.similarity_scores,
            "retrieval_query": req.retrieval_query, "temperature": req.temperature,
            "max_tokens": req.max_tokens, "context_window": req.context_window,
            "tool_calls": req.tool_calls, "tools_expected": req.tools_expected,
            "response_schema": req.response_schema,
        })
        fix = _run_fix(diagnosis, rec, req.simulate, user["id"])
    return {"diagnosis": diagnosis, "ui": to_card(diagnosis), "fix": fix}


def _seed_for(owner: str) -> int:
    """Seed the labeled sample dataset for one account."""
    cases = json.loads(DATASET.read_text())["cases"] + example_cases()
    for c in cases:
        kwargs = {k: v for k, v in c.items() if k not in ("id", "expected", "_comment", "label")}
        req = AnalyzeRequest(label=c.get("id") or c.get("label"), explain_with_llm=False,
                             session_id="sample-data", model_name="claude-haiku-4-5",
                             **kwargs)
        _run(req, owner)
    return len(cases)


class LLMKeyIn(BaseModel):
    key: str = Field(max_length=500)


@app.put("/api/account/llm-keys/{provider}")
def api_set_llm_key(provider: str, body: LLMKeyIn, user: dict = Depends(require_user)):
    """Save an encrypted LLM API key (openai or anthropic) for the user."""
    try:
        auth_store.set_user_key(user["id"], provider, body.key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "provider": provider}


@app.delete("/api/account/llm-keys/{provider}")
def api_delete_llm_key(provider: str, user: dict = Depends(require_user)):
    auth_store.delete_user_key(user["id"], provider)
    return {"ok": True}


@app.get("/api/account/llm-keys")
def api_get_llm_keys(user: dict = Depends(require_user)):
    """Return which providers the user has keys set (never the key itself)."""
    return auth_store.get_user_keys(user["id"])


@app.get("/admin")
def admin_page(request: Request):
    if not auth_store.is_staff((current_user(request) or {}).get("id", "")):
        raise HTTPException(status_code=403, detail="Staff only")
    return _page("admin.html")


@app.get("/api/admin/stats")
def api_admin_stats(user: dict = Depends(require_user)):
    if not auth_store.is_staff(user["id"]):
        raise HTTPException(status_code=403, detail="Staff only")
    diag_stats = store.stats()
    trace_stats = trace_store.stats()
    leads = lead_store.stats()
    activation = auth_store.activation_stats()
    diagnosis_users = {r.get("owner") for r in store.list(limit=500) if r.get("owner")}
    trace_users = {t.get("owner") for t in trace_store.list(limit=500) if t.get("owner")}
    activated_users = diagnosis_users | trace_users
    return {
        "users": auth_store.user_count(),
        "leads": leads,
        "activation": {
            **activation,
            "users_with_diagnoses": len(diagnosis_users),
            "users_with_traces": len(trace_users),
            "activated_product_users": len(activated_users),
        },
        "funnel": {
            "leads": leads["total"],
            "accounts": auth_store.user_count(),
            "users_with_api_tokens": activation["users_with_api_tokens"],
            "activated_product_users": len(activated_users),
        },
        "diagnoses": diag_stats,
        "traces": trace_stats,
        "recent_users": auth_store.recent_users(10),
    }


class OrgCreate(BaseModel):
    name: str = Field(max_length=120)


class InviteCreate(BaseModel):
    email: str = Field(max_length=320)
    role: str = Field(default="member", pattern="^(admin|member)$")


@app.post("/api/orgs")
def api_org_create(body: OrgCreate, user: dict = Depends(require_user)):
    try:
        org = auth_store.create_org(body.name, user["id"])
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return org


@app.get("/api/orgs")
def api_org_list(user: dict = Depends(require_user)):
    return {"items": auth_store.list_user_orgs(user["id"])}


@app.get("/api/orgs/{org_id}")
def api_org_get(org_id: str, user: dict = Depends(require_user)):
    if not auth_store.user_org_role(org_id, user["id"]):
        raise HTTPException(status_code=403, detail="Not a member of this organisation.")
    org = auth_store.get_org(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found.")
    members = auth_store.list_org_members(org_id)
    return {**org, "members": members}


@app.delete("/api/orgs/{org_id}/members/{member_id}")
def api_org_remove_member(org_id: str, member_id: str, user: dict = Depends(require_user)):
    role = auth_store.user_org_role(org_id, user["id"])
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Admin or owner required.")
    if member_id == user["id"] and role == "owner":
        raise HTTPException(status_code=400, detail="Owner cannot remove themselves.")
    auth_store.remove_org_member(org_id, member_id)
    return {"ok": True}


@app.post("/api/orgs/{org_id}/invites")
def api_org_invite(org_id: str, body: InviteCreate, user: dict = Depends(require_user)):
    role = auth_store.user_org_role(org_id, user["id"])
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Admin or owner required.")
    org = auth_store.get_org(org_id)
    try:
        token = auth_store.create_invite(org_id, body.email, body.role)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Send invite email (fire-and-forget)
    import threading
    from server.email import send_invite
    threading.Thread(target=send_invite,
                     args=(body.email, org["name"], token), daemon=True).start()
    return {"ok": True, "token": token}  # token also returned for debugging


@app.get("/api/orgs/invites/{token}")
def api_invite_info(token: str):
    """Public endpoint — shows org name for the accept-invite page."""
    invite = auth_store.get_invite(token)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found or expired.")
    return {"org_name": invite["org_name"], "role": invite["role"]}


@app.post("/api/orgs/invites/{token}/accept")
def api_invite_accept(token: str, user: dict = Depends(require_user)):
    try:
        invite = auth_store.accept_invite(token, user["id"])
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "org_id": invite["org_id"], "org_name": invite["org_name"]}


class WorkspaceSwitch(BaseModel):
    org_id: str | None = None  # None = personal workspace


@app.patch("/api/user/workspace")
def api_switch_workspace(body: WorkspaceSwitch, user: dict = Depends(require_user)):
    """Switch between personal workspace and an org workspace."""
    try:
        auth_store.set_active_workspace(user["id"], body.org_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "active_org_id": body.org_id}


@app.get("/api/user/workspace")
def api_get_workspace(user: dict = Depends(require_user)):
    active = auth_store.get_active_workspace(user["id"])
    orgs = auth_store.list_user_orgs(user["id"])
    return {"active_org_id": active, "orgs": orgs}


@app.post("/api/seed")
def api_seed(user: dict = Depends(require_user)):
    """(Re)seed the signed-in account with the labeled sample dataset."""
    try:
        return {"seeded": _seed_for(_effective_owner(user["id"]))}
    except Exception:
        log.exception("seed failed")
        raise HTTPException(status_code=500, detail="seeding failed")


# --- static: design system + dashboard ---
app.mount("/ds", StaticFiles(directory=DS_DIR), name="ds")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _page(name: str) -> FileResponse:
    # no-store so the browser never serves a gated page from cache without
    # re-hitting the auth gate (otherwise a logged-out user clicking "Dashboard"
    # could see a cached, seemingly-logged-in page).
    return FileResponse(STATIC_DIR / name, headers={"Cache-Control": "no-store"})


def _gated(request: Request, name: str):
    """Serve an app page, or redirect to /login when not authenticated."""
    if current_user(request) is None:
        return RedirectResponse("/login", status_code=302)
    return _page(name)


@app.get("/accept-invite")
def accept_invite_page():
    return _page("accept-invite.html")


@app.get("/")
def home():
    return _page("home.html")


@app.get("/pricing")
def pricing():
    return _page("pricing.html")


@app.get("/docs")
def docs():
    return _page("docs.html")


@app.get("/login")
def login_page():
    return _page("login.html")


@app.get("/register")
def register_page():
    return _page("register.html")


@app.get("/verify-email")
def verify_email_page():
    return _page("verify-email.html")


@app.get("/reset-password")
def reset_password_page():
    return _page("reset-password.html")


@app.get("/account")
def account_page(request: Request):
    return _gated(request, "account.html")


@app.get("/playground")
def playground(request: Request):
    return _gated(request, "playground.html")


@app.get("/dashboard")
def dashboard(request: Request):
    return _gated(request, "dashboard.html")
