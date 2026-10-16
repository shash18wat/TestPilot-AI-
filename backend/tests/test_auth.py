import pytest
from starlette.requests import Request

from app import auth, database
from app.main import google_start, health, require_auth


def configure_auth(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/api/auth/google/callback")
    monkeypatch.setenv("TESTPILOT_FRONTEND_URL", "http://127.0.0.1:5173")
    monkeypatch.setenv("TESTPILOT_OWNER_EMAIL", "tiwarishashwat36@gmail.com")
    monkeypatch.setenv("TESTPILOT_SESSION_SECRET", "s" * 48)


def test_signed_session_only_accepts_configured_owner(monkeypatch):
    configure_auth(monkeypatch)
    token = auth.issue_session("TIWARISHASHWAT36@gmail.com")
    assert auth.read_session(token) == {"email": "tiwarishashwat36@gmail.com"}
    with pytest.raises(ValueError):
        auth.issue_session("someone@example.com")


def test_render_service_url_supplies_production_oauth_urls(monkeypatch):
    monkeypatch.delenv("GOOGLE_REDIRECT_URI", raising=False)
    monkeypatch.delenv("TESTPILOT_FRONTEND_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://testpilot-demo.onrender.com/")

    values = auth.settings()

    assert values["frontend_url"] == "https://testpilot-demo.onrender.com"
    assert values["redirect_uri"] == "https://testpilot-demo.onrender.com/api/auth/google/callback"


def test_explicit_oauth_urls_override_render_defaults(monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://testpilot-demo.onrender.com")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://auth.example.com/callback")
    monkeypatch.setenv("TESTPILOT_FRONTEND_URL", "https://app.example.com/")

    values = auth.settings()

    assert values["frontend_url"] == "https://app.example.com"
    assert values["redirect_uri"] == "https://auth.example.com/callback"


def test_tampered_and_unconfigured_sessions_are_rejected(monkeypatch):
    configure_auth(monkeypatch)
    token = auth.issue_session("tiwarishashwat36@gmail.com")
    assert auth.read_session(token + "x") is None
    monkeypatch.setenv("TESTPILOT_SESSION_SECRET", "short")
    assert not auth.configured()
    assert auth.read_session(token) is None


def test_workspace_data_requires_auth_and_health_does_not_disclose_hosts(monkeypatch, tmp_path):
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "TESTPILOT_SESSION_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TESTPILOT_DB_PATH", str(tmp_path / "workspace.sqlite3"))
    monkeypatch.setenv("TESTPILOT_ALLOWED_HOSTS", "private.example.com")
    result = health()
    assert result["auth_configured"] is False
    assert "allowed_hosts" not in result
    request = Request({"type": "http", "headers": [], "method": "GET", "path": "/api/specs", "query_string": b"", "scheme": "http", "server": ("testserver", 80), "client": ("127.0.0.1", 1)})
    with pytest.raises(Exception) as raised:
        require_auth(request)
    assert getattr(raised.value, "status_code", None) == 503


def test_google_start_uses_state_pkce_and_http_only_state_cookie(monkeypatch, tmp_path):
    configure_auth(monkeypatch)
    monkeypatch.setenv("TESTPILOT_DB_PATH", str(tmp_path / "oauth.sqlite3"))
    database.initialize()
    response = google_start()
    assert response.status_code == 302
    assert "accounts.google.com/o/oauth2/v2/auth" in response.headers["location"]
    assert "code_challenge_method=S256" in response.headers["location"]
    cookie = response.headers["set-cookie"].lower()
    assert "testpilot_oauth_state=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
