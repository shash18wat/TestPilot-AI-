from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .openapi_parser import example_from_schema


def _fallback_suggestions(operations: list[dict[str, Any]]) -> dict[str, Any]:
    suggestions = []
    for operation in operations[:5]:
        body = example_from_schema(operation.get("request_schema")) if operation.get("request_schema") else None
        suggestions.append({
            "title": f"Happy path: {operation['method']} {operation['path']}",
            "method": operation["method"],
            "path": operation["path"],
            "rationale": "Start with a valid request and confirm the documented success response.",
            "expected_status": operation.get("expected_status") or 200,
            "body": body,
        })
    if operations:
        first = operations[0]
        suggestions.append({
            "title": "Reject a malformed or incomplete request",
            "method": first["method"],
            "path": first["path"],
            "rationale": "Check that invalid input returns a clear 4xx response without an internal error.",
            "expected_status": 400,
            "body": None,
        })
    return {"source": "built-in", "suggestions": suggestions}


async def suggestions_for(operations: list[dict[str, Any]]) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        result = _fallback_suggestions(operations)
        result["note"] = "Gemini is not configured. These starter suggestions were generated from the OpenAPI schema."
        return result
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
    prompt = (
        "Create up to 5 concise API test suggestions from this OpenAPI operation data. "
        "Return JSON only with a top-level suggestions array. Each item must include title, method, path, rationale, expected_status, body. "
        "Do not invent credentials or claim a request was executed.\n\n" + json.dumps(operations[:40], ensure_ascii=True)[:18000]
    )
    try:
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": api_key},
                json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}},
            )
            response.raise_for_status()
            payload = response.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        generated = json.loads(text)
        values = generated.get("suggestions", []) if isinstance(generated, dict) else []
        sanitized = []
        for item in values[:5]:
            if not isinstance(item, dict):
                continue
            sanitized.append({
                "title": str(item.get("title", "API test suggestion"))[:120],
                "method": str(item.get("method", "GET")).upper()[:10],
                "path": str(item.get("path", "/"))[:500],
                "rationale": str(item.get("rationale", ""))[:400],
                "expected_status": int(item.get("expected_status", 200)) if str(item.get("expected_status", 200)).isdigit() else 200,
                "body": item.get("body"),
            })
        return {"source": "gemini", "suggestions": sanitized or _fallback_suggestions(operations)["suggestions"]}
    except Exception:
        result = _fallback_suggestions(operations)
        result["note"] = "Gemini could not be reached. Built-in suggestions are shown instead."
        return result


async def explain_failure(run: dict[str, Any]) -> dict[str, str]:
    if run["passed"]:
        return {"source": "built-in", "explanation": "This test passed its configured response checks."}
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    fallback = f"{run['method']} {run['safe_path']} did not meet the expected response checks. {run['summary']}"
    if not api_key:
        return {"source": "built-in", "explanation": fallback}
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
    prompt = "Explain this API test failure in plain language and suggest one next step. Do not assume access to response bodies or secrets. Test result: " + json.dumps({key: run.get(key) for key in ("method", "safe_path", "status_code", "expected_status", "json_valid", "summary")})
    try:
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": api_key},
                json={"contents": [{"parts": [{"text": prompt}]}]},
            )
            response.raise_for_status()
            payload = response.json()
        explanation = payload["candidates"][0]["content"]["parts"][0]["text"]
        return {"source": "gemini", "explanation": str(explanation)[:1200]}
    except Exception:
        return {"source": "built-in", "explanation": fallback}

