"""Validated configuration changes. The admin UI must go through this service.

Defaults are inserted into SQLite once. Later admin saves are never overwritten.
The API key is stored in the settings table and is never returned to the browser.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from photo_frame.core.database import settingDefaults, Database
from photo_frame.models.display import presentationModes, transitions


class SettingsError(ValueError):
    pass


class SettingsService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.seedDefaults()

    def seedDefaults(self) -> None:
        for key, value in settingDefaults.items():
            if self.db.getSetting(key) is None:
                self.db.setSetting(key, value)

    def publicView(self) -> dict[str, str]:
        stored = self.db.allSettings()
        view = {
            key: stored.get(key, settingDefaults.get(key, ""))
            for key in settingDefaults
            if key != "api_key"
        }
        view["apiKeyConfigured"] = "1" if self.apiKey() else "0"
        return view

    def get(self, key: str) -> str:
        value = self.db.getSetting(key)
        if value is None:
            return settingDefaults.get(key, "")
        return value

    def immichUrl(self) -> str:
        return self.get("immich_url").strip().rstrip("/")

    def albumId(self) -> str:
        return self.get("album_id").strip()

    def albumName(self) -> str:
        return self.get("album_name")

    def apiKey(self) -> str:
        return self.get("api_key").strip()

    def presentationMode(self) -> str:
        value = self.get("presentation_mode")
        return value if value in presentationModes else "balanced"

    def photoDurationSeconds(self) -> int:
        return intSetting(self.get("photo_duration_seconds"), 12, minimum=3, maximum=300)

    def newWindowHours(self) -> int:
        return intSetting(self.get("new_window_hours"), 48, minimum=1, maximum=24 * 30)

    def showOverlay(self) -> bool:
        return self.get("show_overlay").strip().lower() in {"1", "true", "yes", "on"}

    def videosEnabled(self) -> bool:
        return self.get("videos_enabled").strip().lower() in {"1", "true", "yes", "on"}

    def transition(self) -> str:
        value = self.get("transition")
        return value if value in transitions else "fade"

    def cacheCeilingBytes(self) -> int:
        return intSetting(self.get("cache_ceiling_bytes"), 28_000_000_000, minimum=100_000_000, maximum=2_000_000_000_000)

    def reservedBytes(self) -> int:
        return intSetting(self.get("reserved_bytes"), 1_000_000_000, minimum=0, maximum=100_000_000_000)

    def syncIncrementalMinutes(self) -> int:
        return intSetting(self.get("sync_incremental_minutes"), 60, minimum=5, maximum=24 * 60)

    def syncReconcileHours(self) -> int:
        return intSetting(self.get("sync_reconcile_hours"), 24, minimum=1, maximum=24 * 14)

    def httpTimeoutSeconds(self) -> float:
        return float(intSetting(self.get("http_timeout_seconds"), 60, minimum=5, maximum=600))

    def downloadTimeoutSeconds(self) -> float:
        return float(intSetting(self.get("download_timeout_seconds"), 300, minimum=30, maximum=3600))

    def updateDisplay(self, payload: dict) -> None:
        if "presentationMode" in payload:
            mode = str(payload["presentationMode"])
            if mode not in presentationModes:
                raise SettingsError("unknown presentation mode")
            self.db.setSetting("presentation_mode", mode)
        if "photoDurationSeconds" in payload:
            seconds = int(payload["photoDurationSeconds"])
            if not 3 <= seconds <= 300:
                raise SettingsError("photo duration must be between 3 and 300 seconds")
            self.db.setSetting("photo_duration_seconds", str(seconds))
        if "showOverlay" in payload:
            shown = payload["showOverlay"]
            shown = shown if isinstance(shown, bool) else str(shown).strip().lower() in {"1", "true", "yes", "on"}
            self.db.setSetting("show_overlay", "1" if shown else "0")
        if "videosEnabled" in payload:
            enabled = payload["videosEnabled"]
            enabled = enabled if isinstance(enabled, bool) else str(enabled).strip().lower() in {"1", "true", "yes", "on"}
            self.db.setSetting("videos_enabled", "1" if enabled else "0")
        if "transition" in payload:
            transition = str(payload["transition"])
            if transition not in transitions:
                raise SettingsError("unknown transition")
            self.db.setSetting("transition", transition)
        if "newWindowHours" in payload:
            hours = int(payload["newWindowHours"])
            if not 1 <= hours <= 24 * 30:
                raise SettingsError("new-media window must be between 1 and 720 hours")
            self.db.setSetting("new_window_hours", str(hours))

    def updateSystem(self, payload: dict) -> None:
        if "cacheCeilingBytes" in payload:
            value = int(payload["cacheCeilingBytes"])
            if not 100_000_000 <= value <= 2_000_000_000_000:
                raise SettingsError("cache ceiling is out of range")
            self.db.setSetting("cache_ceiling_bytes", str(value))
        if "reservedBytes" in payload:
            value = int(payload["reservedBytes"])
            if not 0 <= value <= 100_000_000_000:
                raise SettingsError("reserved space is out of range")
            self.db.setSetting("reserved_bytes", str(value))
        if "syncIncrementalMinutes" in payload:
            value = int(payload["syncIncrementalMinutes"])
            if not 5 <= value <= 24 * 60:
                raise SettingsError("incremental sync interval must be between 5 and 1440 minutes")
            self.db.setSetting("sync_incremental_minutes", str(value))
        if "syncReconcileHours" in payload:
            value = int(payload["syncReconcileHours"])
            if not 1 <= value <= 24 * 14:
                raise SettingsError("reconciliation interval must be between 1 and 336 hours")
            self.db.setSetting("sync_reconcile_hours", str(value))
        if "httpTimeoutSeconds" in payload:
            value = int(payload["httpTimeoutSeconds"])
            if not 5 <= value <= 600:
                raise SettingsError("HTTP timeout must be between 5 and 600 seconds")
            self.db.setSetting("http_timeout_seconds", str(value))
        if "downloadTimeoutSeconds" in payload:
            value = int(payload["downloadTimeoutSeconds"])
            if not 30 <= value <= 3600:
                raise SettingsError("download timeout must be between 30 and 3600 seconds")
            self.db.setSetting("download_timeout_seconds", str(value))

    def updateImmich(self, payload: dict) -> None:
        if "immichUrl" in payload and payload["immichUrl"] is not None:
            url = str(payload["immichUrl"]).strip().rstrip("/")
            if url:
                parsed = urlparse(url)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise SettingsError("Immich URL must be an http(s) URL")
            self.db.setSetting("immich_url", url)
        if "albumId" in payload and payload["albumId"] is not None:
            albumId = str(payload["albumId"]).strip()
            if albumId and not re.fullmatch(r"[A-Za-z0-9-]{8,64}", albumId):
                raise SettingsError("album id looks invalid")
            self.db.setSetting("album_id", albumId)
        if payload.get("apiKey"):
            self.storeApiKey(str(payload["apiKey"]))

    def storeApiKey(self, apiKey: str) -> None:
        key = apiKey.strip()
        if len(key) < 8:
            raise SettingsError("API key is too short")
        if any(char.isspace() for char in key):
            raise SettingsError("API key must not contain whitespace")
        self.db.setSetting("api_key", key)


def intSetting(raw: str | None, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(float(raw)) if raw not in (None, "") else default
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)
