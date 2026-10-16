import json

import pytest

from app.openapi_parser import SpecError, example_from_schema, parse_spec


def test_parse_openapi_json_and_extract_operations():
    source = json.dumps({
        "openapi": "3.0.3",
        "info": {"title": "Example", "version": "1"},
        "paths": {"/users/{user_id}": {
            "parameters": [{"name": "x-trace-id", "in": "header", "schema": {"type": "string"}}],
            "get": {
                "operationId": "getUser",
                "summary": "Get a user",
                "parameters": [{"name": "user_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                "responses": {"200": {"description": "ok"}},
            },
        }},
    })
    document, operations = parse_spec(source)
    assert document["openapi"] == "3.0.3"
    assert operations[0]["method"] == "GET"
    assert operations[0]["path"] == "/users/{user_id}"
    assert operations[0]["expected_status"] == 200
    assert {parameter["name"] for parameter in operations[0]["parameters"]} == {"user_id", "x-trace-id"}


def test_parse_yaml_request_schema():
    _, operations = parse_spec('''openapi: 3.1.0
info: {title: Example, version: '1'}
paths:
  /items:
    post:
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [name]
              properties:
                name: {type: string}
      responses:
        '201': {description: created}
''')
    assert operations[0]["request_schema"]["required"] == ["name"]
    assert example_from_schema(operations[0]["request_schema"]) == {"name": "example"}
    assert operations[0]["expected_status"] == 201


@pytest.mark.parametrize("source", ["", "[]", "openapi: 2.0\npaths: {}", "openapi: 3.0.3\ninfo: {}"])
def test_reject_invalid_or_unsupported_specs(source):
    with pytest.raises(SpecError):
        parse_spec(source)


def test_reject_oversized_spec():
    with pytest.raises(SpecError, match="too large"):
        parse_spec("x" * 1_000_001)
