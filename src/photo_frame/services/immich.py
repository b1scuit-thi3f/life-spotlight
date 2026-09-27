"""Small httpx wrapper around the Immich REST API.

The installed server version is discovered at runtime. Album membership is
read only from the configured album; the client does not walk the library.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from photo_frame.helpers.models import RemoteAlbum, RemoteAsset
from photo_frame.helpers.timeutil import parse_iso

logger = logging.getLogger(__name__)


class ImmichError(Exception):
    def __init__(self, message: str, *, error_class: str = "immich_error", status_code: int | None = None):
        super().__init__(message)
        self.error_class = error_class
        self.status_code = status_code


class ImmichClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 60.0,
        download_timeout: float = 300.0,
    ) -> None:
        if not base_url:
            raise ImmichError("Immich URL is not configured", error_class="not_configured")
        if not api_key:
            raise ImmichError("Immich API key is not configured", error_class="not_configured")
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._download_timeout = download_timeout

    def _client(self, timeout: float | None = None) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            headers={"x-api-key": self._api_key, "Accept": "application/json"},
            timeout=timeout or self._timeout,
            follow_redirects=True,
        )

    def ping(self) -> dict[str, Any]:
        with self._client() as client:
            version = self._get_json(client, "/api/server/version")
            about = {}
            try:
                about = self._get_json(client, "/api/server/about")
            except ImmichError:
                about = {}
            return {"version": version, "about": about}

    def list_albums(self) -> list[dict[str, Any]]:
        with self._client() as client:
            payload = self._get_json(client, "/api/albums")
        if isinstance(payload, list):
            return payload
        raise ImmichError("album list response was not a list", error_class="malformed_response")

    def get_album(self, album_id: str, *, without_assets: bool = False) -> RemoteAlbum:
        params = {"withoutAssets": "true"} if without_assets else None
        with self._client() as client:
            payload = self._get_json(client, f"/api/albums/{album_id}", params=params)
        if not isinstance(payload, dict):
            raise ImmichError("album response was not an object", error_class="malformed_response")
        assets_raw = payload.get("assets") or []
        if not isinstance(assets_raw, list):
            raise ImmichError("album assets were not a list", error_class="malformed_response")
        assets = [parse_asset(item) for item in assets_raw]
        return RemoteAlbum(
            album_id=str(payload.get("id") or album_id),
            name=str(payload.get("albumName") or payload.get("name") or "Album"),
            asset_count=int(payload.get("assetCount") or len(assets)),
            updated_at=parse_iso(payload.get("updatedAt")),
            assets=assets,
        )

    def download_original(self, asset_id: str, destination) -> None:
        url = f"/api/assets/{asset_id}/original"
        try:
            with self._client(timeout=self._download_timeout) as client:
                with client.stream("GET", url) as response:
                    _raise_for_status(response)
                    content_type = response.headers.get("content-type", "")
                    if content_type.startswith("text/") or "json" in content_type:
                        raise ImmichError(
                            "download returned a non-media response",
                            error_class="malformed_response",
                            status_code=response.status_code,
                        )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with destination.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            handle.write(chunk)
        except httpx.TimeoutException as exc:
            raise ImmichError("download timed out", error_class="timeout") from exc
        except httpx.HTTPError as exc:
            raise ImmichError("download failed", error_class="network") from exc

    def _get_json(self, client: httpx.Client, path: str, params: dict | None = None) -> Any:
        try:
            response = client.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise ImmichError("request timed out", error_class="timeout") from exc
        except httpx.HTTPError as exc:
            raise ImmichError("network error talking to Immich", error_class="network") from exc
        _raise_for_status(response)
        try:
            return response.json()
        except ValueError as exc:
            raise ImmichError("Immich returned non-JSON", error_class="malformed_response") from exc


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    if response.status_code in (401, 403):
        error_class = "authentication"
    elif response.status_code == 404:
        error_class = "not_found"
    elif response.status_code >= 500:
        error_class = "server_error"
    else:
        error_class = "http_error"
    raise ImmichError(
        f"Immich returned HTTP {response.status_code}",
        error_class=error_class,
        status_code=response.status_code,
    )


def parse_asset(payload: dict[str, Any]) -> RemoteAsset:
    if not isinstance(payload, dict) or not payload.get("id"):
        raise ImmichError("asset payload missing id", error_class="malformed_response")
    asset_type = str(payload.get("type") or "").upper()
    media_type = "video" if asset_type == "VIDEO" else "photo"
    exif = payload.get("exifInfo") or {}
    if not isinstance(exif, dict):
        exif = {}
    duration = exif.get("duration")
    try:
        duration_seconds = float(duration) if duration not in (None, "") else None
    except (TypeError, ValueError):
        duration_seconds = None
    file_size = payload.get("exifInfo", {}).get("fileSizeInByte") if isinstance(payload.get("exifInfo"), dict) else None
    if file_size is None:
        file_size = payload.get("fileSize") or (exif.get("fileSizeInByte") if isinstance(exif, dict) else None)
    checksum = payload.get("checksum")
    if isinstance(checksum, str) and checksum.startswith("\\x"):
        checksum = checksum[2:]
    return RemoteAsset(
        immich_id=str(payload["id"]),
        media_type=media_type,  # type: ignore[arg-type]
        filename=_optional_str(payload.get("originalFileName") or payload.get("originalPath")),
        mime_type=_optional_str(payload.get("originalMimeType") or payload.get("mimeType")),
        captured_at=_first_datetime(exif.get("dateTimeOriginal"), payload.get("fileCreatedAt"), payload.get("localDateTime")),
        immich_created_at=parse_iso(payload.get("createdAt")),
        immich_updated_at=parse_iso(payload.get("updatedAt")),
        width=_optional_int(exif.get("exifImageWidth") or payload.get("width")),
        height=_optional_int(exif.get("exifImageHeight") or payload.get("height")),
        duration_seconds=duration_seconds,
        file_size_bytes=_optional_int(file_size),
        checksum=_optional_str(checksum),
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_datetime(*values: Any) -> datetime | None:
    for value in values:
        if isinstance(value, str):
            parsed = parse_iso(value)
            if parsed is not None:
                return parsed
    return None


def change_marker(album: RemoteAlbum) -> str:
    """Cheap hint only. Correctness comes from comparing asset IDs."""
    newest = ""
    for asset in album.assets:
        stamp = asset.immich_updated_at.isoformat() if asset.immich_updated_at else ""
        if stamp > newest:
            newest = stamp
    updated = album.updated_at.isoformat() if album.updated_at else ""
    return f"{album.asset_count}|{updated}|{newest}|{len(album.assets)}"
