from pathlib import Path

from app import database
from app.ai_service import _fallback_suggestions
from app.main import ImportSpec, RunRequest, get_spec, import_spec, list_runs, list_specs, prepare_execution
from fastapi import HTTPException
import pytest


def test_import_persists_operations_and_builtin_suggestions(monkeypatch):
    database_file = Path(__file__).parents[1] / "data" / "test-api.sqlite3"
    if database_file.exists():
        database_file.unlink()
    monkeypatch.setenv("TESTPILOT_DB_PATH", str(database_file))
    try:
        database.initialize()
        imported = import_spec(ImportSpec(
            name="Example",
            content="openapi: 3.0.3\ninfo: {title: Example, version: '1'}\npaths:\n  /health:\n    get:\n      responses:\n        '200': {description: ok}\n",
        ))
        saved = get_spec(imported["id"])
        assert saved["operations"][0]["path"] == "/health"
        assert list_specs()[0]["name"] == "Example"
        assert list_runs() == []
        fallback = _fallback_suggestions(saved["operations"])
        assert fallback["suggestions"]
        assert fallback["source"] == "built-in"
    finally:
        if database_file.exists():
            database_file.unlink()


def test_prepare_execution_encodes_path_and_keeps_secrets_out_of_saved_shape():
    payload = RunRequest(
        spec_id=1, operation_id="op1", target_base_url="https://api.example.com/v1",
        path_params={"user_id": "a b"}, query_params={"token": "temporary"},
        headers={"Authorization": "Bearer temporary"},
    )
    operation = {"path": "/users/{user_id}"}
    route, url, query, headers = prepare_execution(payload, operation, payload.target_base_url)
    assert route == "/users/a%20b"
    assert url == "https://api.example.com/v1/users/a%20b"
    assert query["token"] == "temporary"
    assert headers["Authorization"] == "Bearer temporary"
    assert "temporary" not in route


def test_prepare_execution_rejects_control_headers_and_missing_path_values():
    operation = {"path": "/users/{user_id}"}
    missing = RunRequest(spec_id=1, operation_id="op1", target_base_url="https://api.example.com")
    with pytest.raises(HTTPException, match="Provide values for path parameters"):
        prepare_execution(missing, operation, missing.target_base_url)
    forbidden = RunRequest(spec_id=1, operation_id="op1", target_base_url="https://api.example.com", path_params={"user_id": 1}, headers={"Host": "internal.local"})
    with pytest.raises(HTTPException, match="cannot be overridden"):
        prepare_execution(forbidden, operation, forbidden.target_base_url)
