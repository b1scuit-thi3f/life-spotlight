"""Local media files. Downloads are promoted only after validation."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from photo_frame.helpers.models import RemoteAsset


class CacheError(Exception):
    """A local file failed validation or could not be stored."""


class MediaCache:
    def __init__(self, cache_dir: Path, tmp_dir: Path, ceiling_bytes: int, reserved_bytes: int) -> None:
        self.cache_dir = cache_dir
        self.tmp_dir = tmp_dir
        self.ceiling_bytes = ceiling_bytes
        self.reserved_bytes = reserved_bytes
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, asset: RemoteAsset) -> Path:
        """Build a cache path from the remote id, never from a remote filename."""
        safe_id = "".join(ch for ch in asset.immich_id if ch.isalnum() or ch in "-_")
        if not safe_id:
            raise CacheError("asset id is empty")
        extension = _extension(asset)
        return self.cache_dir / f"{safe_id}{extension}"

    def temporary_path(self, asset: RemoteAsset) -> Path:
        safe_id = "".join(ch for ch in asset.immich_id if ch.isalnum() or ch in "-_")
        return self.tmp_dir / f"{safe_id}.partial"

    def promote(self, temporary: Path, destination: Path, *, min_bytes: int = 32) -> tuple[int, str]:
        if not temporary.is_file():
            raise CacheError("download did not produce a file")
        size = temporary.stat().st_size
        if size < min_bytes:
            temporary.unlink(missing_ok=True)
            raise CacheError(f"downloaded file is too small ({size} bytes)")
        digest = _sha256(temporary)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.with_suffix(destination.suffix + ".promoting")
        shutil.move(str(temporary), staging)
        os.replace(staging, destination)
        return size, digest

    def delete(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            cache_root = self.cache_dir.resolve()
        except OSError as exc:
            raise CacheError("could not resolve cache path") from exc
        if cache_root not in resolved.parents and resolved != cache_root:
            raise CacheError("refusing to delete a path outside the cache")
        path.unlink(missing_ok=True)

    def usage_bytes(self) -> int:
        total = 0
        if not self.cache_dir.exists():
            return 0
        for item in self.cache_dir.iterdir():
            if item.is_file():
                total += item.stat().st_size
        return total

    def filesystem_free_bytes(self) -> int | None:
        try:
            usage = shutil.disk_usage(self.cache_dir)
        except OSError:
            return None
        return int(usage.free)

    def has_room(self, incoming_bytes: int | None) -> bool:
        used = self.usage_bytes()
        incoming = incoming_bytes or 0
        if used + incoming > self.ceiling_bytes:
            return False
        free = self.filesystem_free_bytes()
        if free is None:
            return True
        return free - incoming > self.reserved_bytes


def _extension(asset: RemoteAsset) -> str:
    mime = (asset.mime_type or "").lower()
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/heic": ".heic",
        "image/heif": ".heif",
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/webm": ".webm",
        "video/x-matroska": ".mkv",
    }
    if mime in mapping:
        return mapping[mime]
    name = asset.filename or ""
    suffix = Path(name).suffix.lower()
    if suffix and len(suffix) <= 8 and suffix.startswith(".") and suffix[1:].isalnum():
        return suffix
    return ".mp4" if asset.media_type == "video" else ".jpg"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
