"""Local SQLite storage: settings, conversation history, structured activity log."""

from __future__ import annotations

import json
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

-- File changes NOVA made, so the last one can be undone (moves reversed, backups restored).
CREATE TABLE IF NOT EXISTS file_ops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    op TEXT NOT NULL,
    summary TEXT NOT NULL,
    data_json TEXT NOT NULL,
    undone INTEGER NOT NULL DEFAULT 0
);

-- People the Communication Agent may message (added by the user only; kept on this PC).
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    phone TEXT,
    email TEXT,
    created_at TEXT NOT NULL
);

-- Long-term memory: only what the user asked NOVA to remember (or approved). Slots (name, city, ...) hold one value.
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    slot TEXT,
    value TEXT,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    last_used TEXT
);

-- Workflow memory: named routines of exact, already-resolved "open" steps.
CREATE TABLE IF NOT EXISTS workflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    steps_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    runs INTEGER NOT NULL DEFAULT 0,
    last_run TEXT
);

-- Behavior patterns: what the user opened (apps, websites, projects) and which commands ran, with time.
-- Kept and deleted together with the conversation history.
CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    task_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_events(created_at);
CREATE INDEX IF NOT EXISTS idx_activity_task ON activity_log(task_id);
CREATE INDEX IF NOT EXISTS idx_conversations_created ON conversations(created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_task ON conversations(task_id);
CREATE INDEX IF NOT EXISTS idx_activity_date ON activity_log(date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_slot ON memories(slot) WHERE slot IS NOT NULL;
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


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

    # file operations journal (undo)
    def add_file_op(self, op: str, summary: str, data: dict[str, Any]) -> int:
        cur = self._execute(
            "INSERT INTO file_ops(created_at, op, summary, data_json) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), op, summary, json.dumps(data, ensure_ascii=False)),
        )
        return int(cur.lastrowid or 0)

    def last_file_op(self) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM file_ops WHERE undone = 0 ORDER BY id DESC LIMIT 1")
        if not rows:
            return None
        row = rows[0]
        row["data"] = json.loads(row.pop("data_json"))
        return row

    def mark_file_op_undone(self, op_id: int) -> None:
        self._execute("UPDATE file_ops SET undone = 1 WHERE id = ?", (op_id,))

    # contacts (Communication Agent)
    def save_contact(self, name: str, phone: str | None, email: str | None) -> dict[str, Any]:
        """Add a contact, or fill in the number/email of an existing one (same name, any case)."""
        self._execute(
            "INSERT INTO contacts(name, phone, email, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET phone = COALESCE(excluded.phone, contacts.phone), "
            "email = COALESCE(excluded.email, contacts.email)",
            (name, phone, email, datetime.now().isoformat(timespec="seconds")),
        )
        return self._query("SELECT * FROM contacts WHERE name = ? COLLATE NOCASE", (name,))[0]

    def list_contacts(self) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM contacts ORDER BY name COLLATE NOCASE")

    def delete_contact(self, contact_id: int) -> bool:
        return self._execute("DELETE FROM contacts WHERE id = ?", (contact_id,)).rowcount > 0

    # long-term memory
    def add_memory(self, text: str, source: str, slot: str | None = None, value: str | None = None) -> dict[str, Any]:
        """Save a memory; a slot memory (name, city...) replaces the previous one for that slot."""
        now = _now()
        with self._lock:
            if slot:
                cur = self._conn.execute(
                    "INSERT INTO memories(text, slot, value, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(slot) WHERE slot IS NOT NULL DO UPDATE SET text = excluded.text, value = excluded.value, "
                    "source = excluded.source, updated_at = excluded.updated_at RETURNING id",
                    (text, slot, value, source, now, now))
            else:
                cur = self._conn.execute(
                    "INSERT INTO memories(text, source, created_at, updated_at) VALUES (?, ?, ?, ?) RETURNING id",
                    (text, source, now, now))
            memory_id = cur.fetchone()[0]
            self._conn.commit()
        return self.get_memory(memory_id) or {}

    def get_memory(self, memory_id: int) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM memories WHERE id = ?", (memory_id,))
        return rows[0] if rows else None

    def memory_for_slot(self, slot: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM memories WHERE slot = ?", (slot,))
        return rows[0] if rows else None

    def list_memories(self) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM memories ORDER BY id DESC")

    def touch_memories(self, ids: list[int]) -> None:
        for memory_id in ids:
            self._execute("UPDATE memories SET uses = uses + 1, last_used = ? WHERE id = ?", (_now(), memory_id))

    def delete_memories(self, ids: list[int]) -> int:
        if not ids:
            return 0
        marks = ",".join("?" * len(ids))
        return self._execute(f"DELETE FROM memories WHERE id IN ({marks})", tuple(ids)).rowcount

    def delete_all_memories(self) -> int:
        return self._execute("DELETE FROM memories").rowcount

    # workflows
    def save_workflow(self, name: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
        now = _now()
        self._execute(
            "INSERT INTO workflows(name, steps_json, created_at, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET steps_json = excluded.steps_json, updated_at = excluded.updated_at",
            (name, json.dumps(steps, ensure_ascii=False), now, now),
        )
        return self.get_workflow(name) or {}

    @staticmethod
    def _workflow_row(row: dict[str, Any]) -> dict[str, Any]:
        row["steps"] = json.loads(row.pop("steps_json"))
        return row

    def get_workflow(self, name: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM workflows WHERE name = ? COLLATE NOCASE", (name,))
        return self._workflow_row(rows[0]) if rows else None

    def list_workflows(self) -> list[dict[str, Any]]:
        return [self._workflow_row(r) for r in self._query("SELECT * FROM workflows ORDER BY name COLLATE NOCASE")]

    def delete_workflow(self, workflow_id: int) -> bool:
        return self._execute("DELETE FROM workflows WHERE id = ?", (workflow_id,)).rowcount > 0

    def mark_workflow_run(self, workflow_id: int) -> None:
        self._execute("UPDATE workflows SET runs = runs + 1, last_run = ? WHERE id = ?", (_now(), workflow_id))

    # conversation history: conversations + the activity of each task, searchable; deleted together
    @staticmethod
    def _range(column: str, start: str | None, end: str | None) -> tuple[str, list[Any]]:
        sql, params = "", []
        if start:
            sql += f" AND {column} >= ?"
            params.append(start)
        if end:
            sql += f" AND {column} < ?"
            params.append(end)
        return sql, params

    def search_conversations(self, terms: list[str], start: str | None = None, end: str | None = None,
                             limit: int = 20, exclude_intents: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM conversations WHERE 1 = 1", []
        for term in terms:
            sql += (" AND (user_text LIKE ? ESCAPE '\\' OR response LIKE ? ESCAPE '\\' OR IFNULL(intent, '') LIKE ? "
                    "ESCAPE '\\')")
            params += [_like(term)] * 3
        for intent in exclude_intents:
            sql += " AND IFNULL(intent, '') <> ?"
            params.append(intent)
        when, extra = self._range("created_at", start, end)
        return self._query(sql + when + " ORDER BY id DESC LIMIT ?", tuple(params + extra + [limit]))

    def activity_for_tasks(self, task_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {t: [] for t in task_ids}
        if not task_ids:
            return out
        marks = ",".join("?" * len(task_ids))
        for row in self._query(f"SELECT * FROM activity_log WHERE task_id IN ({marks}) ORDER BY id", tuple(task_ids)):
            out[row["task_id"]].append(row)
        return out

    def history_span(self, start: str | None = None, end: str | None = None) -> tuple[str | None, str | None]:
        when, params = self._range("created_at", start, end)
        row = self._query("SELECT MIN(created_at) AS a, MAX(created_at) AS b FROM conversations WHERE 1 = 1" + when,
                          tuple(params))[0]
        return row["a"], row["b"]

    def count_history(self, start: str | None = None, end: str | None = None) -> int:
        when, params = self._range("created_at", start, end)
        return int(self._query("SELECT COUNT(*) AS n FROM conversations WHERE 1 = 1" + when, tuple(params))[0]["n"])

    def delete_history(self, start: str | None = None, end: str | None = None) -> int:
        """Conversations, their activity records and permission questions in the range. Returns conversations removed."""
        when, params = self._range("created_at", start, end)
        activity, activity_params = self._range("date || 'T' || time", start, end)
        with self._lock:
            removed = self._conn.execute("DELETE FROM conversations WHERE 1 = 1" + when, tuple(params)).rowcount
            self._conn.execute("DELETE FROM activity_log WHERE 1 = 1" + activity, tuple(activity_params))
            self._conn.execute("DELETE FROM permission_requests WHERE 1 = 1" + when, tuple(params))
            self._conn.execute("DELETE FROM usage_events WHERE 1 = 1" + when, tuple(params))
            self._conn.commit()
        return removed

    def delete_task_history(self, task_id: str) -> bool:
        with self._lock:
            removed = self._conn.execute("DELETE FROM conversations WHERE task_id = ?", (task_id,)).rowcount
            self._conn.execute("DELETE FROM activity_log WHERE task_id = ?", (task_id,))
            self._conn.execute("DELETE FROM permission_requests WHERE task_id = ?", (task_id,))
            self._conn.execute("DELETE FROM usage_events WHERE task_id = ?", (task_id,))
            self._conn.commit()
        return removed > 0

    # behavior patterns
    def add_usage(self, kind: str, target: str, task_id: str | None = None) -> None:
        self._execute("INSERT INTO usage_events(created_at, kind, target, task_id) VALUES (?, ?, ?, ?)",
                      (_now(), kind, target[:120], task_id))

    def list_usage(self, since: str | None = None) -> list[dict[str, Any]]:
        if since:
            return self._query("SELECT * FROM usage_events WHERE created_at >= ? ORDER BY id", (since,))
        return self._query("SELECT * FROM usage_events ORDER BY id")

    def delete_usage(self) -> int:
        return self._execute("DELETE FROM usage_events").rowcount

    def declined_routines(self) -> set[str]:
        try:
            return set(json.loads(self.get_setting("declined_routines") or "[]"))
        except ValueError:
            return set()

    def decline_routine(self, key: str) -> None:
        self.set_setting("declined_routines", json.dumps(sorted(self.declined_routines() | {key}), ensure_ascii=False))

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
