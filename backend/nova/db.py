"""Local SQLite storage: settings, conversation history, structured activity log."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .redaction import redact

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    user_text TEXT NOT NULL,
    detected_language TEXT,
    intent TEXT,
    response TEXT,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    task_id TEXT NOT NULL,
    task_name TEXT NOT NULL,
    agent TEXT NOT NULL,
    action TEXT NOT NULL,
    permission_status TEXT NOT NULL,
    execution_status TEXT NOT NULL,
    test_status TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    admin_status TEXT NOT NULL,
    error TEXT,
    final_result TEXT
);

CREATE TABLE IF NOT EXISTS system_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    profile_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS permission_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intent TEXT NOT NULL,
    scope TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    last_used TEXT,
    UNIQUE(intent, scope)
);

CREATE TABLE IF NOT EXISTS permission_requests (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    max_risk TEXT NOT NULL,
    decision TEXT,
    decided_by TEXT,
    decided_at TEXT,
    remembered INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_activity_task ON activity_log(task_id);
CREATE INDEX IF NOT EXISTS idx_conversations_created ON conversations(created_at);
"""


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    # settings
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        rows = self._query("SELECT value FROM settings WHERE key = ?", (key,))
        return rows[0]["value"] if rows else default

    def set_setting(self, key: str, value: str) -> None:
        self._execute(
            "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, datetime.now().isoformat(timespec="seconds")),
        )

    # conversations
    def add_conversation(
        self,
        *,
        task_id: str,
        source: str,
        user_text: str,
        detected_language: str | None,
        intent: str | None,
        response: str | None,
        status: str,
    ) -> None:
        self._execute(
            "INSERT INTO conversations(task_id, created_at, source, user_text, detected_language, intent, response, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                datetime.now().isoformat(timespec="seconds"),
                source,
                redact(user_text),
                detected_language,
                intent,
                redact(response),
                status,
            ),
        )

    def list_conversations(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM conversations ORDER BY id DESC LIMIT ?", (limit,))

    # activity log
    def add_activity(
        self,
        *,
        task_id: str,
        task_name: str,
        agent: str,
        action: str,
        permission_status: str = "not_required",
        execution_status: str,
        test_status: str = "not_run",
        verification_status: str = "not_applicable",
        admin_status: str = "pending",
        error: str | None = None,
        final_result: str | None = None,
    ) -> None:
        now = datetime.now()
        self._execute(
            "INSERT INTO activity_log(date, time, task_id, task_name, agent, action, permission_status, "
            "execution_status, test_status, verification_status, admin_status, error, final_result) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S"),
                task_id,
                redact(task_name),
                agent,
                redact(action),
                permission_status,
                execution_status,
                test_status,
                verification_status,
                admin_status,
                redact(error),
                redact(final_result),
            ),
        )

    def list_activity(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,))

    # permissions: remembered approvals and the audit trail of every request
    def add_permission_rule(self, intent: str, scope: str, description: str) -> None:
        self._execute(
            "INSERT OR IGNORE INTO permission_rules(intent, scope, description, created_at) VALUES (?, ?, ?, ?)",
            (intent, scope, redact(description), datetime.now().isoformat(timespec="seconds")),
        )

    def find_permission_rule(self, intent: str, scope: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM permission_rules WHERE intent = ? AND scope = ?", (intent, scope))
        return rows[0] if rows else None

    def touch_permission_rule(self, rule_id: int) -> None:
        self._execute("UPDATE permission_rules SET uses = uses + 1, last_used = ? WHERE id = ?",
                      (datetime.now().isoformat(timespec="seconds"), rule_id))

    def list_permission_rules(self) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM permission_rules ORDER BY id DESC")

    def delete_permission_rule(self, rule_id: int) -> bool:
        return self._execute("DELETE FROM permission_rules WHERE id = ?", (rule_id,)).rowcount > 0

    def add_permission_request(self, request_id: str, task_id: str, steps_json: str, max_risk: str) -> None:
        self._execute(
            "INSERT INTO permission_requests(id, task_id, created_at, steps_json, max_risk) VALUES (?, ?, ?, ?, ?)",
            (request_id, task_id, datetime.now().isoformat(timespec="seconds"), redact(steps_json), max_risk),
        )

    def decide_permission_request(self, request_id: str, decision: str, decided_by: str, remembered: bool) -> None:
        self._execute(
            "UPDATE permission_requests SET decision = ?, decided_by = ?, decided_at = ?, remembered = ? WHERE id = ?",
            (decision, decided_by, datetime.now().isoformat(timespec="seconds"), int(remembered), request_id),
        )

    def list_permission_requests(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM permission_requests ORDER BY created_at DESC LIMIT ?", (limit,))

    # system profile (latest few kept for comparison)
    def save_system_profile(self, profile_json: str, keep: int = 5) -> None:
        self._execute(
            "INSERT INTO system_profile(created_at, profile_json) VALUES (?, ?)",
            (datetime.now().isoformat(timespec="seconds"), profile_json),
        )
        self._execute(
            "DELETE FROM system_profile WHERE id NOT IN (SELECT id FROM system_profile ORDER BY id DESC LIMIT ?)",
            (keep,),
        )

    def latest_system_profile(self) -> str | None:
        rows = self._query("SELECT profile_json FROM system_profile ORDER BY id DESC LIMIT 1")
        return rows[0]["profile_json"] if rows else None
