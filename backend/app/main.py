from __future__ import annotations

import json
import os
import re
import secrets
import time
import base64
import asyncio
import hashlib
import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import aiohttp
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, database
from .ai_service import explain_failure, suggestions_for
from .openapi_parser import SpecError, parse_spec
from .security import PinnedResolver, TargetRejected, configured_target_hosts, validate_target_url

load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    yield


app = FastAPI(title="TestPilot AI API", version="1.0.0", description="Secure API testing workspace", lifespan=lifespan)
origins = [item.strip() for item in os.getenv("TESTPILOT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if item.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


def require_auth(request: Request) -> dict[str, str]:
    if not auth.configured():
        raise HTTPException(503, "Google sign-in is not configured. Set the OAuth and session values in the backend .env.")
    principal = auth.read_session(request.cookies.get(auth.SESSION_COOKIE))
    if not principal:
        raise HTTPException(401, "Sign in with the permitted Google account to continue.")
    return principal


@app.get("/api/auth/session")
def auth_session(request: Request) -> dict[str, Any]:
    principal = auth.read_session(request.cookies.get(auth.SESSION_COOKIE))
    return {"configured": auth.configured(), "authenticated": principal is not None, "email": principal["email"] if principal else None}


def _oauth_failure(code: str) -> RedirectResponse:
    values = auth.settings()
    response = RedirectResponse(f"{values['frontend_url']}/?auth_error={quote(code)}", status_code=303)
    response.delete_cookie(auth.OAUTH_STATE_COOKIE, path="/api/auth/google/callback")
    return response


@app.get("/api/auth/google/start")
def google_start():
    values = auth.settings()
    if not auth.configured():
        raise HTTPException(503, "Google sign-in is not configured. Set the OAuth and session values in the backend .env.")
    state, verifier, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    with database.connect() as db:
        db.execute("INSERT INTO oauth_states(state, code_verifier, nonce, expires_at) VALUES (?, ?, ?, ?)", (state, verifier, nonce, int(time.time()) + auth.OAUTH_STATE_TTL_SECONDS))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    params = {
        "client_id": values["client_id"], "redirect_uri": values["redirect_uri"], "response_type": "code",
        "scope": "openid email profile", "state": state, "nonce": nonce, "prompt": "select_account",
        "code_challenge": challenge, "code_challenge_method": "S256",
    }
    response = RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params), status_code=302)
    response.set_cookie(auth.OAUTH_STATE_COOKIE, state, max_age=auth.OAUTH_STATE_TTL_SECONDS, httponly=True, secure=values["cookie_secure"], samesite="lax", path="/api/auth/google/callback")
    return response


@app.get("/api/auth/google/callback")
async def google_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    values = auth.settings()
    if not auth.configured():
        return _oauth_failure("setup")
    cookie_state = request.cookies.get(auth.OAUTH_STATE_COOKIE)
    if error or not code or not state or not cookie_state or not hmac.compare_digest(state, cookie_state):
        return _oauth_failure("sign_in")
    with database.connect() as db:
        row = db.execute("SELECT code_verifier, nonce, expires_at FROM oauth_states WHERE state = ?", (state,)).fetchone()
        db.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
    if row is None or int(row["expires_at"]) < int(time.time()):
        return _oauth_failure("sign_in")
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False, follow_redirects=False) as client:
            token_response = await client.post("https://oauth2.googleapis.com/token", data={
                "code": code, "client_id": values["client_id"], "client_secret": values["client_secret"],
                "redirect_uri": values["redirect_uri"], "grant_type": "authorization_code", "code_verifier": row["code_verifier"],
            })
        if token_response.status_code != 200:
            return _oauth_failure("sign_in")
        id_token = token_response.json().get("id_token")
        if not id_token:
            return _oauth_failure("sign_in")
        def verify_id_token():
            import requests
            from google.auth.transport.requests import Request as GoogleRequest
            from google.oauth2 import id_token as google_id_token
            session = requests.Session()
            session.trust_env = False
            try:
                return google_id_token.verify_oauth2_token(id_token, GoogleRequest(session=session), values["client_id"])
            finally:
                session.close()
        claims = await asyncio.to_thread(verify_id_token)
        if not hmac.compare_digest(str(claims.get("nonce", "")), str(row["nonce"])):
            return _oauth_failure("sign_in")
        email = str(claims.get("email", "")).strip().casefold()
        if claims.get("email_verified") is not True or email != values["owner_email"]:
            return _oauth_failure("account")
        session_token = auth.issue_session(email)
    except Exception:
        return _oauth_failure("sign_in")
    response = RedirectResponse(values["frontend_url"] + "/", status_code=303)
    response.delete_cookie(auth.OAUTH_STATE_COOKIE, path="/api/auth/google/callback")
    response.set_cookie(auth.SESSION_COOKIE, session_token, max_age=auth.SESSION_TTL_SECONDS, httponly=True, secure=values["cookie_secure"], samesite="lax", path="/")
    return response


@app.post("/api/auth/logout")
def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return response


class ImportSpec(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1)


class RunRequest(BaseModel):
    spec_id: int
    operation_id: str = Field(max_length=32)
    target_base_url: str = Field(min_length=1, max_length=2048)
    path_params: dict[str, Any] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    expected_status: int | None = Field(default=None, ge=100, le=599)
    expect_json: bool = False


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "ai_configured": bool(os.getenv("GEMINI_API_KEY", "").strip()), "auth_configured": auth.configured()}


@app.get("/api/settings")
def get_settings(_: dict[str, str] = Depends(require_auth)) -> dict[str, Any]:
    return {"allowed_hosts": configured_target_hosts()}


@app.get("/api/specs")
def list_specs(_: dict[str, str] = Depends(require_auth)) -> list[dict[str, Any]]:
    with database.connect() as db:
        rows = db.execute("SELECT id, name, created_at, operations_json FROM specs ORDER BY id DESC").fetchall()
    return [{"id": row["id"], "name": row["name"], "created_at": row["created_at"], "operation_count": len(database.json_load(row["operations_json"]))} for row in rows]


@app.get("/api/specs/{spec_id}")
def get_spec(spec_id: int, _: dict[str, str] = Depends(require_auth)) -> dict[str, Any]:
    with database.connect() as db:
        row = db.execute("SELECT id, name, created_at, operations_json FROM specs WHERE id = ?", (spec_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Collection not found.")
    return {"id": row["id"], "name": row["name"], "created_at": row["created_at"], "operations": database.json_load(row["operations_json"])}


@app.post("/api/specs/import", status_code=201)
def import_spec(payload: ImportSpec, _: dict[str, str] = Depends(require_auth)) -> dict[str, Any]:
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Collection name cannot be blank.")
    try:
        _, operations = parse_spec(payload.content)
    except SpecError as exc:
        raise HTTPException(422, str(exc)) from exc
    with database.connect() as db:
        cursor = db.execute("INSERT INTO specs(name, operations_json) VALUES (?, ?)", (name, json.dumps(operations)))
        spec_id = cursor.lastrowid
    return {"id": spec_id, "name": name, "operations": operations}


@app.get("/api/runs")
def list_runs(limit: int = 50, _: dict[str, str] = Depends(require_auth)) -> list[dict[str, Any]]:
    if limit < 1 or limit > 100:
        raise HTTPException(422, "Limit must be between 1 and 100.")
    with database.connect() as db:
        rows = db.execute("SELECT * FROM test_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) | {"passed": bool(row["passed"]), "json_valid": None if row["json_valid"] is None else bool(row["json_valid"])} for row in rows]


def _safe_scalar_map(values: dict[str, Any], label: str) -> dict[str, str]:
    if len(values) > 50:
        raise HTTPException(422, f"At most 50 {label} are allowed.")
    result: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(key, str) or len(key) > 120 or isinstance(value, (dict, list)):
            raise HTTPException(422, f"{label} must contain short names and scalar values.")
        result[key] = str(value)[:2000]
    return result


def prepare_execution(payload: RunRequest, operation: dict[str, Any], base_url: str) -> tuple[str, str, dict[str, str], dict[str, str]]:
    route = operation["path"]
    missing = []
    for name in re.findall(r"\{([^{}]+)\}", route):
        if name not in payload.path_params:
            missing.append(name)
            continue
        raw_value = payload.path_params[name]
        if raw_value is None or isinstance(raw_value, (dict, list)):
            raise HTTPException(422, f"Path parameter '{name}' must be a scalar value.")
        value = str(raw_value)
        if len(value) > 500 or "/" in value:
            raise HTTPException(422, f"Path parameter '{name}' must be a single path segment under 500 characters.")
        route = route.replace("{" + name + "}", quote(value, safe=""))
    if missing:
        raise HTTPException(422, "Provide values for path parameters: " + ", ".join(missing))
    if ".." in route.split("/"):
        raise HTTPException(422, "Path traversal segments are not allowed.")
    query = _safe_scalar_map(payload.query_params, "query parameters")
    headers = _safe_scalar_map(payload.headers, "headers")
    forbidden_headers = {"host", "content-length", "transfer-encoding", "connection", "proxy-authorization", "proxy-connection", "te", "trailer", "upgrade"}
    if any(name.lower() in forbidden_headers for name in headers):
        raise HTTPException(422, "Host and hop-by-hop request headers are managed by TestPilot and cannot be overridden.")
    if len(headers) > 50:
        raise HTTPException(422, "At most 50 request headers are allowed.")
    if payload.body is not None and len(json.dumps(payload.body, ensure_ascii=False).encode("utf-8")) > 1_000_000:
        raise HTTPException(422, "Request JSON body exceeds the 1 MB limit.")
    url = base_url + (route if route.startswith("/") else "/" + route)
    if len(url) > 4096:
        raise HTTPException(422, "The final target URL is too long.")
    return route, url, query, headers


@app.post("/api/runs", status_code=201)
async def execute_run(payload: RunRequest, _: dict[str, str] = Depends(require_auth)) -> dict[str, Any]:
    with database.connect() as db:
        row = db.execute("SELECT operations_json FROM specs WHERE id = ?", (payload.spec_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Collection not found.")
    operations = database.json_load(row["operations_json"])
    operation = next((item for item in operations if item["id"] == payload.operation_id), None)
    if operation is None:
        raise HTTPException(404, "Operation not found in this collection.")
    try:
        base_url, resolved_ips = validate_target_url(payload.target_base_url)
    except TargetRejected as exc:
        raise HTTPException(403, str(exc)) from exc

    route, url, query, headers = prepare_execution(payload, operation, base_url)

    start = time.perf_counter()
    target_host = urlsplit(base_url).hostname or ""
    target_ip = resolved_ips[0]
    expected_status = payload.expected_status if payload.expected_status is not None else operation.get("expected_status")
    try:
        timeout = aiohttp.ClientTimeout(total=15.0, connect=5.0)
        connector = aiohttp.TCPConnector(resolver=PinnedResolver(target_host, target_ip), use_dns_cache=False, ssl=True)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=False, auto_decompress=True) as client:
            async with client.request(operation["method"], url, params=query, headers=headers, json=payload.body if payload.body is not None else None, allow_redirects=False) as response:
                status = response.status
                content_type = response.headers.get("content-type", "")[:120]
                body_bytes = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    remaining = 1_000_000 - len(body_bytes)
                    if remaining <= 0:
                        break
                    body_bytes.extend(chunk[:remaining])
                    if len(body_bytes) >= 1_000_000:
                        break
                truncated = len(body_bytes) >= 1_000_000
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        is_json_type = "json" in content_type.lower()
        try:
            if is_json_type:
                json.loads(bytes(body_bytes).decode("utf-8"))
                json_valid: bool | None = True
            else:
                json_valid = False if payload.expect_json else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            json_valid = False
        status_ok = status == expected_status if expected_status is not None else 200 <= status < 400
        json_ok = not payload.expect_json or json_valid is True
        passed = status_ok and json_ok
        checks = [f"HTTP {status}" + (f" (expected {expected_status})" if expected_status is not None else ""), "JSON response valid" if json_valid else ("Response was not JSON" if payload.expect_json else "JSON check skipped")]
        summary = "All configured checks passed." if passed else "; ".join(checks)
        if truncated:
            summary += " Response exceeded the 1 MB inspection limit."
    except (aiohttp.ServerTimeoutError, TimeoutError):
        status, elapsed_ms, json_valid = None, round((time.perf_counter() - start) * 1000), None
        passed, summary, content_type, truncated = False, "The target request timed out after 15 seconds.", "", False
    except (aiohttp.ClientError, OSError) as exc:
        status, elapsed_ms, json_valid = None, round((time.perf_counter() - start) * 1000), None
        passed, summary, content_type, truncated = False, f"Request failed: {type(exc).__name__}.", "", False

    # Only metadata and validation results are persisted. Auth headers, query values, request
    # bodies, response bodies, and API keys are deliberately omitted.
    with database.connect() as db:
        cursor = db.execute(
            "INSERT INTO test_runs(spec_id, operation_id, operation_label, method, safe_path, status_code, passed, elapsed_ms, expected_status, json_valid, summary) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (payload.spec_id, operation["id"], operation["summary"], operation["method"], operation["path"], status, int(passed), elapsed_ms, expected_status, None if json_valid is None else int(json_valid), summary),
        )
        run_id = cursor.lastrowid
    return {"id": run_id, "spec_id": payload.spec_id, "operation_id": operation["id"], "operation_label": operation["summary"], "method": operation["method"], "safe_path": operation["path"], "status_code": status, "passed": passed, "elapsed_ms": elapsed_ms, "expected_status": expected_status, "json_valid": json_valid, "content_type": content_type, "summary": summary, "created_at": None}


@app.post("/api/ai/specs/{spec_id}/suggestions")
async def ai_suggestions(spec_id: int, _: dict[str, str] = Depends(require_auth)) -> dict[str, Any]:
    with database.connect() as db:
        row = db.execute("SELECT operations_json FROM specs WHERE id = ?", (spec_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Collection not found.")
    return await suggestions_for(database.json_load(row["operations_json"]))


@app.post("/api/ai/runs/{run_id}/explanation")
async def ai_failure_explanation(run_id: int, _: dict[str, str] = Depends(require_auth)) -> dict[str, str]:
    with database.connect() as db:
        row = db.execute("SELECT * FROM test_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Test run not found.")
    run = dict(row)
    run["passed"] = bool(run["passed"])
    return await explain_failure(run)


# The production container serves the built React application from the same origin as
# the API. In local development Vite handles the same-origin /api proxy instead.
frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

