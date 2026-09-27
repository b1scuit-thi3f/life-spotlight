"""Background sync scheduling, independent of the presentation loop."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from photo_frame.config.settings import SettingsService
from photo_frame.helpers.timeutil import parse_iso, utc_now
from photo_frame.services.immich import ImmichClient, ImmichError
from photo_frame.services.sync import SyncService

logger = logging.getLogger(__name__)


class SyncScheduler:
    def __init__(self, sync: SyncService, settings_service: SettingsService) -> None:
        self.sync = sync
        self.settings_service = settings_service
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="photo-frame-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def run_now(self, kind: str = "incremental"):
        with self._lock:
            client = self._client()
            album_id = self.settings_service.album_id()
            if kind == "reconciliation":
                return self.sync.reconcile(client, album_id)
            return self.sync.incremental(client, album_id)

    def _loop(self) -> None:
        # A short delay lets the process finish binding before the first sync.
        if self._stop.wait(5):
            return
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                logger.exception("scheduler tick failed")
            self._stop.wait(30)

    def _tick(self) -> None:
        if not self.settings_service.immich_url() or not self.settings_service.api_key():
            return
        if not self.settings_service.album_id():
            return
        db = self.sync.db
        if db.get_sync("sync_in_progress") == "1":
            return
        now = utc_now()
        last_full = parse_iso(db.get_sync("last_full_reconciliation_at"))
        last_success = parse_iso(db.get_sync("last_success_at"))
        due_full = last_full is None or now - last_full >= timedelta(
            hours=self.settings_service.sync_reconcile_hours()
        )
        due_incremental = last_success is None or now - last_success >= timedelta(
            minutes=self.settings_service.sync_incremental_minutes()
        )
        if not due_full and not due_incremental:
            return
        kind = "reconciliation" if due_full else "incremental"
        logger.info("scheduler starting %s", kind)
        try:
            self.run_now(kind)
        except ImmichError as exc:
            logger.warning("scheduled sync did not start: %s", exc.error_class)

    def _client(self) -> ImmichClient:
        return ImmichClient(
            self.settings_service.immich_url(),
            self.settings_service.api_key(),
            timeout=self.settings_service.http_timeout_seconds(),
            download_timeout=self.settings_service.download_timeout_seconds(),
        )
