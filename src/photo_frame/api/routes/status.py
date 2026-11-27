"""Health and the admin status snapshot."""

from __future__ import annotations

from fastapi import APIRouter, Request

from photo_frame import __version__
from photo_frame.core.settings import SettingsService
from photo_frame.core.status import displayState, systemState
from photo_frame.core.time import toIso, utcNow
from photo_frame.models.immich import ImmichState
from photo_frame.models.network import NetworkState
from photo_frame.models.sync import CacheState, StatusReport, SyncState

router = APIRouter()


@router.get("/api/health")
def health():
    return {"ok": True, "version": __version__}


@router.get("/api/status")
def status(request: Request) -> StatusReport:
    app = request.app
    settings: SettingsService = app.state.settingsService
    cache = app.state.cache
    cache.ceilingBytes = settings.cacheCeilingBytes()
    counts = app.state.repository.counts()
    net = app.state.network.status()
    syncState = app.state.db.allSync()
    started = app.state.startedAt
    return StatusReport(
        version=__version__,
        startedAt=toIso(started),
        uptimeSeconds=int((utcNow() - started).total_seconds()),
        hostname=app.state.runtime.hostname,
        network=NetworkState(
            connected=net.connected,
            ssid=net.ssid,
            addresses=net.addresses,
            nmcliAvailable=net.nmcliAvailable,
        ),
        immich=ImmichState(
            url=settings.immichUrl(),
            albumId=settings.albumId(),
            albumName=settings.albumName(),
            apiKeyConfigured=bool(settings.apiKey()),
        ),
        sync=SyncState(
            inProgress=syncState.get("sync_in_progress") == "1",
            lastAttemptedAt=syncState.get("last_attempted_at"),
            lastAttemptedKind=syncState.get("last_attempted_kind"),
            lastSuccessAt=syncState.get("last_success_at"),
            lastFullReconciliationAt=syncState.get("last_full_reconciliation_at"),
            lastErrorClass=syncState.get("last_error_class") or "",
            lastErrorMessage=syncState.get("last_error_message") or "",
            lastRemoteCount=syncState.get("last_remote_count"),
            lastResultMessage=syncState.get("last_result_message") or "",
            currentlyDisplayedId=syncState.get("currently_displayed_id"),
        ),
        cache=CacheState(
            assets=counts["present"],
            photos=counts["photos"],
            videos=counts["videos"],
            bytes=cache.usageBytes(),
            ceilingBytes=cache.ceilingBytes,
            freeBytes=cache.filesystemFreeBytes(),
        ),
        display=displayState(settings),
        system=systemState(settings),
    )
