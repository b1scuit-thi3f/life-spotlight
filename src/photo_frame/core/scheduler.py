"""Background sync scheduling, independent of the presentation loop."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from photo_frame.core.immich import ImmichClient, ImmichError
from photo_frame.core.settings import SettingsService
from photo_frame.core.sync import SyncService
from photo_frame.core.time import parseIso

logger = logging.getLogger(__name__)


class SyncScheduler:
    def __init__(self, sync: SyncService, settingsService: SettingsService) -> None:
        self.sync = sync
        self.settingsService = settingsService
        self.stopEvent = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.loop, name="photo-frame-sync", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stopEvent.set()

    def runNow(self, kind: str = "incremental"):
        with self.lock:
            client = self.client()
            albumId = self.settingsService.albumId()
            if kind == "reconciliation":
                return self.sync.reconcile(client, albumId)
            return self.sync.incremental(client, albumId)

    def loop(self) -> None:
        if self.stopEvent.wait(5):
            return
        while not self.stopEvent.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("scheduler tick failed")
            self.stopEvent.wait(30)

    def tick(self) -> None:
        if not self.settingsService.immichUrl() or not self.settingsService.apiKey():
            return
        if not self.settingsService.albumId():
            return
        db = self.sync.db
        if db.getSync("sync_in_progress") == "1":
            return
        now = datetime.now(timezone.utc)
        lastFull = parseIso(db.getSync("last_full_reconciliation_at"))
        lastSuccess = parseIso(db.getSync("last_success_at"))
        dueFull = lastFull is None or now - lastFull >= timedelta(hours=self.settingsService.syncReconcileHours())
        dueIncremental = lastSuccess is None or now - lastSuccess >= timedelta(
            minutes=self.settingsService.syncIncrementalMinutes()
        )
        if not dueFull and not dueIncremental:
            return
        kind = "reconciliation" if dueFull else "incremental"
        logger.info("scheduler starting %s", kind)
        try:
            self.runNow(kind)
        except ImmichError as exc:
            logger.warning("scheduled sync did not start: %s", exc.errorClass)

    def client(self) -> ImmichClient:
        return ImmichClient(
            self.settingsService.immichUrl(),
            self.settingsService.apiKey(),
            timeout=self.settingsService.httpTimeoutSeconds(),
            downloadTimeout=self.settingsService.downloadTimeoutSeconds(),
        )
