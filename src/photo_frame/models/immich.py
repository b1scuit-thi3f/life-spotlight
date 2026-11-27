"""Immich album records and the admin connection payload."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field

from photo_frame.models.media import MediaType


@dataclass(slots=True)
class RemoteAsset:
    immichId: str
    mediaType: MediaType
    filename: str | None = None
    mimeType: str | None = None
    capturedAt: datetime | None = None
    immichCreatedAt: datetime | None = None
    immichUpdatedAt: datetime | None = None
    width: int | None = None
    height: int | None = None
    durationSeconds: float | None = None
    fileSizeBytes: int | None = None
    checksum: str | None = None


@dataclass(slots=True)
class RemoteAlbum:
    albumId: str
    name: str
    assetCount: int
    updatedAt: datetime | None = None
    assets: list[RemoteAsset] = field(default_factory=list)


class ImmichUpdate(BaseModel):
    immichUrl: str | None = None
    albumId: str | None = None
    apiKey: str | None = None


class ImmichState(BaseModel):
    url: str
    albumId: str
    albumName: str
    apiKeyConfigured: bool


class AlbumSummary(BaseModel):
    id: str | None = None
    name: str | None = None
    count: int | None = None


class ImmichTestResult(BaseModel):
    ok: bool
    server: str | None = None
    albums: list[AlbumSummary] = Field(default_factory=list)
    errorClass: str | None = None
    message: str | None = None
