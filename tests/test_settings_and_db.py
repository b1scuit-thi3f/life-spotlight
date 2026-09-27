from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from photo_frame.app import create_app
from photo_frame.config import RuntimeConfig, SettingsError, SettingsService, runtime_from_args
from photo_frame.helpers.db import SETTING_DEFAULTS, Database


def test_schema_and_cascade(tmp_path: Path):
    db = Database(tmp_path / "frame.sqlite")
    db.execute(
        """
        INSERT INTO media (
            immich_id, media_type, local_path, first_seen_at, is_present
        ) VALUES ('id-1', 'photo', '/tmp/a.jpg', '2024-01-01T00:00:00+00:00', 1)
        """
    )
    media_id = db.execute("SELECT id FROM media").fetchone()["id"]
    db.execute(
        """
        INSERT INTO playback_history (media_id, displayed_at, duration_seconds, completed, audio_enabled)
        VALUES (?, '2024-01-02T00:00:00+00:00', 10, 1, 0)
        """,
        (media_id,),
    )
    db.execute("DELETE FROM media WHERE id = ?", (media_id,))
    remaining = db.execute("SELECT COUNT(*) AS n FROM playback_history").fetchone()["n"]
    assert remaining == 0
    with pytest.raises(Exception):
        db.execute(
            """
            INSERT INTO media (immich_id, media_type, local_path, first_seen_at)
            VALUES ('id-2', 'audio', '/tmp/b', '2024-01-01T00:00:00+00:00')
            """
        )
    db.close()


def test_defaults_are_seeded_and_admin_values_win(tmp_path: Path):
    runtime = RuntimeConfig(data_dir=tmp_path / "data")
    runtime.ensure_dirs()
    db = Database(runtime.database_path)
    service = SettingsService(db)
    assert service.presentation_mode() == "balanced"
    assert service.photo_duration_seconds() == 12
    assert db.get_setting("presentation_mode") == SETTING_DEFAULTS["presentation_mode"]
    service.update_display({"presentation_mode": "now", "photo_duration_seconds": 9})
    again = SettingsService(db)
    assert again.presentation_mode() == "now"
    assert again.photo_duration_seconds() == 9
    db.close()


def test_api_key_is_stored_but_not_returned(tmp_path: Path):
    runtime = RuntimeConfig(data_dir=tmp_path / "data")
    runtime.ensure_dirs()
    db = Database(runtime.database_path)
    service = SettingsService(db)
    service.store_api_key("super-secret-key")
    assert service.api_key() == "super-secret-key"
    assert "super-secret-key" not in service.public_view().values()
    assert "api_key" not in service.public_view()
    with pytest.raises(SettingsError):
        service.update_immich({"immich_url": "not a url"})
    with pytest.raises(SettingsError):
        service.update_display({"presentation_mode": "moods"})
    db.close()


def test_cli_parses_process_flags_only():
    runtime = runtime_from_args(
        ["--host", "127.0.0.1", "--port", "9000", "--data-dir", "/tmp/frame", "--hostname", "lounge", "--log-level", "DEBUG"]
    )
    assert runtime.host == "127.0.0.1"
    assert runtime.port == 9000
    assert runtime.hostname == "lounge"
    assert runtime.log_level == "DEBUG"
    assert runtime.database_path == Path("/tmp/frame/photo_frame.sqlite")


def test_presentation_and_admin_smoke(tmp_path: Path):
    runtime = RuntimeConfig(data_dir=tmp_path / "data", host="127.0.0.1", port=8080)
    runtime.ensure_dirs()
    app = create_app(runtime)
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        page = client.get("/")
        assert page.status_code == 200
        assert "Photo Frame" in page.text
        admin = client.get("/admin")
        assert admin.status_code == 200
        status = client.get("/api/status").json()
        assert status["immich"]["api_key_configured"] is False
        assert "api_key" not in status["immich"] or status["immich"].get("api_key") in (None, "")
        saved = client.post(
            "/api/admin/display",
            json={"presentation_mode": "now", "photo_duration_seconds": 9, "show_overlay": False},
        )
        assert saved.status_code == 200
        status = client.get("/api/status").json()
        assert status["display"]["presentation_mode"] == "now"
        assert status["system"]["sync_incremental_minutes"] == 60
        assert "api_key" not in status["immich"]
        tuned = client.post("/api/admin/system", json={"sync_incremental_minutes": 15})
        assert tuned.status_code == 200
        assert client.get("/api/status").json()["system"]["sync_incremental_minutes"] == 15
        nxt = client.get("/api/presentation/next")
        assert nxt.status_code == 200
        assert nxt.json()["media"] is None
        missing = client.get("/media/1")
        assert missing.status_code == 404
