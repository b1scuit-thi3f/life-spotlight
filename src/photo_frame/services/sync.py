"""Hourly incremental sync and daily full reconciliation.

Destructive cache changes happen only after a successful full remote read.
A failed or partial read leaves the last known good cache untouched.
"""

from __future__ import annotations

import logging
from pathlib import Path

from photo_frame.helpers.db import Database
from photo_frame.helpers.models import RemoteAlbum, RemoteAsset, SyncResult
from photo_frame.helpers.timeutil import parse_iso, to_iso, utc_now
from photo_frame.services.cache import CacheError, MediaCache
from photo_frame.services.immich import ImmichClient, ImmichError, change_marker
from photo_frame.services.repository import MediaRepository

logger = logging.getLogger(__name__)


class SyncService:
    def __init__(self, db: Database, repository: MediaRepository, cache: MediaCache) -> None:
        self.db = db
        self.repository = repository
        self.cache = cache

    def incremental(self, client: ImmichClient, album_id: str) -> SyncResult:
        return self._run("incremental", client, album_id, allow_deletes=False, cheap_skip=True)

    def reconcile(self, client: ImmichClient, album_id: str) -> SyncResult:
        return self._run("reconciliation", client, album_id, allow_deletes=True, cheap_skip=False)

    def _run(
        self,
        kind: str,
        client: ImmichClient,
        album_id: str,
        *,
        allow_deletes: bool,
        cheap_skip: bool,
    ) -> SyncResult:
        started = utc_now()
        self.db.set_sync("last_attempted_at", to_iso(started))
        self.db.set_sync("last_attempted_kind", kind)
        self.db.set_sync("sync_in_progress", "1")
        result = SyncResult(kind=kind, success=False, started_at=to_iso(started), finished_at=to_iso(started))
        try:
            if not album_id:
                raise ImmichError("no album is configured", error_class="not_configured")
            summary = client.get_album(album_id, without_assets=True)
            previous_marker = self.db.get_sync("remote_change_marker") or ""
            if cheap_skip and previous_marker:
                # The summary endpoint may omit assets. Fetch the full album
                # only when the cheap marker looks different, or when we have
                # never stored one. Count + album updatedAt are hints only.
                hint = f"{summary.asset_count}|{summary.updated_at.isoformat() if summary.updated_at else ''}"
                stored_hint = previous_marker.split("|", 2)[0] + "|" + (
                    previous_marker.split("|", 2)[1] if "|" in previous_marker else ""
                )
                if hint == stored_hint and self.repository.counts()["present"] > 0:
                    result.success = True
                    result.remote_count = summary.asset_count
                    result.message = "no remote change detected"
                    result.unchanged = summary.asset_count
                    self._finish_success(result, summary, marker=previous_marker)
                    return result

            album = client.get_album(album_id, without_assets=False)
            self.db.set_setting("album_name", album.name)
            marker = change_marker(album)
            added, updated, unchanged, skipped = self._apply_remote(client, album)
            removed = 0
            if allow_deletes:
                removed = self._remove_absent(album)
            result.success = True
            result.added = added
            result.updated = updated
            result.removed = removed
            result.unchanged = unchanged
            result.skipped = skipped
            result.remote_count = len(album.assets) or album.asset_count
            result.message = (
                f"added {added}, updated {updated}, removed {removed}, unchanged {unchanged}"
            )
            self._finish_success(result, album, marker=marker)
            return result
        except ImmichError as exc:
            logger.warning("sync %s failed: %s (%s)", kind, exc, exc.error_class)
            return self._finish_failure(result, exc.error_class, str(exc))
        except CacheError as exc:
            logger.warning("sync %s cache error: %s", kind, exc)
            return self._finish_failure(result, "cache", str(exc))
        except Exception as exc:  # noqa: BLE001 - last line of defence for the scheduler
            logger.exception("sync %s unexpected failure", kind)
            return self._finish_failure(result, "unexpected", exc.__class__.__name__)
        finally:
            self.db.set_sync("sync_in_progress", "0")

    def _apply_remote(self, client: ImmichClient, album: RemoteAlbum) -> tuple[int, int, int, int]:
        added = updated = unchanged = skipped = 0
        now = to_iso(utc_now())
        for asset in album.assets:
            existing = self.repository.get_by_immich_id(asset.immich_id)
            if existing is None:
                if not self.cache.has_room(asset.file_size_bytes):
                    skipped += 1
                    logger.warning("skipping %s; cache ceiling or reserved space reached", asset.immich_id)
                    continue
                local_path = self.cache.path_for(asset)
                media_id = self.repository.insert_pending(asset, str(local_path), now)
                try:
                    size, digest = self._download(client, asset, local_path)
                except Exception:
                    self.repository.delete_media(media_id)
                    raise
                self.repository.mark_present(media_id, file_size_bytes=size, checksum=digest)
                added += 1
                continue

            remote_updated = asset.immich_updated_at
            local_updated = parse_iso(existing.immich_updated_at)
            checksum_changed = bool(asset.checksum and existing.checksum and asset.checksum != existing.checksum)
            metadata_changed = remote_updated is not None and (
                local_updated is None or remote_updated > local_updated
            )
            missing_file = existing.is_present == 0 or not Path(existing.local_path).is_file()
            if metadata_changed or checksum_changed or missing_file:
                if not self.cache.has_room(asset.file_size_bytes) and missing_file:
                    skipped += 1
                    continue
                self.repository.update_metadata(existing.id, asset)
                if checksum_changed or missing_file or metadata_changed:
                    # Refresh the file when the remote record moved. A metadata-only
                    # change still re-downloads so a replaced original cannot linger.
                    destination = Path(existing.local_path)
                    size, digest = self._download(client, asset, destination)
                    self.repository.mark_present(existing.id, file_size_bytes=size, checksum=digest)
                updated += 1
            else:
                unchanged += 1
        return added, updated, unchanged, skipped

    def _download(self, client: ImmichClient, asset: RemoteAsset, destination: Path) -> tuple[int, str]:
        temporary = self.cache.temporary_path(asset)
        temporary.unlink(missing_ok=True)
        try:
            client.download_original(asset.immich_id, temporary)
            return self.cache.promote(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _remove_absent(self, album: RemoteAlbum) -> int:
        remote_ids = {asset.immich_id for asset in album.assets}
        removed = 0
        for local in self.repository.list_present():
            if local.immich_id in remote_ids:
                continue
            self.repository.mark_absent(local.id)
            self.cache.delete(Path(local.local_path))
            # v1 retention: history for deleted media is removed with the row.
            self.repository.delete_media(local.id)
            removed += 1
        return removed

    def _finish_success(self, result: SyncResult, album: RemoteAlbum, *, marker: str) -> None:
        finished = utc_now()
        result.finished_at = to_iso(finished)
        self.db.set_sync("last_success_at", result.finished_at)
        self.db.set_sync("last_remote_count", str(result.remote_count or album.asset_count))
        self.db.set_sync("last_result_message", result.message)
        self.db.set_sync("last_error_class", "")
        self.db.set_sync("last_error_message", "")
        self.db.set_sync("remote_change_marker", marker)
        if result.kind == "reconciliation":
            self.db.set_sync("last_full_reconciliation_at", result.finished_at)
        logger.info("sync %s ok: %s", result.kind, result.message)

    def _finish_failure(self, result: SyncResult, error_class: str, message: str) -> SyncResult:
        result.success = False
        result.finished_at = to_iso(utc_now())
        result.error_class = error_class
        result.message = message
        self.db.set_sync("last_error_class", error_class)
        self.db.set_sync("last_error_message", message[:500])
        self.db.set_sync("last_result_message", f"failed: {error_class}")
        return result
