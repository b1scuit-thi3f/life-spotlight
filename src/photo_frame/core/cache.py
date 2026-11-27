"""Local media files. Downloads are promoted only after validation."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from photo_frame.models.immich import RemoteAsset


class CacheError(Exception):
    """A local file failed validation or could not be stored."""


class MediaCache:
    def __init__(self, cacheDir: Path, tmpDir: Path, ceilingBytes: int, reservedBytes: int) -> None:
        self.cacheDir = cacheDir
        self.tmpDir = tmpDir
        self.ceilingBytes = ceilingBytes
        self.reservedBytes = reservedBytes
        self.cacheDir.mkdir(parents=True, exist_ok=True)
        self.tmpDir.mkdir(parents=True, exist_ok=True)

    def pathFor(self, asset: RemoteAsset) -> Path:
        """Build a cache path from the remote id, never from a remote filename."""
        safeId = "".join(ch for ch in asset.immichId if ch.isalnum() or ch in "-_")
        if not safeId:
            raise CacheError("asset id is empty")
        return self.cacheDir / f"{safeId}{extensionFor(asset)}"

    def temporaryPath(self, asset: RemoteAsset) -> Path:
        safeId = "".join(ch for ch in asset.immichId if ch.isalnum() or ch in "-_")
        return self.tmpDir / f"{safeId}.partial"

    def promote(self, temporary: Path, destination: Path, *, minBytes: int = 32) -> tuple[int, str]:
        if not temporary.is_file():
            raise CacheError("download did not produce a file")
        size = temporary.stat().st_size
        if size < minBytes:
            temporary.unlink(missing_ok=True)
            raise CacheError(f"downloaded file is too small ({size} bytes)")
        digest = hashlib.sha256()
        with temporary.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest = digest.hexdigest()
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.with_suffix(destination.suffix + ".promoting")
        shutil.move(str(temporary), staging)
        os.replace(staging, destination)
        return size, digest

    def delete(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            cacheRoot = self.cacheDir.resolve()
        except OSError as exc:
            raise CacheError("could not resolve cache path") from exc
        if cacheRoot not in resolved.parents and resolved != cacheRoot:
            raise CacheError("refusing to delete a path outside the cache")
        path.unlink(missing_ok=True)

    def usageBytes(self) -> int:
        total = 0
        if not self.cacheDir.exists():
            return 0
        for item in self.cacheDir.iterdir():
            if item.is_file():
                total += item.stat().st_size
        return total

    def filesystemFreeBytes(self) -> int | None:
        try:
            usage = shutil.disk_usage(self.cacheDir)
        except OSError:
            return None
        return int(usage.free)

    def hasRoom(self, incomingBytes: int | None) -> bool:
        used = self.usageBytes()
        incoming = incomingBytes or 0
        if used + incoming > self.ceilingBytes:
            return False
        free = self.filesystemFreeBytes()
        if free is None:
            return True
        return free - incoming > self.reservedBytes


def extensionFor(asset: RemoteAsset) -> str:
    mime = (asset.mimeType or "").lower()
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
    return ".mp4" if asset.mediaType == "video" else ".jpg"
