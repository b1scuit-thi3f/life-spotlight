from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from photo_frame.config import RuntimeConfig
from photo_frame.helpers.db import Database
from photo_frame.helpers.models import RemoteAlbum, RemoteAsset
from photo_frame.helpers.timeutil import to_iso, utc_now
from photo_frame.services.cache import MediaCache
from photo_frame.services.immich import ImmichClient, ImmichError, parse_asset
from photo_frame.services.repository import MediaRepository
from photo_frame.services.sync import SyncService


class FakeImmich(ImmichClient):
    def __init__(self, album: RemoteAlbum, files: dict[str, bytes]):
        self.base_url = "https://immich.test"
        self._api_key = "test-key"
        self.album = album
        self.files = files
        self.downloads: list[str] = []
        self.fail = False

    def get_album(self, album_id: str, *, without_assets: bool = False) -> RemoteAlbum:
        if self.fail:
            raise ImmichError("boom", error_class="server_error", status_code=500)
        if without_assets:
            return RemoteAlbum(
                album_id=self.album.album_id,
                name=self.album.name,
                asset_count=len(self.album.assets),
                updated_at=self.album.updated_at,
                assets=[],
            )
        return self.album

    def download_original(self, asset_id: str, destination) -> None:
        self.downloads.append(asset_id)
        destination.write_bytes(self.files[asset_id])


def payload(immich_id: str) -> bytes:
    return f"jpeg-bytes-that-are-long-enough-{immich_id}".encode()


def asset(immich_id: str, *, updated: str | None = None, media_type: str = "photo") -> RemoteAsset:
    return RemoteAsset(
        immich_id=immich_id,
        media_type=media_type,  # type: ignore[arg-type]
        filename=f"{immich_id}.jpg",
        mime_type="image/jpeg" if media_type == "photo" else "video/mp4",
        captured_at=None,
        immich_created_at=utc_now() - timedelta(days=400),
        immich_updated_at=utc_now() if updated is None else None,
        file_size_bytes=128,
        checksum=immich_id,
    )


@pytest.fixture
def service(tmp_path: Path):
    settings = RuntimeConfig(data_dir=tmp_path / "data")
    settings.ensure_dirs()
    db = Database(settings.database_path)
    repo = MediaRepository(db)
    cache = MediaCache(settings.cache_dir, settings.tmp_dir, ceiling_bytes=10_000_000, reserved_bytes=0)
    sync = SyncService(db, repo, cache)
    yield db, repo, cache, sync
    db.close()


def test_incremental_adds_new_asset_and_sets_first_seen(service):
    db, repo, cache, sync = service
    before = utc_now()
    remote = asset("old-photo")
    remote.captured_at = utc_now() - timedelta(days=3000)
    client = FakeImmich(
        RemoteAlbum("album-1", "Family", 1, utc_now(), [remote]),
        {"old-photo": payload("old-photo")},
    )
    result = sync.incremental(client, "album-1")
    assert result.success
    assert result.added == 1
    stored = repo.get_by_immich_id("old-photo")
    assert stored is not None
    assert stored.is_present == 1
    assert Path(stored.local_path).read_bytes().startswith(b"jpeg")
    seen = stored.first_seen_at
    assert seen >= to_iso(before - timedelta(seconds=2))


def test_failed_sync_does_not_delete_cached_media(service):
    db, repo, cache, sync = service
    client = FakeImmich(
        RemoteAlbum("album-1", "Family", 1, utc_now(), [asset("keep-me")]),
        {"keep-me": payload("keep-me")},
    )
    assert sync.reconcile(client, "album-1").success
    client.fail = True
    client.album = RemoteAlbum("album-1", "Family", 0, utc_now(), [])
    failed = sync.reconcile(client, "album-1")
    assert failed.success is False
    assert failed.error_class == "server_error"
    stored = repo.get_by_immich_id("keep-me")
    assert stored is not None
    assert stored.is_present == 1
    assert Path(stored.local_path).is_file()


def test_reconciliation_removes_assets_absent_from_album(service):
    db, repo, cache, sync = service
    first = asset("stay")
    second = asset("leave")
    client = FakeImmich(
        RemoteAlbum("album-1", "Family", 2, utc_now(), [first, second]),
        {"stay": payload("stay"), "leave": payload("leave")},
    )
    sync.reconcile(client, "album-1")
    client.album = RemoteAlbum("album-1", "Family", 1, utc_now(), [first])
    result = sync.reconcile(client, "album-1")
    assert result.removed == 1
    assert repo.get_by_immich_id("leave") is None
    assert repo.get_by_immich_id("stay") is not None
    assert not (cache.cache_dir / "leave.jpg").exists()


def test_changed_checksum_redownloads(service):
    db, repo, cache, sync = service
    original = asset("changed")
    client = FakeImmich(
        RemoteAlbum("album-1", "Family", 1, utc_now(), [original]),
        {"changed": payload("changed-v1")},
    )
    sync.incremental(client, "album-1")
    updated = asset("changed")
    updated.checksum = "different"
    updated.immich_updated_at = utc_now() + timedelta(minutes=5)
    client.album = RemoteAlbum("album-1", "Family", 1, utc_now(), [updated])
    client.files["changed"] = payload("changed-v2")
    result = sync.incremental(client, "album-1")
    assert result.updated == 1
    assert Path(repo.get_by_immich_id("changed").local_path).read_bytes().endswith(b"v2")


def test_parse_asset_uses_id_not_filename():
    parsed = parse_asset(
        {
            "id": "abc-123",
            "type": "IMAGE",
            "originalFileName": "../etc/passwd",
            "originalMimeType": "image/jpeg",
            "createdAt": "2024-01-02T03:04:05.000Z",
            "updatedAt": "2024-02-02T03:04:05.000Z",
            "exifInfo": {"dateTimeOriginal": "2008-07-04T12:00:00.000Z"},
        }
    )
    assert parsed.immich_id == "abc-123"
    assert parsed.media_type == "photo"
    assert parsed.filename == "../etc/passwd"
    assert parsed.captured_at is not None
    assert parsed.captured_at.year == 2008


def test_http_error_mapping():
    response = httpx.Response(401, request=httpx.Request("GET", "https://immich.test/api/albums"))
    with pytest.raises(ImmichError) as caught:
        from photo_frame.services.immich import _raise_for_status

        _raise_for_status(response)
    assert caught.value.error_class == "authentication"
