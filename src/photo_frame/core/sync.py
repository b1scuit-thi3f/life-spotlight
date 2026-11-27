"""Hourly incremental sync and daily full reconciliation.

Destructive cache changes happen only after a successful full remote read.
A failed or partial read leaves the last known good cache untouched.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from photo_frame.core.cache import CacheError, MediaCache
from photo_frame.core.database import Database
from photo_frame.core.immich import ImmichClient, ImmichError
from photo_frame.core.repository import MediaRepository
from photo_frame.core.time import parseIso, toIso
from photo_frame.models.immich import RemoteAlbum, RemoteAsset
from photo_frame.models.sync import SyncResult

logger = logging.getLogger(__name__)


class SyncService:
    def __init__(self, db: Database, repository: MediaRepository, cache: MediaCache) -> None:
        self.db = db
        self.repository = repository
        self.cache = cache

    def incremental(self, client: ImmichClient, albumId: str) -> SyncResult:
        return self.run("incremental", client, albumId, allowDeletes=False, cheapSkip=True)

    def reconcile(self, client: ImmichClient, albumId: str) -> SyncResult:
        return self.run("reconciliation", client, albumId, allowDeletes=True, cheapSkip=False)

    def run(
        self,
        kind: str,
        client: ImmichClient,
        albumId: str,
        *,
        allowDeletes: bool,
        cheapSkip: bool,
    ) -> SyncResult:
        started = datetime.now(timezone.utc)
        self.db.setSync("last_attempted_at", toIso(started))
        self.db.setSync("last_attempted_kind", kind)
        self.db.setSync("sync_in_progress", "1")
        result = SyncResult(kind=kind, success=False, startedAt=toIso(started), finishedAt=toIso(started))
        try:
            if not albumId:
                raise ImmichError("no album is configured", errorClass="not_configured")
            summary = client.getAlbum(albumId, withoutAssets=True)
            previousMarker = self.db.getSync("remote_change_marker") or ""
            if cheapSkip and previousMarker:
                hint = f"{summary.assetCount}|{summary.updatedAt.isoformat() if summary.updatedAt else ''}"
                storedHint = previousMarker.split("|", 2)[0] + "|" + (
                    previousMarker.split("|", 2)[1] if "|" in previousMarker else ""
                )
                if hint == storedHint and self.repository.counts()["present"] > 0:
                    result.success = True
                    result.remoteCount = summary.assetCount
                    result.message = "no remote change detected"
                    result.unchanged = summary.assetCount
                    self.finishSuccess(result, summary, marker=previousMarker)
                    return result

            album = client.getAlbum(albumId, withoutAssets=False)
            self.db.setSetting("album_name", album.name)
            newest = ""
            for asset in album.assets:
                stamp = asset.immichUpdatedAt.isoformat() if asset.immichUpdatedAt else ""
                if stamp > newest:
                    newest = stamp
            updatedAt = album.updatedAt.isoformat() if album.updatedAt else ""
            marker = f"{album.assetCount}|{updatedAt}|{newest}|{len(album.assets)}"
            added, updated, unchanged, skipped = self.applyRemote(client, album)
            removed = self.removeAbsent(album) if allowDeletes else 0
            result.success = True
            result.added = added
            result.updated = updated
            result.removed = removed
            result.unchanged = unchanged
            result.skipped = skipped
            result.remoteCount = len(album.assets) or album.assetCount
            result.message = f"added {added}, updated {updated}, removed {removed}, unchanged {unchanged}"
            self.finishSuccess(result, album, marker=marker)
            return result
        except ImmichError as exc:
            logger.warning("sync %s failed: %s (%s)", kind, exc, exc.errorClass)
            return self.finishFailure(result, exc.errorClass, str(exc))
        except CacheError as exc:
            logger.warning("sync %s cache error: %s", kind, exc)
            return self.finishFailure(result, "cache", str(exc))
        except Exception as exc:  # noqa: BLE001 - last line of defence for the scheduler
            logger.exception("sync %s unexpected failure", kind)
            return self.finishFailure(result, "unexpected", exc.__class__.__name__)
        finally:
            self.db.setSync("sync_in_progress", "0")

    def applyRemote(self, client: ImmichClient, album: RemoteAlbum) -> tuple[int, int, int, int]:
        added = updated = unchanged = skipped = 0
        now = toIso(datetime.now(timezone.utc))
        for asset in album.assets:
            existing = self.repository.getByImmichId(asset.immichId)
            if existing is None:
                if not self.cache.hasRoom(asset.fileSizeBytes):
                    skipped += 1
                    logger.warning("skipping %s; cache ceiling or reserved space reached", asset.immichId)
                    continue
                localPath = self.cache.pathFor(asset)
                mediaId = self.repository.insertPending(asset, str(localPath), now)
                try:
                    size, digest = self.download(client, asset, localPath)
                except Exception:
                    self.repository.deleteMedia(mediaId)
                    raise
                self.repository.markPresent(mediaId, fileSizeBytes=size, checksum=digest)
                added += 1
                continue

            remoteUpdated = asset.immichUpdatedAt
            localUpdated = parseIso(existing.immichUpdatedAt)
            checksumChanged = bool(asset.checksum and existing.checksum and asset.checksum != existing.checksum)
            metadataChanged = remoteUpdated is not None and (localUpdated is None or remoteUpdated > localUpdated)
            missingFile = existing.isPresent == 0 or not Path(existing.localPath).is_file()
            if metadataChanged or checksumChanged or missingFile:
                if not self.cache.hasRoom(asset.fileSizeBytes) and missingFile:
                    skipped += 1
                    continue
                self.repository.updateMetadata(existing.id, asset)
                destination = Path(existing.localPath)
                size, digest = self.download(client, asset, destination)
                self.repository.markPresent(existing.id, fileSizeBytes=size, checksum=digest)
                updated += 1
            else:
                unchanged += 1
        return added, updated, unchanged, skipped

    def download(self, client: ImmichClient, asset: RemoteAsset, destination: Path) -> tuple[int, str]:
        temporary = self.cache.temporaryPath(asset)
        temporary.unlink(missing_ok=True)
        try:
            client.downloadOriginal(asset.immichId, temporary)
            return self.cache.promote(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def removeAbsent(self, album: RemoteAlbum) -> int:
        remoteIds = {asset.immichId for asset in album.assets}
        removed = 0
        for local in self.repository.listPresent():
            if local.immichId in remoteIds:
                continue
            self.repository.markAbsent(local.id)
            self.cache.delete(Path(local.localPath))
            self.repository.deleteMedia(local.id)
            removed += 1
        return removed

    def finishSuccess(self, result: SyncResult, album: RemoteAlbum, *, marker: str) -> None:
        finished = datetime.now(timezone.utc)
        result.finishedAt = toIso(finished)
        self.db.setSync("last_success_at", result.finishedAt)
        self.db.setSync("last_remote_count", str(result.remoteCount or album.assetCount))
        self.db.setSync("last_result_message", result.message)
        self.db.setSync("last_error_class", "")
        self.db.setSync("last_error_message", "")
        self.db.setSync("remote_change_marker", marker)
        if result.kind == "reconciliation":
            self.db.setSync("last_full_reconciliation_at", result.finishedAt)
        logger.info("sync %s ok: %s", result.kind, result.message)

    def finishFailure(self, result: SyncResult, errorClass: str, message: str) -> SyncResult:
        result.success = False
        result.finishedAt = toIso(datetime.now(timezone.utc))
        result.errorClass = errorClass
        result.message = message
        self.db.setSync("last_error_class", errorClass)
        self.db.setSync("last_error_message", message[:500])
        self.db.setSync("last_result_message", f"failed: {errorClass}")
        return result
