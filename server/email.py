"""Transactional email via Resend (free tier: 3,000 emails/month).

All sends are fire-and-forget — a failure never breaks the request that triggered it.
Set RESEND_API_KEY in the environment. If unset, emails are silently skipped
(works for local dev without any email setup).

Get a free key at: https://resend.com/api-keys
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("debugai.email")

FROM_ADDRESS = os.environ.get("DEBUGAI_FROM_EMAIL", "DebugAI <hello@debugerai.com>")
APP_URL = os.environ.get("DEBUGAI_APP_URL", "https://debugerai.onrender.com")


def _client():
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        return None
    try:
        import resend
        resend.api_key = key
        return resend
    except ImportError:
        return None


def send_welcome(to_email: str, name: str) -> None:
    """Fire a welcome email after registration. Fails silently if unconfigured."""
    client = _client()
    if not client:
        return

    first = name.split()[0] if name else "there"
    html = f"""
<!DOCTYPE html>
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0d0c0a;color:#f4f0e6;padding:40px 24px;max-width:520px;margin:0 auto">
  <p style="font-size:20px;font-weight:700;margin:0 0 8px">
    <span style="color:#EF9F27">Debug</span>AI
  </p>
  <h1 style="font-size:22px;font-weight:700;margin:0 0 16px;line-height:1.3">
    Welcome, {first}. Time to stop guessing.
  </h1>
  <p style="color:#aba593;line-height:1.65;margin:0 0 24px">
    DebugAI gives every LLM failure a name, a confidence score, and a specific fix.
    Paste a failing call into the workbench and see a real diagnosis in seconds.
  </p>
  <a href="{APP_URL}/dashboard"
     style="display:inline-block;background:#EF9F27;color:#1a1304;font-weight:700;
            padding:12px 28px;border-radius:6px;text-decoration:none;font-size:15px">
    Start debugging →
  </a>
  <hr style="border:none;border-top:1px solid #2b2820;margin:32px 0" />
  <p style="color:#757061;font-size:12px;margin:0">
    Install the SDK: <code style="color:#f3bb5b">pip install debugerai</code><br/>
    Questions? Reply to this email — it goes straight to the founder.
  </p>
</body>
</html>"""

    try:
        client.Emails.send({
            "from": FROM_ADDRESS,
            "to": [to_email],
            "subject": "Welcome to DebugAI — your first diagnosis takes 2 minutes",
            "html": html,
        })
        log.info("welcome email sent to %s", to_email)
    except Exception as e:
        log.warning("welcome email failed (%s)", e)
