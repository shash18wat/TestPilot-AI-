from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def database_path() -> Path:
    configured = os.getenv("TESTPILOT_DB_PATH", "backend/data/testpilot.sqlite3")
    return Path(configured)


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    return connection


def initialize() -> None:
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS specs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                operations_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            CREATE TABLE IF NOT EXISTS test_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spec_id INTEGER,
                operation_id TEXT NOT NULL,
                operation_label TEXT NOT NULL,
                method TEXT NOT NULL,
                safe_path TEXT NOT NULL,
                status_code INTEGER,
                passed INTEGER NOT NULL,
                elapsed_ms INTEGER,
                expected_status INTEGER,
                json_valid INTEGER,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                FOREIGN KEY(spec_id) REFERENCES specs(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY,
                code_verifier TEXT NOT NULL,
                nonce TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            );
        """)
        db.execute("DELETE FROM oauth_states WHERE expires_at < unixepoch()")


def json_load(value: str) -> Any:
    return json.loads(value)

