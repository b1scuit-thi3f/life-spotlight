"""Sync outcomes and the status block shown on the admin page."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from photo_frame.models.display import DisplayState
from photo_frame.models.immich import ImmichState
from photo_frame.models.network import NetworkState
from photo_frame.models.system import SystemState


@dataclass(slots=True)
class SyncResult:
    kind: str
    success: bool
    startedAt: str
    finishedAt: str
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    skipped: int = 0
    remoteCount: int | None = None
    errorClass: str | None = None
    message: str = ""


class SyncState(BaseModel):
    inProgress: bool
    lastAttemptedAt: str | None = None
    lastAttemptedKind: str | None = None
    lastSuccessAt: str | None = None
    lastFullReconciliationAt: str | None = None
    lastErrorClass: str = ""
    lastErrorMessage: str = ""
    lastRemoteCount: str | None = None
    lastResultMessage: str = ""
    currentlyDisplayedId: str | None = None


class CacheState(BaseModel):
    assets: int
    photos: int
    videos: int
    bytes: int
    ceilingBytes: int
    freeBytes: int | None = None


class StatusReport(BaseModel):
    version: str
    startedAt: str
    uptimeSeconds: int
    hostname: str
    network: NetworkState
    immich: ImmichState
    sync: SyncState
    cache: CacheState
    display: DisplayState
    system: SystemState


class SyncTriggerResult(BaseModel):
    ok: bool
    kind: str
    message: str
    added: int
    updated: int
    removed: int
    unchanged: int
    skipped: int
    errorClass: str | None = None
