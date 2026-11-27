"""Wire the process and mount the HTTP routes. Work lives in photo_frame.core."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.staticfiles import StaticFiles as StarletteStaticFiles

from photo_frame import __version__
from photo_frame.api.routes.admin import router as adminRouter
from photo_frame.api.routes.pages import router as pagesRouter
from photo_frame.api.routes.presentation import router as presentationRouter
from photo_frame.api.routes.status import router as statusRouter
from photo_frame.config import RuntimeConfig, configureLogging
from photo_frame.core.cache import MediaCache
from photo_frame.core.database import Database
from photo_frame.core.network import NetworkAdapter
from photo_frame.core.repository import MediaRepository
from photo_frame.core.scheduler import SyncScheduler
from photo_frame.core.selection import SelectionEngine
from photo_frame.core.settings import SettingsService
from photo_frame.core.sync import SyncService

logger = logging.getLogger(__name__)

webDir = Path(__file__).resolve().parent.parent / "web"
templates = Jinja2Templates(directory=str(webDir / "templates"))


class NoCacheStaticFiles(StarletteStaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def createApp(runtime: RuntimeConfig | None = None) -> FastAPI:
    runtime = runtime or RuntimeConfig()
    configureLogging(runtime.logLevel)
    runtime.ensureDirs()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.startedAt = datetime.now(timezone.utc)
        app.state.scheduler.start()
        logger.info("photo frame %s listening; data dir %s", __version__, runtime.dataDir)
        yield
        app.state.scheduler.stop()
        app.state.db.close()

    app = FastAPI(title="Photo Frame", version=__version__, lifespan=lifespan)
    db = Database(runtime.databasePath)
    settingsService = SettingsService(db)
    repository = MediaRepository(db)
    cache = MediaCache(
        runtime.cacheDir,
        runtime.tmpDir,
        ceilingBytes=settingsService.cacheCeilingBytes(),
        reservedBytes=settingsService.reservedBytes(),
    )
    sync = SyncService(db, repository, cache)
    scheduler = SyncScheduler(sync, settingsService)
    network = NetworkAdapter(runtime.hostname)

    app.state.runtime = runtime
    app.state.db = db
    app.state.settingsService = settingsService
    app.state.repository = repository
    app.state.cache = cache
    app.state.sync = sync
    app.state.scheduler = scheduler
    app.state.network = network
    app.state.selector = SelectionEngine(newWindowHours=settingsService.newWindowHours())
    app.state.templates = templates

    app.mount("/static", NoCacheStaticFiles(directory=str(webDir / "static")), name="static")
    app.include_router(pagesRouter)
    app.include_router(statusRouter)
    app.include_router(presentationRouter)
    app.include_router(adminRouter)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.exception("unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    return app
