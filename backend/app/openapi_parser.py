"""Small, safe OpenAPI 3 parser for importing API operations."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import yaml

MAX_SPEC_BYTES = 1_000_000
METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


class SpecError(ValueError):
    pass


def parse_spec(content: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(content, str) or not content.strip():
        raise SpecError("Paste an OpenAPI YAML or JSON document.")
    if len(content.encode("utf-8")) > MAX_SPEC_BYTES:
        raise SpecError("The OpenAPI document is too large (maximum 1 MB).")
    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise SpecError("Could not parse the OpenAPI YAML or JSON document.") from exc
    if not isinstance(document, dict):
        raise SpecError("The document must be an OpenAPI object.")
    version = str(document.get("openapi", ""))
    if not version.startswith("3."):
        raise SpecError("Only OpenAPI 3.x documents are supported in this MVP.")
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise SpecError("The document must contain a paths object.")

    operations: list[dict[str, Any]] = []
    for path, path_item in paths.items():
        if not isinstance(path, str) or not path.startswith("/") or not isinstance(path_item, dict):
            continue
        path_parameters = path_item.get("parameters", [])
        for method, operation in path_item.items():
            method = str(method).lower()
            if method not in METHODS or not isinstance(operation, dict):
                continue
            op_id = str(operation.get("operationId") or f"{method}_{path}")
            digest = hashlib.sha1(f"{method}:{path}:{op_id}".encode()).hexdigest()[:10]
            parameters = []
            operation_parameters = operation.get("parameters", [])
            merged_parameters: dict[tuple[str, str], Any] = {}
            for parameter in (path_parameters if isinstance(path_parameters, list) else []) + (operation_parameters if isinstance(operation_parameters, list) else []):
                if isinstance(parameter, dict) and parameter.get("name") and parameter.get("in"):
                    merged_parameters[(str(parameter["name"]), str(parameter["in"]))] = parameter
            for parameter in merged_parameters.values():
                if not isinstance(parameter, dict):
                    continue
                schema = parameter.get("schema", {}) if isinstance(parameter.get("schema", {}), dict) else {}
                parameters.append({
                    "name": str(parameter.get("name", ""))[:100],
                    "in": str(parameter.get("in", "query")),
                    "required": bool(parameter.get("required", False)),
                    "type": str(schema.get("type", "string")),
                    "description": str(parameter.get("description", ""))[:300],
                })
            request_schema = None
            request_body = operation.get("requestBody")
            if isinstance(request_body, dict):
                content_map = request_body.get("content", {})
                if isinstance(content_map, dict):
                    json_content = content_map.get("application/json", {})
                    if isinstance(json_content, dict):
                        request_schema = json_content.get("schema")
            responses = operation.get("responses", {})
            success_status = next((int(str(code)) for code in responses if str(code).startswith("2") and str(code).isdigit()), None) if isinstance(responses, dict) else None
            operations.append({
                "id": digest,
                "operation_id": op_id[:160],
                "method": method.upper(),
                "path": path[:500],
                "summary": str(operation.get("summary") or operation.get("description") or op_id)[:300],
                "parameters": parameters,
                "request_schema": request_schema,
                "expected_status": success_status,
            })
    if not operations:
        raise SpecError("No supported HTTP operations were found in the paths object.")
    return document, operations


def example_from_schema(schema: Any) -> Any:
    """Create a tiny valid-ish example body from a JSON schema fragment."""
    if not isinstance(schema, dict):
        return {}
    if "example" in schema:
        return schema["example"]
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        required = schema.get("required", [])
        props = schema.get("properties", {})
        if not isinstance(props, dict):
            return {}
        keys = required or list(props)[:4]
        return {key: example_from_schema(props.get(key, {})) for key in keys[:8]}
    if kind == "array":
        return [example_from_schema(schema.get("items", {}))]
    if kind == "string":
        return schema.get("enum", ["example"])[0] if schema.get("enum") else "example"
    if kind == "integer":
        return schema.get("minimum", 1)
    if kind == "number":
        return schema.get("minimum", 1)
    if kind == "boolean":
        return True
    return None

