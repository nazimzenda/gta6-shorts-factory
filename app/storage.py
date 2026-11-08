from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

from app.config import settings

JSON_COLUMNS: dict[str, tuple[str, ...]] = {    "businesses": ("brand_rules",),
    "workers": ("capabilities", "permissions"),
    "initiatives": ("plan",),
    "approvals": (),
    "tasks": ("evidence",),
    "task_events": ("payload",),
    "audit_events": ("payload",),
    "source_assets": ("metadata",),
    "rights_records": ("platforms",),
    "media_assets": ("metadata",),
    "transcripts": ("segments",),
    "video_variants": ("qc_report",),
    "provider_quotes": ("request",),
    "mcp_servers": ("scopes",),
    "mcp_tools": ("input_schema",),
    "cua_sessions": ("allowlist",),
    "cua_actions": ("result",),
    "publishing_jobs": ("payload",),
    "analytics_snapshots": ("metadata",),
}

BOOLEAN_COLUMNS: dict[str, tuple[str, ...]] = {
    "rights_records": ("commercial_use",),
    "provider_jobs": ("mock",),
    "mcp_tools": ("enabled",),
}

TABLE_ORDER = (
    "platform_posts",
    "analytics_snapshots",
    "publishing_jobs",
    "publishing_accounts",
    "mcp_tool_calls",
    "mcp_tools",
    "mcp_servers",
    "cua_actions",
    "cua_sessions",
    "provider_jobs",
    "provider_quotes",
    "provider_accounts",
    "cost_events",
    "render_jobs",
    "video_variants",
    "highlight_candidates",
    "transcripts",
    "media_assets",
    "rights_records",
    "source_assets",
    "task_events",
    "task_dependencies",
    "tasks",
    "initiatives",
    "approvals",
    "audit_events",
)


class Store:
    """SQLite persistence for the local Founder Control Tower.

    JSON text columns are decoded on read so the API and dashboard receive
    structured values. Writes always go through parameterized SQL.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else settings.database_path
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(
            str(self.path), check_same_thread=False, timeout=30
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self.initialize()

    # ------------------------------------------------------------------ schema
    def initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS businesses (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    brand_rules TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS departments (
                    id TEXT PRIMARY KEY,
                    business_id TEXT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    manager_worker_id TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS workers (
                    id TEXT PRIMARY KEY,
                    department_id TEXT,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    avatar TEXT NOT NULL DEFAULT '🤖',
                    capabilities TEXT NOT NULL DEFAULT '[]',
                    permissions TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'active',
                    current_task_id TEXT,
                    last_action TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS initiatives (
                    id TEXT PRIMARY KEY,
                    business_id TEXT,
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'plan_pending',
                    risk_level TEXT NOT NULL DEFAULT 'low',
                    plan TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    initiative_id TEXT,
                    title TEXT NOT NULL,
                    department TEXT NOT NULL,
                    worker TEXT,
                    worker_id TEXT,
                    type TEXT NOT NULL DEFAULT 'general',
                    status TEXT NOT NULL DEFAULT 'pending',
                    priority INTEGER NOT NULL DEFAULT 3,
                    input_ref TEXT,
                    output_ref TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    error TEXT,
                    evidence TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    started_at TEXT,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS task_dependencies (
                    task_id TEXT NOT NULL,
                    depends_on_task_id TEXT NOT NULL,
                    PRIMARY KEY (task_id, depends_on_task_id)
                );

                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    actor TEXT NOT NULL DEFAULT 'ceo',
                    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    subject_type TEXT,
                    subject_id TEXT NOT NULL,
                    requested_by TEXT NOT NULL DEFAULT 'ceo',
                    status TEXT NOT NULL DEFAULT 'pending',
                    reason TEXT,
                    decided_by TEXT,
                    decided_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS source_assets (
                    id TEXT PRIMARY KEY,
                    uri TEXT NOT NULL,
                    path TEXT,
                    filename TEXT,
                    sha256 TEXT UNIQUE,
                    owner TEXT,
                    source_url TEXT,
                    retrieved_at TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    duration REAL,
                    width INTEGER,
                    height INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending_rights',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS rights_records (
                    id TEXT PRIMARY KEY,
                    source_asset_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    license_type TEXT NOT NULL,
                    commercial_use INTEGER NOT NULL DEFAULT 0,
                    proof_uri TEXT,
                    platforms TEXT NOT NULL DEFAULT '[]',
                    attribution TEXT,
                    takedown_contact TEXT,
                    expires_at TEXT,
                    review_notes TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS media_assets (
                    id TEXT PRIMARY KEY,
                    source_asset_id TEXT,
                    kind TEXT NOT NULL DEFAULT 'source',
                    uri TEXT NOT NULL,
                    duration REAL,
                    width INTEGER,
                    height INTEGER,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS transcripts (
                    id TEXT PRIMARY KEY,
                    media_asset_id TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT 'en',
                    segments TEXT NOT NULL DEFAULT '[]',
                    model TEXT,
                    confidence REAL,
                    status TEXT NOT NULL DEFAULT 'ready',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(media_asset_id)
                );

                CREATE TABLE IF NOT EXISTS highlight_candidates (
                    id TEXT PRIMARY KEY,
                    media_asset_id TEXT NOT NULL,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    score REAL NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT '',
                    hook TEXT,
                    status TEXT NOT NULL DEFAULT 'proposed',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS video_variants (
                    id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    style TEXT NOT NULL,
                    title TEXT NOT NULL,
                    script TEXT NOT NULL DEFAULT '',
                    caption_text TEXT,
                    render_uri TEXT,
                    caption_uri TEXT,
                    qc_status TEXT NOT NULL DEFAULT 'pending',
                    qc_report TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS render_jobs (
                    id TEXT PRIMARY KEY,
                    variant_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    command TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS provider_accounts (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    owner TEXT NOT NULL DEFAULT 'founder',
                    credential_ref TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS provider_quotes (
                    id TEXT PRIMARY KEY,
                    provider_account_id TEXT,
                    provider TEXT NOT NULL DEFAULT 'everygen',
                    request_hash TEXT NOT NULL,
                    request TEXT NOT NULL DEFAULT '{}',
                    credits REAL NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    expires_at TEXT,
                    approval_id TEXT,
                    status TEXT NOT NULL DEFAULT 'quoted',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS provider_jobs (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL DEFAULT 'everygen',
                    provider_quote_id TEXT,
                    external_job_id TEXT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    approval_id TEXT,
                    request_hash TEXT NOT NULL,
                    result_uri TEXT,
                    error TEXT,
                    mock INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS mcp_servers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    endpoint TEXT NOT NULL,
                    transport TEXT NOT NULL DEFAULT 'stdio',
                    scopes TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'registered',
                    last_seen TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS mcp_tools (
                    id TEXT PRIMARY KEY,
                    server_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    input_schema TEXT NOT NULL DEFAULT '{}',
                    risk TEXT NOT NULL DEFAULT 'low',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(server_id, name)
                );

                CREATE TABLE IF NOT EXISTS mcp_tool_calls (
                    id TEXT PRIMARY KEY,
                    server_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    approval_id TEXT,
                    status TEXT NOT NULL DEFAULT 'recorded',
                    output_ref TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS cua_sessions (
                    id TEXT PRIMARY KEY,
                    worker_id TEXT,
                    target TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'observe',
                    allowlist TEXT NOT NULL DEFAULT '[]',
                    capability_token_hash TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    approval_id TEXT,
                    max_actions INTEGER NOT NULL DEFAULT 25,
                    actions_used INTEGER NOT NULL DEFAULT 0,
                    expires_at TEXT,
                    evidence_dir TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    closed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS cua_actions (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    target TEXT,
                    evidence_uri TEXT,
                    result TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'recorded',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS publishing_accounts (
                    id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    credential_ref TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS publishing_jobs (
                    id TEXT PRIMARY KEY,
                    video_variant_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    account_id TEXT,
                    schedule_at TEXT,
                    approval_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pending_approval',
                    payload TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    idempotency_key TEXT UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS platform_posts (
                    id TEXT PRIMARY KEY,
                    publishing_job_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    external_post_id TEXT,
                    url TEXT,
                    status TEXT NOT NULL DEFAULT 'published',
                    published_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS analytics_snapshots (
                    id TEXT PRIMARY KEY,
                    platform_post_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    views INTEGER NOT NULL DEFAULT 0,
                    likes INTEGER NOT NULL DEFAULT 0,
                    comments INTEGER NOT NULL DEFAULT 0,
                    shares INTEGER NOT NULL DEFAULT 0,
                    follows INTEGER NOT NULL DEFAULT 0,
                    retention REAL,
                    watch_time REAL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS cost_events (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    category TEXT NOT NULL,
                    amount REAL NOT NULL DEFAULT 0,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    task_id TEXT,
                    job_id TEXT,
                    note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    approval_id TEXT,
                    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS system_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
                CREATE INDEX IF NOT EXISTS idx_audit_occurred ON audit_events(occurred_at);
                CREATE INDEX IF NOT EXISTS idx_variants_candidate ON video_variants(candidate_id);
                CREATE INDEX IF NOT EXISTS idx_posts_job ON platform_posts(publishing_job_id);
                """
            )
            self._migrate_legacy_tables()
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_initiative ON tasks(initiative_id)"
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('version', '2')"
            )

    def _columns(self, table: str) -> set[str]:
        return {row[1] for row in self._connection.execute(f"PRAGMA table_info({table})")}

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        if column not in self._columns(table):
            self._connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    def _migrate_legacy_tables(self) -> None:
        """Extend databases created by the foundation slice."""
        self._ensure_column("departments", "manager_worker_id", "TEXT")
        self._ensure_column("approvals", "subject_type", "TEXT")
        self._ensure_column("approvals", "requested_by", "TEXT NOT NULL DEFAULT 'ceo'")
        self._ensure_column("approvals", "reason", "TEXT")
        self._ensure_column("approvals", "decided_by", "TEXT")
        self._ensure_column("audit_events", "approval_id", "TEXT")
        self._ensure_column("rights_records", "platforms", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column("rights_records", "attribution", "TEXT")
        self._ensure_column("rights_records", "takedown_contact", "TEXT")
        self._ensure_column("rights_records", "review_notes", "TEXT")
        self._ensure_column("rights_records", "created_at", "TEXT")
        self._ensure_column("rights_records", "updated_at", "TEXT")
        self._ensure_column("tasks", "initiative_id", "TEXT")
        self._ensure_column("tasks", "worker_id", "TEXT")
        self._ensure_column("tasks", "type", "TEXT NOT NULL DEFAULT 'general'")
        self._ensure_column("tasks", "priority", "INTEGER NOT NULL DEFAULT 3")
        self._ensure_column("tasks", "input_ref", "TEXT")
        self._ensure_column("tasks", "output_ref", "TEXT")
        self._ensure_column("tasks", "attempts", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("tasks", "max_attempts", "INTEGER NOT NULL DEFAULT 3")
        self._ensure_column("tasks", "error", "TEXT")
        self._ensure_column("tasks", "evidence", "TEXT NOT NULL DEFAULT '{}'")
        self._ensure_column("tasks", "updated_at", "TEXT")
        self._ensure_column("tasks", "started_at", "TEXT")
        self._ensure_column("tasks", "completed_at", "TEXT")
        self._ensure_column("provider_jobs", "provider_quote_id", "TEXT")
        self._ensure_column("provider_jobs", "external_job_id", "TEXT")
        self._ensure_column("provider_jobs", "mock", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("provider_jobs", "updated_at", "TEXT")
        self._ensure_column("cua_sessions", "worker_id", "TEXT")
        self._ensure_column("cua_sessions", "allowlist", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column("cua_sessions", "capability_token_hash", "TEXT")
        self._ensure_column("cua_sessions", "max_actions", "INTEGER NOT NULL DEFAULT 25")
        self._ensure_column("cua_sessions", "actions_used", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("cua_sessions", "expires_at", "TEXT")
        self._ensure_column("cua_sessions", "evidence_dir", "TEXT")
        self._ensure_column("cua_sessions", "created_at", "TEXT")
        self._ensure_column("cua_sessions", "closed_at", "TEXT")
        self._ensure_column("mcp_tools", "created_at", "TEXT")
        self._connection.execute(
            "UPDATE rights_records SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP), "
            "updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)"
        )
        self._connection.execute(
            "UPDATE tasks SET updated_at = COALESCE(updated_at, created_at)"
        )
        self._connection.execute(
            "UPDATE cua_sessions SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP)"
        )
        self._connection.execute(
            "UPDATE provider_jobs SET updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)"
        )
        self._connection.execute(
            "UPDATE mcp_tools SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP)"
        )

    # ------------------------------------------------------------------ helpers
    def execute(self, query: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock, self._connection:
            return self._connection.execute(query, tuple(params))

    def executemany(self, query: str, params: Iterable[Iterable[Any]]) -> sqlite3.Cursor:
        with self._lock, self._connection:
            return self._connection.executemany(query, [tuple(row) for row in params])

    def _decode(self, table: str, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        for column in JSON_COLUMNS.get(table, ()):
            value = data.get(column)
            if isinstance(value, str) and value:
                try:
                    data[column] = json.loads(value)
                except json.JSONDecodeError:
                    pass
        for column in BOOLEAN_COLUMNS.get(table, ()):
            if column in data and data[column] is not None:
                data[column] = bool(data[column])
        return data

    def one(
        self, query: str, params: Iterable[Any] = (), table: str | None = None
    ) -> dict[str, Any] | None:
        row = self.execute(query, params).fetchone()
        if not row:
            return None
        if table is None:
            table = self._table_from_query(query)
        return self._decode(table, row)

    def many(
        self, query: str, params: Iterable[Any] = (), table: str | None = None
    ) -> list[dict[str, Any]]:
        rows = self.execute(query, params).fetchall()
        if table is None:
            table = self._table_from_query(query)
        return [self._decode(table, row) for row in rows]

    @staticmethod
    def _table_from_query(query: str) -> str:
        lowered = query.lower()
        for table in JSON_COLUMNS:
            if f"from {table}" in lowered or f"into {table}" in lowered or f"update {table}" in lowered:
                return table
        return ""

    def insert(self, table: str, data: dict[str, Any]) -> dict[str, Any]:
        columns = list(data)
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)
        self.execute(
            f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
            [self._encode(table, column, data[column]) for column in columns],
        )
        row_id = data.get("id")
        if row_id is not None:
            row = self.one(f"SELECT * FROM {table} WHERE id = ?", (row_id,), table)
            return row or {}
        return {}

    def update(self, table: str, row_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if not data:
            return self.one(f"SELECT * FROM {table} WHERE id = ?", (row_id,), table) or {}
        assignments = ", ".join(f"{column} = ?" for column in data)
        values = [self._encode(table, column, value) for column, value in data.items()]
        self.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", [*values, row_id])
        return self.one(f"SELECT * FROM {table} WHERE id = ?", (row_id,), table) or {}

    def _encode(self, table: str, column: str, value: Any) -> Any:
        if column in JSON_COLUMNS.get(table, ()) and isinstance(value, (dict, list)):
            return json.dumps(value, sort_keys=True)
        if isinstance(value, bool):
            return int(value)
        return value

    def count(self, table: str, where: str = "", params: Iterable[Any] = ()) -> int:
        query = f"SELECT COUNT(*) AS count FROM {table}"
        if where:
            query += f" WHERE {where}"
        row = self.one(query, params, table)
        return int(row["count"]) if row else 0

    def audit(
        self,
        actor: str,
        action: str,
        target: str,
        payload: dict[str, Any] | str | None = None,
        approval_id: str | None = None,
    ) -> None:
        if payload is None:
            encoded = "{}"
        elif isinstance(payload, str):
            try:
                json.loads(payload)
                encoded = payload
            except json.JSONDecodeError:
                encoded = json.dumps({"message": payload})
        else:
            encoded = json.dumps(payload, sort_keys=True, default=str)
        self.execute(
            "INSERT INTO audit_events (actor, action, target, payload, approval_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (actor, action, target, encoded, approval_id),
        )

    # ------------------------------------------------------------- system state
    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM system_state WHERE key = ?", (key,), "")
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    def set_state(self, key: str, value: Any) -> None:
        encoded = json.dumps(value)
        self.execute(
            """
            INSERT INTO system_state (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """,
            (key, encoded),
        )

    def is_emergency_stopped(self) -> bool:
        return bool(self.get_state("emergency_stop", False))

    def backup(self, destination: str | Path) -> Path:
        target_path = Path(destination)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            target = sqlite3.connect(str(target_path))
            try:
                self._connection.backup(target)
            finally:
                target.close()
        return target_path

    def integrity_check(self) -> str:
        row = self.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "unknown"

    def reset_domain_data(self) -> None:
        """Clear operational data while preserving the seeded organisation."""
        with self._lock, self._connection:
            for table in TABLE_ORDER:
                self._connection.execute(f"DELETE FROM {table}")
            self._connection.execute("DELETE FROM sqlite_sequence")
            self._connection.execute("DELETE FROM system_state")

    def close(self) -> None:
        with self._lock:
            self._connection.close()


store = Store()
