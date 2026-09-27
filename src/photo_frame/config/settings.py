"""Validated configuration changes. The admin UI must go through this service.

Defaults are inserted into SQLite once. Later admin saves are never overwritten.
The API key is stored in the settings table and is never returned to the browser.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from photo_frame.helpers.db import PUBLIC_SETTING_KEYS, SETTING_DEFAULTS, Database
from photo_frame.helpers.models import PRESENTATION_MODES, TRANSITIONS

_ALBUM_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class SettingsError(ValueError):
    pass


class SettingsService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.seed_defaults()

    def seed_defaults(self) -> None:
        for key, value in SETTING_DEFAULTS.items():
            if self.db.get_setting(key) is None:
                self.db.set_setting(key, value)

    def public_view(self) -> dict[str, str]:
        stored = self.db.all_settings()
        view = {key: stored.get(key, SETTING_DEFAULTS.get(key, "")) for key in PUBLIC_SETTING_KEYS}
        view["api_key_configured"] = "1" if self.api_key() else "0"
        return view

    def get(self, key: str) -> str:
        value = self.db.get_setting(key)
        if value is None:
            return SETTING_DEFAULTS.get(key, "")
        return value

    def immich_url(self) -> str:
        return self.get("immich_url").strip().rstrip("/")

    def album_id(self) -> str:
        return self.get("album_id").strip()

    def album_name(self) -> str:
        return self.get("album_name")

    def api_key(self) -> str:
        return self.get("api_key").strip()

    def presentation_mode(self) -> str:
        value = self.get("presentation_mode")
        return value if value in PRESENTATION_MODES else "balanced"

    def photo_duration_seconds(self) -> int:
        return _int_setting(self.get("photo_duration_seconds"), 12, minimum=3, maximum=300)

    def new_window_hours(self) -> int:
        return _int_setting(self.get("new_window_hours"), 48, minimum=1, maximum=24 * 30)

    def show_overlay(self) -> bool:
        return _bool_setting(self.get("show_overlay"))

    def videos_enabled(self) -> bool:
        return _bool_setting(self.get("videos_enabled"))

    def transition(self) -> str:
        value = self.get("transition")
        return value if value in TRANSITIONS else "fade"

    def cache_ceiling_bytes(self) -> int:
        return _int_setting(
            self.get("cache_ceiling_bytes"),
            28_000_000_000,
            minimum=100_000_000,
            maximum=2_000_000_000_000,
        )

    def reserved_bytes(self) -> int:
        return _int_setting(
            self.get("reserved_bytes"),
            1_000_000_000,
            minimum=0,
            maximum=100_000_000_000,
        )

    def sync_incremental_minutes(self) -> int:
        return _int_setting(self.get("sync_incremental_minutes"), 60, minimum=5, maximum=24 * 60)

    def sync_reconcile_hours(self) -> int:
        return _int_setting(self.get("sync_reconcile_hours"), 24, minimum=1, maximum=24 * 14)

    def http_timeout_seconds(self) -> float:
        return float(_int_setting(self.get("http_timeout_seconds"), 60, minimum=5, maximum=600))

    def download_timeout_seconds(self) -> float:
        return float(_int_setting(self.get("download_timeout_seconds"), 300, minimum=30, maximum=3600))

    def update_display(self, payload: dict) -> None:
        if "presentation_mode" in payload:
            mode = str(payload["presentation_mode"])
            if mode not in PRESENTATION_MODES:
                raise SettingsError("unknown presentation mode")
            self.db.set_setting("presentation_mode", mode)
        if "photo_duration_seconds" in payload:
            seconds = int(payload["photo_duration_seconds"])
            if not 3 <= seconds <= 300:
                raise SettingsError("photo duration must be between 3 and 300 seconds")
            self.db.set_setting("photo_duration_seconds", str(seconds))
        if "show_overlay" in payload:
            self.db.set_setting("show_overlay", "1" if _as_bool(payload["show_overlay"]) else "0")
        if "videos_enabled" in payload:
            self.db.set_setting("videos_enabled", "1" if _as_bool(payload["videos_enabled"]) else "0")
        if "transition" in payload:
            transition = str(payload["transition"])
            if transition not in TRANSITIONS:
                raise SettingsError("unknown transition")
            self.db.set_setting("transition", transition)
        if "new_window_hours" in payload:
            hours = int(payload["new_window_hours"])
            if not 1 <= hours <= 24 * 30:
                raise SettingsError("new-media window must be between 1 and 720 hours")
            self.db.set_setting("new_window_hours", str(hours))

    def update_system(self, payload: dict) -> None:
        if "cache_ceiling_bytes" in payload:
            value = int(payload["cache_ceiling_bytes"])
            if not 100_000_000 <= value <= 2_000_000_000_000:
                raise SettingsError("cache ceiling is out of range")
            self.db.set_setting("cache_ceiling_bytes", str(value))
        if "reserved_bytes" in payload:
            value = int(payload["reserved_bytes"])
            if not 0 <= value <= 100_000_000_000:
                raise SettingsError("reserved space is out of range")
            self.db.set_setting("reserved_bytes", str(value))
        if "sync_incremental_minutes" in payload:
            value = int(payload["sync_incremental_minutes"])
            if not 5 <= value <= 24 * 60:
                raise SettingsError("incremental sync interval must be between 5 and 1440 minutes")
            self.db.set_setting("sync_incremental_minutes", str(value))
        if "sync_reconcile_hours" in payload:
            value = int(payload["sync_reconcile_hours"])
            if not 1 <= value <= 24 * 14:
                raise SettingsError("reconciliation interval must be between 1 and 336 hours")
            self.db.set_setting("sync_reconcile_hours", str(value))
        if "http_timeout_seconds" in payload:
            value = int(payload["http_timeout_seconds"])
            if not 5 <= value <= 600:
                raise SettingsError("HTTP timeout must be between 5 and 600 seconds")
            self.db.set_setting("http_timeout_seconds", str(value))
        if "download_timeout_seconds" in payload:
            value = int(payload["download_timeout_seconds"])
            if not 30 <= value <= 3600:
                raise SettingsError("download timeout must be between 30 and 3600 seconds")
            self.db.set_setting("download_timeout_seconds", str(value))

    def update_immich(self, payload: dict) -> None:
        if "immich_url" in payload and payload["immich_url"] is not None:
            url = str(payload["immich_url"]).strip().rstrip("/")
            if url:
                parsed = urlparse(url)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise SettingsError("Immich URL must be an http(s) URL")
            self.db.set_setting("immich_url", url)
        if "album_id" in payload and payload["album_id"] is not None:
            album_id = str(payload["album_id"]).strip()
            if album_id and not _ALBUM_ID.match(album_id):
                raise SettingsError("album id looks invalid")
            self.db.set_setting("album_id", album_id)
        if payload.get("api_key"):
            self.store_api_key(str(payload["api_key"]))

    def store_api_key(self, api_key: str) -> None:
        key = api_key.strip()
        if len(key) < 8:
            raise SettingsError("API key is too short")
        if any(char.isspace() for char in key):
            raise SettingsError("API key must not contain whitespace")
        self.db.set_setting("api_key", key)


def _int_setting(raw: str | None, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(float(raw)) if raw not in (None, "") else default
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)


def _bool_setting(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
