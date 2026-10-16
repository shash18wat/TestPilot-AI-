"""Google OAuth configuration and signed local session helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

SESSION_COOKIE = "testpilot_session"
OAUTH_STATE_COOKIE = "testpilot_oauth_state"
SESSION_TTL_SECONDS = 8 * 60 * 60
OAUTH_STATE_TTL_SECONDS = 10 * 60


def settings() -> dict[str, Any]:
    return {
        "client_id": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/api/auth/google/callback").strip(),
        "frontend_url": os.getenv("TESTPILOT_FRONTEND_URL", "http://127.0.0.1:5173").strip().rstrip("/"),
        "owner_email": os.getenv("TESTPILOT_OWNER_EMAIL", "").strip().casefold(),
        "session_secret": os.getenv("TESTPILOT_SESSION_SECRET", ""),
        "cookie_secure": os.getenv("TESTPILOT_COOKIE_SECURE", "true").lower() in {"1", "true", "yes"},
    }


def configured() -> bool:
    values = settings()
    return all((
        values["client_id"], values["client_secret"], values["redirect_uri"],
        values["frontend_url"], values["owner_email"], len(values["session_secret"]) >= 32,
    ))


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def issue_session(email: str) -> str:
    values = settings()
    owner = values["owner_email"]
    if not configured() or email.strip().casefold() != owner:
        raise ValueError("Session can only be issued to the configured owner account.")
    now = int(time.time())
    payload = _b64(json.dumps({"email": owner, "iat": now, "exp": now + SESSION_TTL_SECONDS}, separators=(",", ":")).encode("utf-8"))
    signature = _b64(hmac.new(values["session_secret"].encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def read_session(token: str | None) -> dict[str, Any] | None:
    if not token or not configured():
        return None
    try:
        payload, signature = token.split(".", 1)
        values = settings()
        expected = _b64(hmac.new(values["session_secret"].encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(raw)
        email = str(claims.get("email", "")).strip().casefold()
        if email != values["owner_email"] or int(claims.get("exp", 0)) <= int(time.time()):
            return None
        return {"email": email}
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeError):
        return None
