"""SQLite state for the automation pipeline.

The pipeline keeps its own database so a long generation/publish cycle never
holds the Founder Control Tower's ``factory.db`` write lock.  Every stage is
idempotent: links are unique by URL, generations by ``(link_id, variant)`` and
posts by ``(generation_id, platform)``.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable


LINK_STATUSES = {
    "new",
    "generating",
    "generated",
    "done",
    "failed",
    "skipped",
    "deferred",
}
GENERATION_STATUSES = {
    "pending",
    "generating",
    "downloaded",
    "qc_failed",
    "ready",
    "publishing",
    "partially_published",
    "published",
    "failed",
    "skipped",
    "deferred",
}
POST_STATUSES = {
    "pending",
    "publishing",
    "published",
    "dry_run",
    "deferred",
    "failed",
    "skipped",
}


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    video_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    duration TEXT NOT NULL DEFAULT '',
    view_count TEXT NOT NULL DEFAULT '',
    published TEXT NOT NULL DEFAULT '',
    query TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS generations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    variant INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    direction TEXT NOT NULL DEFAULT '',
    guest_path TEXT,
    host_path TEXT,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    duration_seconds REAL,
    width INTEGER,
    height INTEGER,
    credits REAL,
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(link_id, variant)
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generation_id INTEGER NOT NULL REFERENCES generations(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    live INTEGER NOT NULL DEFAULT 0,
    remote_hint TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(generation_id, platform)
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    stats TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    kind TEXT NOT NULL,
    subject TEXT,
    message TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_links_status ON links(status, id);
CREATE INDEX IF NOT EXISTS idx_generations_status ON generations(status, id);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(platform, status, id);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PipelineDB:
    """Thin, explicitly-committed SQLite repository."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(
            str(self.path), check_same_thread=False, timeout=30
        )
        self._connection.row_factory = sqlite3.Row
        self.initialize()

    def initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(SCHEMA)

    # ------------------------------------------------------------------ utils
    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _rows(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            cursor = self._connection.execute(sql, tuple(params))
            return [dict(row) for row in cursor.fetchall()]

    def _row(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    def _write(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock, self._connection:
            return self._connection.execute(sql, tuple(params))

    # ------------------------------------------------------------------ links
    def add_link(self, meta: dict[str, Any]) -> tuple[int, bool]:
        """Insert a discovered link. Returns ``(id, created)``."""
        url = str(meta.get("url") or "").strip()
        if not url:
            raise ValueError("link url is required")
        existing = self._row("SELECT id FROM links WHERE url = ?", (url,))
        if existing:
            return int(existing["id"]), False
        cursor = self._write(
            """
            INSERT INTO links (url, video_id, title, channel, duration,
                               view_count, published, query, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new')
            """,
            (
                url,
                meta.get("video_id", ""),
                meta.get("title", ""),
                meta.get("channel", ""),
                meta.get("duration", ""),
                meta.get("view_count", ""),
                meta.get("published", ""),
                meta.get("query", ""),
            ),
        )
        return int(cursor.lastrowid or 0), True

    def get_link(self, link_id: int) -> dict[str, Any] | None:
        return self._row("SELECT * FROM links WHERE id = ?", (link_id,))

    def update_link(self, link_id: int, **fields: Any) -> None:
        allowed = {
            "status",
            "attempts",
            "error",
            "video_id",
            "title",
            "channel",
            "duration",
            "view_count",
            "published",
            "query",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        updates["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        self._write(
            f"UPDATE links SET {assignments} WHERE id = ?",
            (*updates.values(), link_id),
        )

    def links(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if status:
            return self._rows(
                "SELECT * FROM links WHERE status = ? ORDER BY id LIMIT ?",
                (status, limit),
            )
        return self._rows("SELECT * FROM links ORDER BY id DESC LIMIT ?", (limit,))

    def claim_links(self, limit: int) -> list[dict[str, Any]]:
        """Return the oldest ``new`` links and mark them ``generating``."""
        rows = self._rows(
            "SELECT * FROM links WHERE status = 'new' ORDER BY id LIMIT ?", (limit,)
        )
        for row in rows:
            attempts = int(row["attempts"] or 0) + 1
            self.update_link(
                int(row["id"]), status="generating", attempts=attempts
            )
            row["status"] = "generating"
            row["attempts"] = attempts
        return rows

    # ------------------------------------------------------------ generations
    def create_generation(
        self,
        link_id: int,
        variant: int,
        direction: str = "",
        status: str = "pending",
    ) -> int:
        cursor = self._write(
            """
            INSERT OR IGNORE INTO generations
                (link_id, variant, status, direction)
            VALUES (?, ?, ?, ?)
            """,
            (link_id, variant, status, direction),
        )
        if cursor.lastrowid:
            return int(cursor.lastrowid)
        row = self._row(
            "SELECT id FROM generations WHERE link_id = ? AND variant = ?",
            (link_id, variant),
        )
        return int(row["id"]) if row else 0

    def get_generation(self, generation_id: int) -> dict[str, Any] | None:
        return self._row("SELECT * FROM generations WHERE id = ?", (generation_id,))

    def update_generation(self, generation_id: int, **fields: Any) -> None:
        allowed = {
            "status",
            "guest_path",
            "host_path",
            "title",
            "description",
            "duration_seconds",
            "width",
            "height",
            "credits",
            "attempts",
            "error",
            "direction",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        updates["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        self._write(
            f"UPDATE generations SET {assignments} WHERE id = ?",
            (*updates.values(), generation_id),
        )

    def generations(
        self, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if status:
            return self._rows(
                "SELECT * FROM generations WHERE status = ? ORDER BY id LIMIT ?",
                (status, limit),
            )
        return self._rows(
            "SELECT * FROM generations ORDER BY id DESC LIMIT ?", (limit,)
        )

    def generations_for_link(self, link_id: int) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT * FROM generations WHERE link_id = ? ORDER BY variant", (link_id,)
        )

    def generation_for_variant(self, link_id: int, variant: int) -> dict[str, Any] | None:
        return self._row(
            "SELECT * FROM generations WHERE link_id = ? AND variant = ?",
            (link_id, variant),
        )

    def pending_variants(
        self, link_id: int, variants: int, retry_limit: int = 2
    ) -> list[int]:
        rows = self._rows(
            "SELECT variant, status, attempts FROM generations WHERE link_id = ?",
            (link_id,),
        )
        existing = {
            int(row["variant"]): (str(row["status"]), int(row["attempts"] or 0))
            for row in rows
        }
        pending: list[int] = []
        for index in range(variants):
            if index not in existing:
                pending.append(index)
                continue
            status, attempts = existing[index]
            if status == "deferred":
                pending.append(index)
            elif status in {"pending", "failed"} and attempts < max(1, retry_limit):
                pending.append(index)
        return pending

    # ------------------------------------------------------------------ posts
    def enqueue_posts(self, generation_id: int, platforms: Iterable[str]) -> None:
        for platform in platforms:
            self._write(
                """
                INSERT OR IGNORE INTO posts (generation_id, platform, status)
                VALUES (?, ?, 'pending')
                """,
                (generation_id, platform),
            )

    def posts_for_generation(self, generation_id: int) -> list[dict[str, Any]]:
        return self._rows(
            "SELECT * FROM posts WHERE generation_id = ? ORDER BY id", (generation_id,)
        )

    def update_post(self, post_id: int, **fields: Any) -> None:
        allowed = {"status", "live", "remote_hint", "error", "attempts"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        updates["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        self._write(
            f"UPDATE posts SET {assignments} WHERE id = ?",
            (*updates.values(), post_id),
        )

    def publishable_generations(
        self, platforms: Iterable[str], limit: int = 100
    ) -> list[dict[str, Any]]:
        platforms = list(platforms)
        if not platforms:
            return []
        placeholders = ",".join("?" for _ in platforms)
        return self._rows(
            f"""
            SELECT DISTINCT g.*
            FROM generations g
            JOIN posts p ON p.generation_id = g.id
            WHERE g.status IN ('ready', 'partially_published', 'published',
                               'downloaded')
              AND p.platform IN ({placeholders})
              AND p.status IN ('pending', 'failed', 'dry_run', 'deferred')
            ORDER BY g.id
            LIMIT ?
            """,
            (*platforms, limit),
        )

    def posts(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if status:
            return self._rows(
                "SELECT * FROM posts WHERE status = ? ORDER BY id LIMIT ?",
                (status, limit),
            )
        return self._rows("SELECT * FROM posts ORDER BY id DESC LIMIT ?", (limit,))

    def credits_spent(self, day: str | None = None) -> float:
        day = day or datetime.now(timezone.utc).date().isoformat()
        row = self._row(
            """
            SELECT COALESCE(SUM(credits), 0) AS total FROM generations
            WHERE substr(created_at, 1, 10) = ?
            """,
            (day,),
        )
        return round(float(row["total"]) if row else 0.0, 2)

    def daily_published_count(self, platform: str, day: str | None = None) -> int:
        day = day or datetime.now(timezone.utc).date().isoformat()
        row = self._row(
            """
            SELECT COUNT(*) AS count FROM posts
            WHERE platform = ? AND status = 'published'
              AND substr(updated_at, 1, 10) = ?
            """,
            (platform, day),
        )
        return int(row["count"]) if row else 0

    # ------------------------------------------------------------------- runs
    def create_run(self, mode: str) -> str:
        run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self._write(
            "INSERT INTO runs (id, mode, status) VALUES (?, ?, 'running')",
            (run_id, mode),
        )
        return run_id

    def finish_run(
        self,
        run_id: str,
        status: str,
        stats: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self._write(
            """
            UPDATE runs SET status = ?, stats = ?, error = ?, finished_at = ?
            WHERE id = ?
            """,
            (
                status,
                json.dumps(stats or {}, sort_keys=True, default=str),
                error,
                _now(),
                run_id,
            ),
        )

    def runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))

    # ----------------------------------------------------------------- events
    def log_event(
        self,
        kind: str,
        message: str,
        subject: str | int | None = None,
        run_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._write(
            """
            INSERT INTO events (run_id, kind, subject, message, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_id,
                kind,
                None if subject is None else str(subject),
                message,
                json.dumps(payload or {}, sort_keys=True, default=str),
            ),
        )

    def events(self, limit: int = 100, run_id: str | None = None) -> list[dict[str, Any]]:
        if run_id:
            return self._rows(
                "SELECT * FROM events WHERE run_id = ? ORDER BY id DESC LIMIT ?",
                (run_id, limit),
            )
        return self._rows("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))

    # -------------------------------------------------------------------- kv
    def set_kv(self, key: str, value: Any) -> None:
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        self._write(
            """
            INSERT INTO kv (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                          updated_at = excluded.updated_at
            """,
            (key, text, _now()),
        )

    def get_kv(self, key: str, default: Any = None) -> Any:
        row = self._row("SELECT value FROM kv WHERE key = ?", (key,))
        if not row:
            return default
        return row["value"]

    # ------------------------------------------------------------------ stats
    def stats(self) -> dict[str, Any]:
        def counts(table: str, statuses: Iterable[str]) -> dict[str, int]:
            result = {status: 0 for status in statuses}
            for row in self._rows(
                f"SELECT status, COUNT(*) AS count FROM {table} GROUP BY status"
            ):
                result[str(row["status"])] = int(row["count"])
            return result

        last_run = self.runs(1)
        return {
            "links": counts("links", LINK_STATUSES),
            "generations": counts("generations", GENERATION_STATUSES),
            "posts": counts("posts", POST_STATUSES),
            "last_run": last_run[0] if last_run else None,
            "db_path": str(self.path),
        }
