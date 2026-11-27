"""Admin mutations: Immich, display, storage, sync, and Wi-Fi."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from photo_frame.core.immich import ImmichClient, ImmichError
from photo_frame.core.settings import SettingsError, SettingsService
from photo_frame.models.display import DisplayState, DisplayUpdate
from photo_frame.models.immich import AlbumSummary, ImmichTestResult, ImmichUpdate
from photo_frame.models.network import WifiConnectResult, WifiNetworks, WifiUpdate
from photo_frame.models.sync import SyncTriggerResult
from photo_frame.models.system import SystemState, SystemUpdate

router = APIRouter()


@router.post("/api/admin/display")
def updateDisplay(request: Request, payload: DisplayUpdate):
    settings: SettingsService = request.app.state.settingsService
    try:
        settings.updateDisplay(payload.model_dump(exclude_none=True))
    except (SettingsError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    request.app.state.selector.newWindowHours = settings.newWindowHours()
    return {
        "ok": True,
        "display": DisplayState(
            presentationMode=settings.presentationMode(),
            photoDurationSeconds=settings.photoDurationSeconds(),
            showOverlay=settings.showOverlay(),
            videosEnabled=settings.videosEnabled(),
            transition=settings.transition(),
            newWindowHours=settings.newWindowHours(),
        ),
    }


@router.post("/api/admin/system")
def updateSystem(request: Request, payload: SystemUpdate):
    settings: SettingsService = request.app.state.settingsService
    try:
        settings.updateSystem(payload.model_dump(exclude_none=True))
    except (SettingsError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    cache = request.app.state.cache
    cache.ceilingBytes = settings.cacheCeilingBytes()
    cache.reservedBytes = settings.reservedBytes()
    return {
        "ok": True,
        "system": SystemState(
            cacheCeilingBytes=settings.cacheCeilingBytes(),
            reservedBytes=settings.reservedBytes(),
            syncIncrementalMinutes=settings.syncIncrementalMinutes(),
            syncReconcileHours=settings.syncReconcileHours(),
            httpTimeoutSeconds=settings.httpTimeoutSeconds(),
            downloadTimeoutSeconds=settings.downloadTimeoutSeconds(),
        ),
    }


@router.post("/api/admin/immich")
def updateImmich(request: Request, payload: ImmichUpdate):
    settings: SettingsService = request.app.state.settingsService
    try:
        settings.updateImmich(payload.model_dump(exclude_none=True))
    except SettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ok": True,
        "immichUrl": settings.immichUrl(),
        "albumId": settings.albumId(),
        "apiKeyConfigured": bool(settings.apiKey()),
    }


@router.post("/api/admin/immich/test")
def testImmich(request: Request, payload: ImmichUpdate):
    settings: SettingsService = request.app.state.settingsService
    try:
        settings.updateImmich(payload.model_dump(exclude_none=True))
        client = ImmichClient(
            settings.immichUrl(),
            settings.apiKey(),
            timeout=settings.httpTimeoutSeconds(),
            downloadTimeout=settings.downloadTimeoutSeconds(),
        )
        info = client.ping()
        albums = [
            AlbumSummary(
                id=item.get("id"),
                name=item.get("albumName") or item.get("name"),
                count=item.get("assetCount"),
            )
            for item in client.listAlbums()
        ]
    except SettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ImmichError as exc:
        return JSONResponse(
            status_code=502,
            content=ImmichTestResult(ok=False, errorClass=exc.errorClass, message=str(exc)).model_dump(),
        )
    version = info.get("version")
    server = version if isinstance(version, str) else str(version) if version is not None else None
    return ImmichTestResult(ok=True, server=server, albums=albums)


@router.post("/api/admin/sync")
def triggerSync(request: Request, kind: str = "incremental") -> SyncTriggerResult:
    if kind not in {"incremental", "reconciliation"}:
        raise HTTPException(status_code=422, detail="unknown sync kind")
    if request.app.state.db.getSync("sync_in_progress") == "1":
        raise HTTPException(status_code=409, detail="a sync is already running")
    try:
        result = request.app.state.scheduler.runNow(kind)
    except ImmichError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SyncTriggerResult(
        ok=result.success,
        kind=result.kind,
        message=result.message,
        added=result.added,
        updated=result.updated,
        removed=result.removed,
        unchanged=result.unchanged,
        skipped=result.skipped,
        errorClass=result.errorClass,
    )


@router.get("/api/admin/wifi")
def wifiNetworks(request: Request) -> WifiNetworks:
    network = request.app.state.network
    return WifiNetworks(networks=network.wifiNetworks(), nmcli=network.status().nmcliAvailable)


@router.post("/api/admin/wifi")
def connectWifi(request: Request, payload: WifiUpdate) -> WifiConnectResult:
    ok, message = request.app.state.network.connectWifi(payload.ssid, payload.password)
    return WifiConnectResult(ok=ok, message=message)


@router.get("/api/admin/history")
def history(request: Request):
    return {"history": request.app.state.repository.recentHistory()}
