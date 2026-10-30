"""Save and read screenings, their step-by-step trace, and the audit log."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class ScreeningStore:
    """One connection, one lock. Every query, reads included, runs under the lock: the
    API serves concurrent requests from a thread pool, and a sqlite3 connection shared by
    two threads at once returns garbage (a row that is not there, a cursor reset halfway)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.lock = threading.Lock()

    # -- writes -----------------------------------------------------------------

    def create(self, run_id: str, role_id: str, candidate_id: str, started_by: str) -> None:
        now = _now()
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO screenings (run_id, role_id, candidate_id, status, started_by, "
                "created_at, updated_at) VALUES (?, ?, ?, 'screening', ?, ?, ?)",
                (run_id, role_id, candidate_id, started_by, now, now),
            )

    def save_state(self, run_id: str, state: dict[str, Any]) -> None:
        """Copy what matters from the copilot's state into the tables. Steps are replaced
        wholesale; the state's step list is the source of truth."""
        steps = state.get("steps", [])
        with self.lock, self.conn:
            self.conn.execute(
                """UPDATE screenings SET status = ?, scorecard_json = ?, draft_message = ?,
                   final_message = ?, decision_json = ?, send_receipt_json = ?,
                   rule_results_json = ?, data_warnings_json = ?, error = ?,
                   tokens_in = ?, tokens_out = ?, updated_at = ?
                   WHERE run_id = ?""",
                (
                    state["status"],
                    _dump(state.get("scorecard")),
                    state.get("draft_message"),
                    state.get("final_message"),
                    _dump(state.get("decision")),
                    _dump(state.get("send_receipt")),
                    json.dumps(state.get("rule_results", [])),
                    json.dumps(state.get("data_warnings", [])),
                    state.get("error"),
                    sum(s.get("tokens_in", 0) for s in steps),
                    sum(s.get("tokens_out", 0) for s in steps),
                    _now(),
                    run_id,
                ),
            )
            self.conn.execute("DELETE FROM steps WHERE run_id = ?", (run_id,))
            self.conn.executemany(
                "INSERT INTO steps (run_id, seq, name, status, started_at, ms, details_json, "
                "tokens_in, tokens_out) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        seq,
                        s["name"],
                        s["status"],
                        s["started_at"],
                        s.get("ms", 0),
                        json.dumps(s.get("details", {}), default=str),
                        s.get("tokens_in", 0),
                        s.get("tokens_out", 0),
                    )
                    for seq, s in enumerate(steps, start=1)
                ],
            )

    def add_audit(self, run_id: str, actor: str, action: str, detail: str = "") -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO audit_log (run_id, at, actor, action, detail) VALUES (?, ?, ?, ?, ?)",
                (run_id, _now(), actor, action, detail),
            )

    # -- reads ------------------------------------------------------------------

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM screenings WHERE run_id = ?", (run_id,)
            ).fetchone()
        return _screening_from_row(row) if row else None

    def steps(self, run_id: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM steps WHERE run_id = ? ORDER BY seq", (run_id,)
            ).fetchall()
        return [
            {
                "seq": r["seq"],
                "name": r["name"],
                "status": r["status"],
                "started_at": r["started_at"],
                "ms": r["ms"],
                "details": json.loads(r["details_json"]),
                "tokens_in": r["tokens_in"],
                "tokens_out": r["tokens_out"],
            }
            for r in rows
        ]

    def audit(self, run_id: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT at, actor, action, detail FROM audit_log WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def latest_for_role(self, role_id: str) -> dict[str, dict[str, Any]]:
        """The newest screening per candidate for a role: {candidate_id: {...}}."""
        with self.lock:
            rows = self.conn.execute(
                """SELECT s.run_id, s.candidate_id, s.status, s.updated_at
                   FROM screenings s
                   JOIN (SELECT candidate_id, MAX(created_at) AS created_at
                         FROM screenings WHERE role_id = ? GROUP BY candidate_id) newest
                     ON newest.candidate_id = s.candidate_id AND newest.created_at = s.created_at
                   WHERE s.role_id = ?""",
                (role_id, role_id),
            ).fetchall()
        return {
            r["candidate_id"]: {
                "run_id": r["run_id"],
                "status": r["status"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        }

    def count(self) -> int:
        with self.lock:
            return self.conn.execute("SELECT COUNT(*) FROM screenings").fetchone()[0]


def _dump(value: Any) -> str | None:
    return None if value is None else json.dumps(value, default=str)


def _load(value: str | None) -> Any:
    return None if value is None else json.loads(value)


def _screening_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "role_id": row["role_id"],
        "candidate_id": row["candidate_id"],
        "status": row["status"],
        "started_by": row["started_by"],
        "scorecard": _load(row["scorecard_json"]),
        "draft_message": row["draft_message"],
        "final_message": row["final_message"],
        "decision": _load(row["decision_json"]),
        "send_receipt": _load(row["send_receipt_json"]),
        "rule_results": json.loads(row["rule_results_json"]),
        "data_warnings": json.loads(row["data_warnings_json"]),
        "error": row["error"],
        "tokens_in": row["tokens_in"],
        "tokens_out": row["tokens_out"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
