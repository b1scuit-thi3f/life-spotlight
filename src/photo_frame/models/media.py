"""Local media records and the presentation payload."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from photo_frame.models.display import DisplayState

MediaType = Literal["photo", "video"]


@dataclass(slots=True)
class MediaRecord:
    id: int
    immichId: str
    mediaType: str
    filename: str | None
    mimeType: str | None
    localPath: str
    capturedAt: str | None
    immichCreatedAt: str | None
    immichUpdatedAt: str | None
    firstSeenAt: str
    lastDisplayedAt: str | None
    displayCount: int
    width: int | None
    height: int | None
    durationSeconds: float | None
    fileSizeBytes: int | None
    checksum: str | None
    isPresent: int


@dataclass(slots=True)
class Selection:
    media: MediaRecord
    isNew: bool
    reason: str


class PlaybackReport(BaseModel):
    mediaId: int
    durationSeconds: float = Field(ge=0, le=86_400)
    completed: bool = True
    audioEnabled: bool = False


class PresentationMedia(BaseModel):
    id: int
    mediaType: str
    mimeType: str | None
    url: str
    width: int | None
    height: int | None
    durationSeconds: float | None
    isNew: bool
    addedLabel: str
    capturedLabel: str
    filename: str | None


class PresentationNext(BaseModel):
    media: PresentationMedia | None
    reason: str | None = None
    display: DisplayState
