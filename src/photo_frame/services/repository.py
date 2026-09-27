"""Local media metadata. File bytes are owned by the cache, not this module."""

from __future__ import annotations

from photo_frame.helpers.db import Database
from photo_frame.helpers.models import MediaRecord, RemoteAsset
from photo_frame.helpers.timeutil import to_iso, utc_now


def row_to_media(row) -> MediaRecord:
    return MediaRecord(
        id=int(row["id"]),
        immich_id=row["immich_id"],
        media_type=row["media_type"],
        filename=row["filename"],
        mime_type=row["mime_type"],
        local_path=row["local_path"],
        captured_at=row["captured_at"],
        immich_created_at=row["immich_created_at"],
        immich_updated_at=row["immich_updated_at"],
        first_seen_at=row["first_seen_at"],
        last_displayed_at=row["last_displayed_at"],
        display_count=int(row["display_count"] or 0),
        width=row["width"],
        height=row["height"],
        duration_seconds=row["duration_seconds"],
        file_size_bytes=row["file_size_bytes"],
        checksum=row["checksum"],
        is_present=int(row["is_present"]),
    )


class MediaRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get_by_immich_id(self, immich_id: str) -> MediaRecord | None:
        row = self.db.execute(
            "SELECT * FROM media WHERE immich_id = ?",
            (immich_id,),
        ).fetchone()
        return row_to_media(row) if row else None

    def get(self, media_id: int) -> MediaRecord | None:
        row = self.db.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
        return row_to_media(row) if row else None

    def list_present(self, *, videos_enabled: bool = True) -> list[MediaRecord]:
        if videos_enabled:
            rows = self.db.execute(
                "SELECT * FROM media WHERE is_present = 1 ORDER BY id"
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM media WHERE is_present = 1 AND media_type = 'photo' ORDER BY id"
            ).fetchall()
        return [row_to_media(row) for row in rows]

    def counts(self) -> dict[str, int]:
        present = self.db.execute(
            "SELECT COUNT(*) AS n FROM media WHERE is_present = 1"
        ).fetchone()["n"]
        photos = self.db.execute(
            "SELECT COUNT(*) AS n FROM media WHERE is_present = 1 AND media_type = 'photo'"
        ).fetchone()["n"]
        videos = self.db.execute(
            "SELECT COUNT(*) AS n FROM media WHERE is_present = 1 AND media_type = 'video'"
        ).fetchone()["n"]
        absent = self.db.execute(
            "SELECT COUNT(*) AS n FROM media WHERE is_present = 0"
        ).fetchone()["n"]
        bytes_used = self.db.execute(
            "SELECT COALESCE(SUM(file_size_bytes), 0) AS n FROM media WHERE is_present = 1"
        ).fetchone()["n"]
        return {
            "present": int(present),
            "photos": int(photos),
            "videos": int(videos),
            "absent": int(absent),
            "bytes": int(bytes_used or 0),
        }

    def insert_pending(self, asset: RemoteAsset, local_path: str, first_seen_at: str) -> int:
        cursor = self.db.execute(
            """
            INSERT INTO media (
                immich_id, media_type, filename, mime_type, local_path,
                captured_at, immich_created_at, immich_updated_at, first_seen_at,
                width, height, duration_seconds, file_size_bytes, checksum, is_present
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                asset.immich_id,
                asset.media_type,
                asset.filename,
                asset.mime_type,
                local_path,
                _iso(asset.captured_at),
                _iso(asset.immich_created_at),
                _iso(asset.immich_updated_at),
                first_seen_at,
                asset.width,
                asset.height,
                asset.duration_seconds,
                asset.file_size_bytes,
                asset.checksum,
            ),
        )
        return int(cursor.lastrowid)

    def update_metadata(self, media_id: int, asset: RemoteAsset) -> None:
        self.db.execute(
            """
            UPDATE media SET
                media_type = ?,
                filename = ?,
                mime_type = ?,
                captured_at = ?,
                immich_created_at = ?,
                immich_updated_at = ?,
                width = ?,
                height = ?,
                duration_seconds = ?,
                file_size_bytes = ?,
                checksum = ?
            WHERE id = ?
            """,
            (
                asset.media_type,
                asset.filename,
                asset.mime_type,
                _iso(asset.captured_at),
                _iso(asset.immich_created_at),
                _iso(asset.immich_updated_at),
                asset.width,
                asset.height,
                asset.duration_seconds,
                asset.file_size_bytes,
                asset.checksum,
                media_id,
            ),
        )

    def mark_present(self, media_id: int, *, file_size_bytes: int | None, checksum: str | None) -> None:
        self.db.execute(
            """
            UPDATE media
            SET is_present = 1,
                file_size_bytes = COALESCE(?, file_size_bytes),
                checksum = COALESCE(?, checksum)
            WHERE id = ?
            """,
            (file_size_bytes, checksum, media_id),
        )

    def mark_absent(self, media_id: int) -> None:
        self.db.execute("UPDATE media SET is_present = 0 WHERE id = ?", (media_id,))

    def delete_media(self, media_id: int) -> None:
        self.db.execute("DELETE FROM media WHERE id = ?", (media_id,))

    def list_absent(self) -> list[MediaRecord]:
        rows = self.db.execute("SELECT * FROM media WHERE is_present = 0").fetchall()
        return [row_to_media(row) for row in rows]

    def record_display(
        self,
        media_id: int,
        *,
        duration_seconds: float,
        completed: bool,
        audio_enabled: bool,
    ) -> None:
        now = to_iso(utc_now())
        self.db.execute(
            """
            INSERT INTO playback_history
                (media_id, displayed_at, duration_seconds, completed, audio_enabled)
            VALUES (?, ?, ?, ?, ?)
            """,
            (media_id, now, duration_seconds, 1 if completed else 0, 1 if audio_enabled else 0),
        )
        self.db.execute(
            """
            UPDATE media
            SET last_displayed_at = ?, display_count = display_count + 1
            WHERE id = ?
            """,
            (now, media_id),
        )

    def recent_history(self, limit: int = 20) -> list[dict]:
        rows = self.db.execute(
            """
            SELECT h.displayed_at, h.duration_seconds, h.completed, h.audio_enabled,
                   m.immich_id, m.filename, m.media_type
            FROM playback_history h
            JOIN media m ON m.id = h.media_id
            ORDER BY h.displayed_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def _iso(value) -> str | None:
    if value is None:
        return None
    return to_iso(value)
