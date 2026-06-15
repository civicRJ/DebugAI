"""Production security middleware: security headers, opt-in API-key auth, and
an in-memory per-client rate limiter.

All three are configured via environment variables so the local demo stays
zero-config while a hosted deployment can lock down:

    DEBUGAI_API_KEY        if set, /api/* requires a matching X-API-Key header
    DEBUGAI_RATE_LIMIT     max /api/* requests per minute per client (default 240)
    DEBUGAI_TRUST_PROXY    if set, honour the first X-Forwarded-For hop (behind a proxy)
"""

from __future__ import annotations

import hmac
import os
import threading
import time
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_API_PREFIX = "/api"
_SESSION_COOKIE = "debugai_session"
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_BODY_BYTES = 4 * 1024 * 1024  # 4 MB — reject oversized request bodies (DoS guard)

# Strict CSP: all scripts are self-hosted (vendored React + esbuild bundles, no
# CDN, no in-browser Babel), so script-src needs no 'unsafe-eval'/'unsafe-inline'
# or remote origins. style-src keeps 'unsafe-inline' for React inline style attrs;
# Google Fonts (stylesheet + font files) are allowed (with system-font fallback
# offline). Framing, plugins, and base-tag hijacking are blocked.
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "img-src 'self' data:; media-src 'self'; "
    "connect-src 'self'; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
)
_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": _CSP,
    "Cross-Origin-Opener-Policy": "same-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        resp: Response = await call_next(request)
        for k, v in _HEADERS.items():
            resp.headers.setdefault(k, v)
        return resp


class APIKeyMiddleware(BaseHTTPMiddleware):
    """When DEBUGAI_API_KEY is set, require it on /api/* via X-API-Key (constant
    -time compared). No key configured → open (local-dev default)."""

    async def dispatch(self, request: Request, call_next):
        key = os.environ.get("DEBUGAI_API_KEY")
        if key and request.url.path.startswith(_API_PREFIX):
            supplied = request.headers.get("x-api-key", "")
            if not hmac.compare_digest(supplied, key):
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)


class BodyLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose declared body exceeds MAX_BODY_BYTES (DoS guard)."""

    async def dispatch(self, request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > MAX_BODY_BYTES:
            return JSONResponse({"detail": "request body too large"}, status_code=413)
        return await call_next(request)


def _csrf_strict() -> bool:
    return bool(os.environ.get("DEBUGAI_STRICT_CSRF") or os.environ.get("DATABASE_URL"))


def _origin_value(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except Exception:
        return None
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _expected_origin(request: Request) -> str:
    if os.environ.get("DEBUGAI_TRUST_PROXY"):
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    else:
        proto = request.url.scheme
        host = request.headers.get("host", "")
    return f"{proto.lower()}://{host.lower()}"


class CSRFMiddleware(BaseHTTPMiddleware):
    """Origin-check cookie-authenticated unsafe API calls.

    Browser sessions authenticate with an httpOnly cookie. In production, any
    mutating /api request carrying that cookie must come from the same origin.
    Token-authenticated SDK calls without cookies are unaffected.
    """

    async def dispatch(self, request: Request, call_next):
        if (
            request.url.path.startswith(_API_PREFIX)
            and request.method.upper() in _UNSAFE_METHODS
            and request.cookies.get(_SESSION_COOKIE)
            and _csrf_strict()
        ):
            supplied = _origin_value(request.headers.get("origin"))
            if supplied is None:
                supplied = _origin_value(request.headers.get("referer"))
            if supplied != _expected_origin(request):
                return JSONResponse({"detail": "csrf origin check failed"}, status_code=403)
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window per-client limiter on /api/* (in-memory, single-process)."""

    def __init__(self, app, per_minute: int | None = None):
        super().__init__(app)
        self._limit = per_minute or int(os.environ.get("DEBUGAI_RATE_LIMIT", "240"))
        self._window = 60.0
        self._lock = threading.Lock()
        self._hits: dict[str, tuple[float, int]] = {}

    def _client(self, request: Request) -> str:
        if os.environ.get("DEBUGAI_TRUST_PROXY"):
            fwd = request.headers.get("x-forwarded-for")
            if fwd:
                return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        if self._limit <= 0 or not request.url.path.startswith(_API_PREFIX):
            return await call_next(request)
        now = time.monotonic()
        ip = self._client(request)
        with self._lock:
            start, count = self._hits.get(ip, (now, 0))
            if now - start >= self._window:
                start, count = now, 0
            count += 1
            self._hits[ip] = (start, count)
            # opportunistic cleanup so the dict can't grow unbounded
            if len(self._hits) > 10_000:
                self._hits = {k: v for k, v in self._hits.items() if now - v[0] < self._window}
            over = count > self._limit
            retry = max(1, int(self._window - (now - start)))
        if over:
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429,
                                headers={"Retry-After": str(retry)})
        return await call_next(request)


_AUTH_PATHS = {"/api/auth/login", "/api/auth/register"}


class AuthRateLimitMiddleware(BaseHTTPMiddleware):
    """Stricter rate limit on auth endpoints (login + register) to prevent
    brute-force and registration spam. Default 10 req/min/IP, separate from
    the general DEBUGAI_RATE_LIMIT. Set DEBUGAI_AUTH_RATE_LIMIT=0 to disable."""

    def __init__(self, app, per_minute: int | None = None):
        # Default 30/min — aggressive enough to block brute-force, tolerant enough
        # for developers who test the login/register flow repeatedly.
        # Override with DEBUGAI_AUTH_RATE_LIMIT env var; set to 0 to disable.
        per_minute = per_minute if per_minute is not None else int(os.environ.get("DEBUGAI_AUTH_RATE_LIMIT", "30"))
        super().__init__(app)
        self._limit = per_minute
        self._window = 60.0
        self._lock = threading.Lock()
        self._hits: dict[str, tuple[float, int]] = {}

    def _client(self, request: Request) -> str:
        if os.environ.get("DEBUGAI_TRUST_PROXY"):
            fwd = request.headers.get("x-forwarded-for")
            if fwd:
                return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        # Read limit dynamically so DEBUGAI_AUTH_RATE_LIMIT=0 works at runtime
        # (important for tests that set env vars after module import).
        effective_limit = int(os.environ.get("DEBUGAI_AUTH_RATE_LIMIT", str(self._limit)))
        if effective_limit <= 0 or request.url.path not in _AUTH_PATHS:
            return await call_next(request)
        now = time.monotonic()
        ip = self._client(request)
        with self._lock:
            start, count = self._hits.get(ip, (now, 0))
            if now - start >= self._window:
                start, count = now, 0
            count += 1
            self._hits[ip] = (start, count)
            if len(self._hits) > 10_000:
                self._hits = {k: v for k, v in self._hits.items() if now - v[0] < self._window}
            over = count > effective_limit
            retry = max(1, int(self._window - (now - start)))
        if over:
            return JSONResponse({"detail": "too many attempts — try again later"},
                                status_code=429, headers={"Retry-After": str(retry)})
        return await call_next(request)


def install(app) -> None:
    """Attach the security stack. Starlette runs the LAST-added middleware
    outermost, so add inner→outer to get this execution order:

        SecurityHeaders → RateLimit → BodyLimit → route

    (Security headers therefore decorate even 429/413 responses; rate limiting
    fires before any work is done.)

    Note: account auth (session cookies) is enforced per-route via the
    `require_user` dependency in app.py, which supersedes the old
    DEBUGAI_API_KEY gate. APIKeyMiddleware remains available for deployments
    that still want a coarse network-level key in front of everything.
    """
    app.add_middleware(AuthRateLimitMiddleware)   # auth endpoints: 10 req/min/IP
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
