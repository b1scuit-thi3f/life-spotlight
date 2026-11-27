"""Local media metadata. File bytes are owned by the cache, not this module."""

from __future__ import annotations

from datetime import datetime, timezone

from photo_frame.core.database import Database
from photo_frame.core.time import toIso
from photo_frame.models.immich import RemoteAsset
from photo_frame.models.media import MediaRecord


def rowToMedia(row) -> MediaRecord:
    return MediaRecord(
        id=int(row["id"]),
        immichId=row["immich_id"],
        mediaType=row["media_type"],
        filename=row["filename"],
        mimeType=row["mime_type"],
        localPath=row["local_path"],
        capturedAt=row["captured_at"],
        immichCreatedAt=row["immich_created_at"],
        immichUpdatedAt=row["immich_updated_at"],
        firstSeenAt=row["first_seen_at"],
        lastDisplayedAt=row["last_displayed_at"],
        displayCount=int(row["display_count"] or 0),
        width=row["width"],
        height=row["height"],
        durationSeconds=row["duration_seconds"],
        fileSizeBytes=row["file_size_bytes"],
        checksum=row["checksum"],
        isPresent=int(row["is_present"]),
    )


def isoTimestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return toIso(value)


class MediaRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def getByImmichId(self, immichId: str) -> MediaRecord | None:
        row = self.db.execute("SELECT * FROM media WHERE immich_id = ?", (immichId,)).fetchone()
        return rowToMedia(row) if row else None

    def get(self, mediaId: int) -> MediaRecord | None:
        row = self.db.execute("SELECT * FROM media WHERE id = ?", (mediaId,)).fetchone()
        return rowToMedia(row) if row else None

    def listPresent(self, *, videosEnabled: bool = True) -> list[MediaRecord]:
        if videosEnabled:
            rows = self.db.execute("SELECT * FROM media WHERE is_present = 1 ORDER BY id").fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM media WHERE is_present = 1 AND media_type = 'photo' ORDER BY id"
            ).fetchall()
        return [rowToMedia(row) for row in rows]

    def counts(self) -> dict[str, int]:
        present = self.db.execute("SELECT COUNT(*) AS n FROM media WHERE is_present = 1").fetchone()["n"]
        photos = self.db.execute(
            "SELECT COUNT(*) AS n FROM media WHERE is_present = 1 AND media_type = 'photo'"
        ).fetchone()["n"]
        videos = self.db.execute(
            "SELECT COUNT(*) AS n FROM media WHERE is_present = 1 AND media_type = 'video'"
        ).fetchone()["n"]
        absent = self.db.execute("SELECT COUNT(*) AS n FROM media WHERE is_present = 0").fetchone()["n"]
        bytesUsed = self.db.execute(
            "SELECT COALESCE(SUM(file_size_bytes), 0) AS n FROM media WHERE is_present = 1"
        ).fetchone()["n"]
        return {
            "present": int(present),
            "photos": int(photos),
            "videos": int(videos),
            "absent": int(absent),
            "bytes": int(bytesUsed or 0),
        }

    def insertPending(self, asset: RemoteAsset, localPath: str, firstSeenAt: str) -> int:
        cursor = self.db.execute(
            """
            INSERT INTO media (
                immich_id, media_type, filename, mime_type, local_path,
                captured_at, immich_created_at, immich_updated_at, first_seen_at,
                width, height, duration_seconds, file_size_bytes, checksum, is_present
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                asset.immichId,
                asset.mediaType,
                asset.filename,
                asset.mimeType,
                localPath,
                isoTimestamp(asset.capturedAt),
                isoTimestamp(asset.immichCreatedAt),
                isoTimestamp(asset.immichUpdatedAt),
                firstSeenAt,
                asset.width,
                asset.height,
                asset.durationSeconds,
                asset.fileSizeBytes,
                asset.checksum,
            ),
        )
        return int(cursor.lastrowid)

    def updateMetadata(self, mediaId: int, asset: RemoteAsset) -> None:
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
                asset.mediaType,
                asset.filename,
                asset.mimeType,
                isoTimestamp(asset.capturedAt),
                isoTimestamp(asset.immichCreatedAt),
                isoTimestamp(asset.immichUpdatedAt),
                asset.width,
                asset.height,
                asset.durationSeconds,
                asset.fileSizeBytes,
                asset.checksum,
                mediaId,
            ),
        )

    def markPresent(self, mediaId: int, *, fileSizeBytes: int | None, checksum: str | None) -> None:
        self.db.execute(
            """
            UPDATE media
            SET is_present = 1,
                file_size_bytes = COALESCE(?, file_size_bytes),
                checksum = COALESCE(?, checksum)
            WHERE id = ?
            """,
            (fileSizeBytes, checksum, mediaId),
        )

    def markAbsent(self, mediaId: int) -> None:
        self.db.execute("UPDATE media SET is_present = 0 WHERE id = ?", (mediaId,))

    def deleteMedia(self, mediaId: int) -> None:
        self.db.execute("DELETE FROM media WHERE id = ?", (mediaId,))

    def listAbsent(self) -> list[MediaRecord]:
        rows = self.db.execute("SELECT * FROM media WHERE is_present = 0").fetchall()
        return [rowToMedia(row) for row in rows]

    def recordDisplay(
        self,
        mediaId: int,
        *,
        durationSeconds: float,
        completed: bool,
        audioEnabled: bool,
    ) -> None:
        now = toIso(datetime.now(timezone.utc))
        self.db.execute(
            """
            INSERT INTO playback_history
                (media_id, displayed_at, duration_seconds, completed, audio_enabled)
            VALUES (?, ?, ?, ?, ?)
            """,
            (mediaId, now, durationSeconds, 1 if completed else 0, 1 if audioEnabled else 0),
        )
        self.db.execute(
            """
            UPDATE media
            SET last_displayed_at = ?, display_count = display_count + 1
            WHERE id = ?
            """,
            (now, mediaId),
        )

    def recentHistory(self, limit: int = 20) -> list[dict]:
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
        return [
            {
                "displayedAt": row["displayed_at"],
                "durationSeconds": row["duration_seconds"],
                "completed": bool(row["completed"]),
                "audioEnabled": bool(row["audio_enabled"]),
                "immichId": row["immich_id"],
                "filename": row["filename"],
                "mediaType": row["media_type"],
            }
            for row in rows
        ]
