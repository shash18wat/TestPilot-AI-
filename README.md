# TestPilot AI

TestPilot AI is a local-first API testing workspace with a React interface and FastAPI service. Import an OpenAPI 3.x YAML or JSON document, explore its operations, run HTTP checks, review history, and request schema-based suggestions. Gemini can add test ideas and failure explanations when configured; built-in fallback suggestions remain available without an API key.

## Features

- React + TypeScript frontend with an operation browser, request builder, dashboard, and run history.
- FastAPI backend with SQLite persistence and interactive API docs at `/docs`.
- OpenAPI 3.x parsing, including path/query parameters and JSON request schemas.
- API execution with expected-status and JSON-syntax checks, 15-second timeout, TLS verification, and redirects disabled.
- Test-run history stores outcomes and validation metadata. It does not save request headers, query values, request bodies, or response bodies.
- Optional Gemini suggestions and failure explanations; the key stays on the backend.
- Google sign-in restricted to the configured owner email, with PKCE, signed HTTP-only sessions, and protected workspace APIs.
- Outbound requests start disabled and require an exact hostname allowlist.
- Includes a small demo OpenAPI contract at `examples/demo-openapi.yaml`.

## Requirements

- Python 3.10+
- Node.js 18+

## Local setup

From this folder:

1. Copy `.env.example` to `.env`.
2. Create and activate a Python virtual environment, then install `requirements.txt` (use `requirements-dev.txt` to run the test suite).
3. In one terminal, start the API: `uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000`.
4. In another terminal, run `npm install` and `npm run dev` from `frontend/`.
5. Configure Google sign-in as described below, then open the local URL printed by Vite (normally `http://127.0.0.1:5173`).

The SQLite database is created at `backend/data/testpilot.sqlite3` by default. Change `TESTPILOT_DB_PATH` in `.env` to use another local path.

## Allow a test target

The default allowlist is empty. Before running an API operation, set an exact hostname in `.env`:

```dotenv
TESTPILOT_ALLOWED_HOSTS=api.example.com
```

Use comma-separated exact hostnames when more than one is needed. Wildcards, URL schemes, paths, user information, private/local IPs, nonstandard ports, and redirects are not accepted. HTTPS is required by default. For a trusted HTTP-only test service, set `TESTPILOT_ALLOW_HTTP=true`; local and private IPs are still blocked. Restart the backend after changing `.env`. Enter the target base URL in the request builder; the hostname must exactly match the allowlist.

Security checks resolve every target and block any private, local, reserved, or otherwise non-global address. Each HTTP request is pinned to the public IP checked for that invocation, preventing a later DNS answer from redirecting the connection. The HTTP client disables environment proxy settings and follows no redirects. Test this MVP only against systems you are authorized to assess.

## Google sign-in

The workspace accepts only `TESTPILOT_OWNER_EMAIL` (pre-filled as `tiwarishashwat36@gmail.com` in `.env.example`). Google OAuth credentials are not included; create them in your own Google Cloud project:

1. Configure the OAuth consent screen and create an OAuth client ID with application type **Web application**.
2. Add this authorized redirect URI exactly: `http://127.0.0.1:8000/api/auth/google/callback`.
3. Copy the client ID and secret into `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in the project `.env`.
4. Generate a unique session secret with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and set `TESTPILOT_SESSION_SECRET` to its output. It must be at least 32 characters.
5. Keep `TESTPILOT_COOKIE_SECURE=false` for local HTTP development only. Then start the backend and frontend and choose **Continue with Google**. Sign in using the configured owner email.

The OAuth flow uses state, PKCE, nonce, and Google's verified ID-token validation. Workspace routes require a signed, eight-hour, HttpOnly, SameSite=Lax cookie. Provider errors and tokens are never shown to the browser UI. For a public HTTPS deployment, use an HTTPS OAuth callback and frontend URL, set `TESTPILOT_COOKIE_SECURE=true`, configure the production frontend origin in `TESTPILOT_CORS_ORIGINS`, use a fresh session secret, and review host/network protections for your deployment. Never commit `.env` or publish OAuth secrets.

If OAuth values are missing, the app displays a setup screen and keeps workspace data behind authentication. No Google account is contacted until you press the sign-in button.

## Gemini (optional)

Set `GEMINI_API_KEY` in the backend `.env` to enable Gemini. Keep it server-side; do not add it to frontend variables. `GEMINI_MODEL` defaults to `gemini-3.8-flash` and can be changed for your account or project. Without a key or if the API is unavailable, the backend returns built-in suggestions and concise failure explanations.

The integration uses Google's `generateContent` REST API and the `x-goog-api-key` header. See [Gemini API generateContent documentation](https://ai.google.dev/gemini-api/docs/generate-content) and [model documentation](https://ai.google.dev/gemini-api/docs/models).

## Verify

From this folder:

```text
python -m pytest backend/tests
```

For the frontend production build:

```text
cd frontend
npm run build
```

The frontend uses Google Fonts from Google Fonts when network access is available; system sans-serif fallbacks are used otherwise.

## MVP limits

- Supports OpenAPI 3.x operations and JSON request bodies. It does not resolve `$ref` graphs or generate comprehensive schema-conformance/property tests.
- Assertions cover one expected HTTP status and optional valid JSON syntax; custom JSONPath/schema assertions are future work.
- Run history intentionally omits bodies and credentials, so it is suitable for outcome tracking rather than replay.
- Single-owner Google sign-in is included; teams, role management, scheduling, production deployment configuration, and a background test runner are not included.
