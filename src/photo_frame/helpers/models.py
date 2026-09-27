"""Domain models shared by sync, selection, and the HTTP layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

MediaType = Literal["photo", "video"]
PresentationMode = Literal["now", "newest", "random", "balanced"]
PRESENTATION_MODES: tuple[str, ...] = ("now", "newest", "random", "balanced")
TRANSITIONS: tuple[str, ...] = ("none", "fade")


@dataclass(slots=True)
class RemoteAsset:
    immich_id: str
    media_type: MediaType
    filename: str | None = None
    mime_type: str | None = None
    captured_at: datetime | None = None
    immich_created_at: datetime | None = None
    immich_updated_at: datetime | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    file_size_bytes: int | None = None
    checksum: str | None = None


@dataclass(slots=True)
class RemoteAlbum:
    album_id: str
    name: str
    asset_count: int
    updated_at: datetime | None = None
    assets: list[RemoteAsset] = field(default_factory=list)


@dataclass(slots=True)
class MediaRecord:
    id: int
    immich_id: str
    media_type: str
    filename: str | None
    mime_type: str | None
    local_path: str
    captured_at: str | None
    immich_created_at: str | None
    immich_updated_at: str | None
    first_seen_at: str
    last_displayed_at: str | None
    display_count: int
    width: int | None
    height: int | None
    duration_seconds: float | None
    file_size_bytes: int | None
    checksum: str | None
    is_present: int


@dataclass(slots=True)
class SyncResult:
    kind: str
    success: bool
    started_at: str
    finished_at: str
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    skipped: int = 0
    remote_count: int | None = None
    error_class: str | None = None
    message: str = ""
