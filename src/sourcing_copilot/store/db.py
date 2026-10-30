"""Open the SQLite file and create the tables if they are missing."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS screenings (
    run_id            TEXT PRIMARY KEY,
    role_id           TEXT NOT NULL,
    candidate_id      TEXT NOT NULL,
    status            TEXT NOT NULL,
    started_by        TEXT NOT NULL,
    scorecard_json    TEXT,
    draft_message     TEXT,
    final_message     TEXT,
    decision_json     TEXT,
    send_receipt_json TEXT,
    rule_results_json TEXT NOT NULL DEFAULT '[]',
    data_warnings_json TEXT NOT NULL DEFAULT '[]',
    error             TEXT,
    tokens_in         INTEGER NOT NULL DEFAULT 0,
    tokens_out        INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS screenings_by_role ON screenings (role_id, candidate_id, created_at);

CREATE TABLE IF NOT EXISTS steps (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    name         TEXT NOT NULL,
    status       TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    ms           INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}',
    tokens_in    INTEGER NOT NULL DEFAULT 0,
    tokens_out   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS steps_by_run ON steps (run_id, seq);

CREATE TABLE IF NOT EXISTS audit_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id  TEXT NOT NULL,
    at      TEXT NOT NULL,
    actor   TEXT NOT NULL,
    action  TEXT NOT NULL,
    detail  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS audit_by_run ON audit_log (run_id, id);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    """One connection shared by the app. check_same_thread=False because FastAPI runs
    sync handlers in a thread pool; the store serialises writes with a lock."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn
