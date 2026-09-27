from __future__ import annotations

from pathlib import Path

import pytest

from photo_frame.helpers.models import RemoteAsset
from photo_frame.services.cache import CacheError, MediaCache


def test_paths_ignore_hostile_filenames(tmp_path: Path):
    cache = MediaCache(tmp_path / "cache", tmp_path / "tmp", ceiling_bytes=1000, reserved_bytes=0)
    asset = RemoteAsset(
        immich_id="abc-123",
        media_type="photo",
        filename="../../etc/passwd",
        mime_type="image/png",
    )
    path = cache.path_for(asset)
    assert path.parent == cache.cache_dir
    assert path.name == "abc-123.png"


def test_promote_rejects_tiny_files_and_writes_atomically(tmp_path: Path):
    cache = MediaCache(tmp_path / "cache", tmp_path / "tmp", ceiling_bytes=1000, reserved_bytes=0)
    asset = RemoteAsset(immich_id="file1", media_type="photo", mime_type="image/jpeg")
    temporary = cache.temporary_path(asset)
    temporary.write_bytes(b"nope")
    with pytest.raises(CacheError):
        cache.promote(temporary, cache.path_for(asset))
    temporary.write_bytes(b"x" * 64)
    size, digest = cache.promote(temporary, cache.path_for(asset))
    assert size == 64
    assert len(digest) == 64
    assert cache.path_for(asset).is_file()
    assert not temporary.exists()


def test_delete_refuses_paths_outside_cache(tmp_path: Path):
    cache = MediaCache(tmp_path / "cache", tmp_path / "tmp", ceiling_bytes=1000, reserved_bytes=0)
    outside = tmp_path / "secret.txt"
    outside.write_text("keep")
    with pytest.raises(CacheError):
        cache.delete(outside)
    assert outside.exists()
