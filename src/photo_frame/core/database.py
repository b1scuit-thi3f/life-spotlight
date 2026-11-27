"""SQLite access. Column names stay as stored so an existing cache keeps working."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from photo_frame.core.time import toIso

schema = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY,
    immich_id TEXT NOT NULL UNIQUE,
    media_type TEXT NOT NULL CHECK (media_type IN ('photo', 'video')),
    filename TEXT,
    mime_type TEXT,
    local_path TEXT NOT NULL UNIQUE,
    captured_at TEXT,
    immich_created_at TEXT,
    immich_updated_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_displayed_at TEXT,
    display_count INTEGER NOT NULL DEFAULT 0,
    width INTEGER,
    height INTEGER,
    duration_seconds REAL,
    file_size_bytes INTEGER,
    checksum TEXT,
    is_present INTEGER NOT NULL DEFAULT 1 CHECK (is_present IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_media_first_seen_at ON media(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_media_captured_at ON media(captured_at);
CREATE INDEX IF NOT EXISTS idx_media_last_displayed_at ON media(last_displayed_at);
CREATE INDEX IF NOT EXISTS idx_media_type ON media(media_type);

CREATE TABLE IF NOT EXISTS playback_history (
    id INTEGER PRIMARY KEY,
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    displayed_at TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    completed INTEGER NOT NULL DEFAULT 1 CHECK (completed IN (0, 1)),
    audio_enabled INTEGER NOT NULL DEFAULT 0 CHECK (audio_enabled IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_playback_history_media_time
    ON playback_history(media_id, displayed_at);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""

# Stored keys. These strings are the SQLite contract, not Python names.
settingDefaults: dict[str, str] = {
    "immich_url": "",
    "album_id": "",
    "album_name": "",
    "api_key": "",
    "presentation_mode": "balanced",
    "photo_duration_seconds": "12",
    "new_window_hours": "48",
    "show_overlay": "1",
    "videos_enabled": "1",
    "transition": "fade",
    "cache_ceiling_bytes": "28000000000",
    "reserved_bytes": "1000000000",
    "sync_incremental_minutes": "60",
    "sync_reconcile_hours": "24",
    "http_timeout_seconds": "60",
    "download_timeout_seconds": "300",
}


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.migrate()

    def close(self) -> None:
        self.connection.close()

    def migrate(self) -> None:
        self.connection.executescript(schema)
        applied = {row["version"] for row in self.connection.execute("SELECT version FROM schema_migrations")}
        if 1 not in applied:
            self.connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (1, toIso(datetime.now(timezone.utc))),
            )

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, tuple(params))

    def getSetting(self, key: str, default: str | None = None) -> str | None:
        row = self.connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return str(row["value"])

    def setSetting(self, key: str, value: str) -> None:
        now = toIso(datetime.now(timezone.utc))
        self.connection.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )

    def allSettings(self) -> dict[str, str]:
        rows = self.connection.execute("SELECT key, value FROM settings").fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def getSync(self, key: str, default: str | None = None) -> str | None:
        row = self.connection.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return str(row["value"])

    def setSync(self, key: str, value: str) -> None:
        now = toIso(datetime.now(timezone.utc))
        self.connection.execute(
            """
            INSERT INTO sync_state (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )

    def allSync(self) -> dict[str, str]:
        rows = self.connection.execute("SELECT key, value FROM sync_state").fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}
