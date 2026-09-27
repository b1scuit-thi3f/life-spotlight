"""Application coordinator: wiring, lifecycle, and HTTP surface."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.staticfiles import StaticFiles as StarletteStaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from photo_frame import __version__
from photo_frame.config import RuntimeConfig, SettingsError, SettingsService, configure_logging
from photo_frame.helpers.db import Database
from photo_frame.helpers.timeutil import age_label, parse_iso, to_iso, utc_now
from photo_frame.services.cache import MediaCache
from photo_frame.services.immich import ImmichClient, ImmichError
from photo_frame.services.network import NetworkAdapter
from photo_frame.services.repository import MediaRepository
from photo_frame.services.scheduler import SyncScheduler
from photo_frame.services.selection import SelectionEngine
from photo_frame.services.sync import SyncService

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))


class DisplayUpdate(BaseModel):
    presentation_mode: str | None = None
    photo_duration_seconds: int | None = Field(default=None, ge=3, le=300)
    show_overlay: bool | None = None
    videos_enabled: bool | None = None
    transition: str | None = None
    new_window_hours: int | None = Field(default=None, ge=1, le=720)


class SystemUpdate(BaseModel):
    cache_ceiling_bytes: int | None = Field(default=None, ge=100_000_000, le=2_000_000_000_000)
    reserved_bytes: int | None = Field(default=None, ge=0, le=100_000_000_000)
    sync_incremental_minutes: int | None = Field(default=None, ge=5, le=1440)
    sync_reconcile_hours: int | None = Field(default=None, ge=1, le=336)
    http_timeout_seconds: int | None = Field(default=None, ge=5, le=600)
    download_timeout_seconds: int | None = Field(default=None, ge=30, le=3600)


class ImmichUpdate(BaseModel):
    immich_url: str | None = None
    album_id: str | None = None
    api_key: str | None = None


class PlaybackReport(BaseModel):
    media_id: int
    duration_seconds: float = Field(ge=0, le=86_400)
    completed: bool = True
    audio_enabled: bool = False


class WifiUpdate(BaseModel):
    ssid: str = Field(min_length=1, max_length=64)
    password: str = Field(default="", max_length=128)


class NoCacheStaticFiles(StarletteStaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(runtime: RuntimeConfig | None = None) -> FastAPI:
    runtime = runtime or RuntimeConfig()
    configure_logging(runtime.log_level)
    runtime.ensure_dirs()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.started_at = utc_now()
        app.state.scheduler.start()
        logger.info("photo frame %s listening; data dir %s", __version__, runtime.data_dir)
        yield
        app.state.scheduler.stop()
        app.state.db.close()

    app = FastAPI(title="Photo Frame", version=__version__, lifespan=lifespan)
    db = Database(runtime.database_path)
    settings_service = SettingsService(db)
    repository = MediaRepository(db)
    cache = MediaCache(
        runtime.cache_dir,
        runtime.tmp_dir,
        ceiling_bytes=settings_service.cache_ceiling_bytes(),
        reserved_bytes=settings_service.reserved_bytes(),
    )
    sync = SyncService(db, repository, cache)
    scheduler = SyncScheduler(sync, settings_service)
    network = NetworkAdapter(runtime.hostname)

    app.state.runtime = runtime
    app.state.db = db
    app.state.settings_service = settings_service
    app.state.repository = repository
    app.state.cache = cache
    app.state.sync = sync
    app.state.scheduler = scheduler
    app.state.network = network
    app.state.selector = SelectionEngine(new_window_hours=settings_service.new_window_hours())

    app.mount("/static", NoCacheStaticFiles(directory=str(WEB_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def presentation(request: Request):
        return templates.TemplateResponse(request, "presentation.html", {"version": __version__})

    @app.get("/admin", response_class=HTMLResponse)
    def admin(request: Request):
        return templates.TemplateResponse(
            request,
            "admin.html",
            {"version": __version__, "hostname": runtime.hostname},
        )

    @app.get("/setup", response_class=HTMLResponse)
    def setup(request: Request):
        return templates.TemplateResponse(request, "setup.html", {"version": __version__})

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.get("/api/status")
    def status():
        svc: SettingsService = app.state.settings_service
        repo: MediaRepository = app.state.repository
        media_cache: MediaCache = app.state.cache
        media_cache.ceiling_bytes = svc.cache_ceiling_bytes()
        counts = repo.counts()
        net = app.state.network.status()
        sync_state = app.state.db.all_sync()
        started = app.state.started_at
        return {
            "version": __version__,
            "started_at": to_iso(started),
            "uptime_seconds": int((utc_now() - started).total_seconds()),
            "hostname": runtime.hostname,
            "network": {
                "connected": net.connected,
                "ssid": net.ssid,
                "addresses": net.addresses,
                "nmcli_available": net.nmcli_available,
            },
            "immich": {
                "url": svc.immich_url(),
                "album_id": svc.album_id(),
                "album_name": app.state.db.get_setting("album_name") or "",
                "api_key_configured": bool(svc.api_key()),
            },
            "sync": {
                "in_progress": sync_state.get("sync_in_progress") == "1",
                "last_attempted_at": sync_state.get("last_attempted_at"),
                "last_attempted_kind": sync_state.get("last_attempted_kind"),
                "last_success_at": sync_state.get("last_success_at"),
                "last_full_reconciliation_at": sync_state.get("last_full_reconciliation_at"),
                "last_error_class": sync_state.get("last_error_class") or "",
                "last_error_message": sync_state.get("last_error_message") or "",
                "last_remote_count": sync_state.get("last_remote_count"),
                "last_result_message": sync_state.get("last_result_message") or "",
                "currently_displayed_id": sync_state.get("currently_displayed_id"),
            },
            "cache": {
                "assets": counts["present"],
                "photos": counts["photos"],
                "videos": counts["videos"],
                "bytes": media_cache.usage_bytes(),
                "ceiling_bytes": media_cache.ceiling_bytes,
                "free_bytes": media_cache.filesystem_free_bytes(),
            },
            "display": _display_payload(svc),
            "system": _system_payload(svc),
        }

    @app.get("/api/presentation/next")
    def next_media(exclude: str = ""):
        svc: SettingsService = app.state.settings_service
        repo: MediaRepository = app.state.repository
        selector: SelectionEngine = app.state.selector
        selector.new_window_hours = svc.new_window_hours()
        exclude_ids = []
        for part in exclude.split(","):
            part = part.strip()
            if part.isdigit():
                exclude_ids.append(int(part))
        selection = selector.choose(
            repo.list_present(videos_enabled=svc.videos_enabled()),
            svc.presentation_mode(),
            exclude_ids=exclude_ids[-12:],
        )
        if selection is None:
            return JSONResponse({"media": None, "display": _display_payload(svc)})
        app.state.db.set_sync("currently_displayed_id", str(selection.media.id))
        return {
            "media": _media_payload(selection.media, selection.is_new),
            "reason": selection.reason,
            "display": _display_payload(svc),
        }

    @app.post("/api/presentation/played")
    def played(report: PlaybackReport):
        repo: MediaRepository = app.state.repository
        media = repo.get(report.media_id)
        if media is None:
            raise HTTPException(status_code=404, detail="unknown media")
        repo.record_display(
            media.id,
            duration_seconds=report.duration_seconds,
            completed=report.completed,
            audio_enabled=report.audio_enabled,
        )
        return {"ok": True}

    @app.get("/media/{media_id}")
    def media_file(media_id: int):
        repo: MediaRepository = app.state.repository
        cache_dir: Path = app.state.runtime.cache_dir
        media = repo.get(media_id)
        if media is None or not media.is_present:
            raise HTTPException(status_code=404, detail="media is not available")
        path = Path(media.local_path).resolve()
        try:
            path.relative_to(cache_dir.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="media path is not in the cache") from exc
        if not path.is_file():
            raise HTTPException(status_code=404, detail="cached file is missing")
        return FileResponse(path, media_type=media.mime_type or "application/octet-stream")

    @app.post("/api/admin/display")
    def update_display(payload: DisplayUpdate):
        svc: SettingsService = app.state.settings_service
        try:
            svc.update_display(payload.model_dump(exclude_none=True))
        except (SettingsError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        app.state.selector.new_window_hours = svc.new_window_hours()
        return {"ok": True, "display": _display_payload(svc)}

    @app.post("/api/admin/system")
    def update_system(payload: SystemUpdate):
        svc: SettingsService = app.state.settings_service
        try:
            svc.update_system(payload.model_dump(exclude_none=True))
        except (SettingsError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        app.state.cache.ceiling_bytes = svc.cache_ceiling_bytes()
        app.state.cache.reserved_bytes = svc.reserved_bytes()
        return {"ok": True, "system": _system_payload(svc)}

    @app.post("/api/admin/immich")
    def update_immich(payload: ImmichUpdate):
        svc: SettingsService = app.state.settings_service
        try:
            svc.update_immich(payload.model_dump(exclude_none=True))
        except SettingsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "ok": True,
            "immich_url": svc.immich_url(),
            "album_id": svc.album_id(),
            "api_key_configured": bool(svc.api_key()),
        }

    @app.post("/api/admin/immich/test")
    def test_immich():
        svc: SettingsService = app.state.settings_service
        try:
            client = ImmichClient(
                svc.immich_url(),
                svc.api_key(),
                timeout=svc.http_timeout_seconds(),
                download_timeout=svc.download_timeout_seconds(),
            )
            info = client.ping()
            albums = [
                {"id": item.get("id"), "name": item.get("albumName") or item.get("name"), "count": item.get("assetCount")}
                for item in client.list_albums()
            ]
        except ImmichError as exc:
            return JSONResponse(
                status_code=502,
                content={"ok": False, "error_class": exc.error_class, "message": str(exc)},
            )
        return {"ok": True, "server": info.get("version"), "albums": albums}

    @app.post("/api/admin/sync")
    def trigger_sync(kind: str = "incremental"):
        if kind not in {"incremental", "reconciliation"}:
            raise HTTPException(status_code=422, detail="unknown sync kind")
        if app.state.db.get_sync("sync_in_progress") == "1":
            raise HTTPException(status_code=409, detail="a sync is already running")
        try:
            result = app.state.scheduler.run_now(kind)
        except ImmichError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "ok": result.success,
            "kind": result.kind,
            "message": result.message,
            "added": result.added,
            "updated": result.updated,
            "removed": result.removed,
            "unchanged": result.unchanged,
            "skipped": result.skipped,
            "error_class": result.error_class,
        }

    @app.get("/api/admin/wifi")
    def wifi_networks():
        return {"networks": app.state.network.wifi_networks(), "nmcli": app.state.network.status().nmcli_available}

    @app.post("/api/admin/wifi")
    def connect_wifi(payload: WifiUpdate):
        ok, message = app.state.network.connect_wifi(payload.ssid, payload.password)
        return {"ok": ok, "message": message}

    @app.get("/api/admin/history")
    def history():
        return {"history": app.state.repository.recent_history()}

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.exception("unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    return app


def _display_payload(svc: SettingsService) -> dict:
    return {
        "presentation_mode": svc.presentation_mode(),
        "photo_duration_seconds": svc.photo_duration_seconds(),
        "show_overlay": svc.show_overlay(),
        "videos_enabled": svc.videos_enabled(),
        "transition": svc.transition(),
        "new_window_hours": svc.new_window_hours(),
    }


def _system_payload(svc: SettingsService) -> dict:
    return {
        "cache_ceiling_bytes": svc.cache_ceiling_bytes(),
        "reserved_bytes": svc.reserved_bytes(),
        "sync_incremental_minutes": svc.sync_incremental_minutes(),
        "sync_reconcile_hours": svc.sync_reconcile_hours(),
        "http_timeout_seconds": svc.http_timeout_seconds(),
        "download_timeout_seconds": svc.download_timeout_seconds(),
    }


def _media_payload(media, is_new: bool) -> dict:
    captured = parse_iso(media.captured_at)
    first_seen = parse_iso(media.first_seen_at)
    return {
        "id": media.id,
        "media_type": media.media_type,
        "mime_type": media.mime_type,
        "url": f"/media/{media.id}",
        "width": media.width,
        "height": media.height,
        "duration_seconds": media.duration_seconds,
        "is_new": is_new,
        "added_label": f"added {age_label(first_seen)}" if first_seen else "",
        "captured_label": captured.strftime("%-d %b %Y") if captured else "",
        "filename": media.filename,
    }
