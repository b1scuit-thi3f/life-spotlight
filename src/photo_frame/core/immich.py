"""Small httpx wrapper around the Immich REST API.

The installed server version is discovered at runtime. Album membership is
read only from the configured album; the client does not walk the library.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from photo_frame.core.time import parseIso
from photo_frame.models.immich import RemoteAlbum, RemoteAsset

logger = logging.getLogger(__name__)


class ImmichError(Exception):
    def __init__(self, message: str, *, errorClass: str = "immich_error", statusCode: int | None = None):
        super().__init__(message)
        self.errorClass = errorClass
        self.statusCode = statusCode


class ImmichClient:
    def __init__(
        self,
        baseUrl: str,
        apiKey: str,
        *,
        timeout: float = 60.0,
        downloadTimeout: float = 300.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not baseUrl:
            raise ImmichError("Immich URL is not configured", errorClass="not_configured")
        if not apiKey:
            raise ImmichError("Immich API key is not configured", errorClass="not_configured")
        self.baseUrl = baseUrl.rstrip("/")
        self.apiKey = apiKey
        self.timeout = timeout
        self.downloadTimeout = downloadTimeout
        self.transport = transport

    def openClient(self, timeout: float | None = None) -> httpx.Client:
        return httpx.Client(
            base_url=self.baseUrl,
            headers={"x-api-key": self.apiKey, "Accept": "application/json"},
            timeout=timeout or self.timeout,
            follow_redirects=True,
            transport=self.transport,
        )

    def ping(self) -> dict[str, Any]:
        with self.openClient() as client:
            version = self.getJson(client, "/api/server/version")
            about: dict[str, Any] = {}
            try:
                about = self.getJson(client, "/api/server/about")
            except ImmichError:
                about = {}
            return {"version": version, "about": about}

    def listAlbums(self) -> list[dict[str, Any]]:
        with self.openClient() as client:
            payload = self.getJson(client, "/api/albums")
        if isinstance(payload, list):
            return payload
        raise ImmichError("album list response was not a list", errorClass="malformed_response")

    def getAlbum(self, albumId: str, *, withoutAssets: bool = False) -> RemoteAlbum:
        params = {"withoutAssets": "true"} if withoutAssets else None
        with self.openClient() as client:
            payload = self.getJson(client, f"/api/albums/{albumId}", params=params)
        if not isinstance(payload, dict):
            raise ImmichError("album response was not an object", errorClass="malformed_response")
        assetsRaw = payload.get("assets") or []
        if not isinstance(assetsRaw, list):
            raise ImmichError("album assets were not a list", errorClass="malformed_response")
        assetCount = int(payload.get("assetCount") or len(assetsRaw))
        # Immich v3 removed AlbumResponseDto.assets. The album still reports
        # assetCount. Membership comes from POST /api/search/metadata.
        if not withoutAssets and assetCount > 0 and len(assetsRaw) == 0:
            with self.openClient() as client:
                assetsRaw, complete = self.fetchAlbumAssets(client, albumId, assetCount)
            if not assetsRaw or (not complete and assetCount > len(assetsRaw)):
                raise ImmichError(
                    f"Immich reports {assetCount} album assets but search returned {len(assetsRaw)}",
                    errorClass="incomplete_album",
                )
        assets = [parseAsset(item) for item in assetsRaw]
        return RemoteAlbum(
            albumId=str(payload.get("id") or albumId),
            name=str(payload.get("albumName") or payload.get("name") or "Album"),
            assetCount=assetCount,
            updatedAt=parseIso(payload.get("updatedAt")),
            assets=assets,
        )

    def fetchAlbumAssets(
        self,
        client: httpx.Client,
        albumId: str,
        assetCount: int,
    ) -> tuple[list[Any], bool]:
        """Load album membership.

        Flat albumIds search is tried first because servers that do not know
        the v3.2 filter field strip it and would otherwise return the whole
        library. When that page search is rejected, or it stalls short of
        assetCount, the cursor filter search is used. A cursor result larger
        than the album is discarded so an unscoped search cannot be imported.
        """
        legacy = {"albumIds": [albumId], "size": 1000, "withExif": True}
        legacyAssets: list[Any] | None
        try:
            legacyAssets, legacyComplete = self.searchAlbumAssets(client, legacy, mode="page")
        except ImmichError as exc:
            if exc.statusCode not in (400, 422):
                raise
            logger.info("albumIds search was rejected; trying structured album search")
            legacyAssets, legacyComplete = None, False
        else:
            if legacyComplete and legacyAssets:
                return legacyAssets, True

        structured = {
            "filter": {"albumIds": {"any": [albumId]}},
            "size": 1000,
            "withExif": True,
        }
        try:
            assets, complete = self.searchAlbumAssets(client, structured, mode="cursor")
        except ImmichError as exc:
            if legacyAssets is None or exc.statusCode not in (400, 422):
                raise
            logger.info("structured album search was rejected; keeping the albumIds result")
            return legacyAssets, legacyComplete
        if len(assets) > assetCount:
            if legacyAssets is None:
                raise ImmichError(
                    f"album search returned {len(assets)} assets for an album of {assetCount}",
                    errorClass="incomplete_album",
                )
            return legacyAssets, legacyComplete
        return assets, complete

    def searchAlbumAssets(
        self,
        client: httpx.Client,
        base: dict[str, Any],
        *,
        mode: str,
    ) -> tuple[list[Any], bool]:
        collected: list[Any] = []
        seenIds: set[str] = set()
        seenTokens: set[str] = set()
        token: Any = None if mode == "cursor" else 1
        for _ in range(200):
            body = dict(base)
            if mode == "cursor":
                if token is not None:
                    body["cursor"] = token
            else:
                body["page"] = int(token)
            payload = self.postJson(client, "/api/search/metadata", body)
            if not isinstance(payload, dict):
                raise ImmichError("album search response was not an object", errorClass="malformed_response")
            assets = payload.get("assets")
            if not isinstance(assets, dict):
                raise ImmichError("album search response was missing assets", errorClass="malformed_response")
            items = assets.get("items") or []
            if not isinstance(items, list):
                raise ImmichError("album search items were not a list", errorClass="malformed_response")
            nextCursor, nextPage = assets.get("nextCursor"), assets.get("nextPage")
            added = 0
            for item in items:
                if not isinstance(item, dict):
                    raise ImmichError("album search item was not an object", errorClass="malformed_response")
                assetId = str(item.get("id") or "")
                if assetId and assetId in seenIds:
                    continue
                if assetId:
                    seenIds.add(assetId)
                collected.append(item)
                added += 1
            nxt = nextCursor if mode == "cursor" else nextPage
            if nxt in (None, "", 0):
                return collected, True
            tokenKey = str(nxt)
            if added == 0 or tokenKey in seenTokens:
                return collected, False
            seenTokens.add(tokenKey)
            if mode == "cursor":
                token = nxt
            else:
                try:
                    token = int(nxt)
                except (TypeError, ValueError) as exc:
                    raise ImmichError(
                        "album search next page was not a number",
                        errorClass="malformed_response",
                    ) from exc
                if token < 1:
                    raise ImmichError("album search next page was not a number", errorClass="malformed_response")
        raise ImmichError("album search exceeded the page limit", errorClass="incomplete_album")

    def downloadOriginal(self, assetId: str, destination) -> None:
        url = f"/api/assets/{assetId}/original"
        try:
            with self.openClient(timeout=self.downloadTimeout) as client:
                with client.stream("GET", url) as response:
                    raiseForStatus(response)
                    contentType = response.headers.get("content-type", "")
                    if contentType.startswith("text/") or "json" in contentType:
                        raise ImmichError(
                            "download returned a non-media response",
                            errorClass="malformed_response",
                            statusCode=response.status_code,
                        )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with destination.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            handle.write(chunk)
        except httpx.TimeoutException as exc:
            raise ImmichError("download timed out", errorClass="timeout") from exc
        except httpx.HTTPError as exc:
            raise ImmichError("download failed", errorClass="network") from exc

    def getJson(self, client: httpx.Client, path: str, params: dict | None = None) -> Any:
        try:
            response = client.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise ImmichError("request timed out", errorClass="timeout") from exc
        except httpx.HTTPError as exc:
            raise ImmichError("network error talking to Immich", errorClass="network") from exc
        return jsonBody(response)

    def postJson(self, client: httpx.Client, path: str, body: dict[str, Any]) -> Any:
        try:
            response = client.post(path, json=body)
        except httpx.TimeoutException as exc:
            raise ImmichError("request timed out", errorClass="timeout") from exc
        except httpx.HTTPError as exc:
            raise ImmichError("network error talking to Immich", errorClass="network") from exc
        return jsonBody(response)


def jsonBody(response: httpx.Response) -> Any:
    raiseForStatus(response)
    try:
        return response.json()
    except ValueError as exc:
        raise ImmichError("Immich returned non-JSON", errorClass="malformed_response") from exc


def raiseForStatus(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    if response.status_code in (401, 403):
        errorClass = "authentication"
    elif response.status_code == 404:
        errorClass = "not_found"
    elif response.status_code >= 500:
        errorClass = "server_error"
    else:
        errorClass = "http_error"
    raise ImmichError(
        f"Immich returned HTTP {response.status_code}",
        errorClass=errorClass,
        statusCode=response.status_code,
    )


def parseAsset(payload: dict[str, Any]) -> RemoteAsset:
    if not isinstance(payload, dict) or not payload.get("id"):
        raise ImmichError("asset payload missing id", errorClass="malformed_response")
    assetType = str(payload.get("type") or "").upper()
    mediaType = "video" if assetType == "VIDEO" else "photo"
    exif = payload.get("exifInfo") or {}
    if not isinstance(exif, dict):
        exif = {}
    duration = exif.get("duration")
    try:
        durationSeconds = float(duration) if duration not in (None, "") else None
    except (TypeError, ValueError):
        durationSeconds = None
    fileSize = exif.get("fileSizeInByte")
    if fileSize is None:
        fileSize = payload.get("fileSize")
    checksum = payload.get("checksum")
    if isinstance(checksum, str) and checksum.startswith("\\x"):
        checksum = checksum[2:]
    checksum = str(checksum).strip() or None if checksum is not None else None
    filename = payload.get("originalFileName") or payload.get("originalPath")
    filename = str(filename).strip() or None if filename is not None else None
    mimeType = payload.get("originalMimeType") or payload.get("mimeType")
    mimeType = str(mimeType).strip() or None if mimeType is not None else None
    capturedAt = None
    for value in (exif.get("dateTimeOriginal"), payload.get("fileCreatedAt"), payload.get("localDateTime")):
        if isinstance(value, str):
            capturedAt = parseIso(value)
            if capturedAt is not None:
                break
    numbers: list[int | None] = []
    for raw in (exif.get("exifImageWidth") or payload.get("width"), exif.get("exifImageHeight") or payload.get("height"), fileSize):
        if raw in (None, ""):
            numbers.append(None)
            continue
        try:
            numbers.append(int(raw))
        except (TypeError, ValueError):
            numbers.append(None)
    width, height, fileSizeBytes = numbers
    return RemoteAsset(
        immichId=str(payload["id"]),
        mediaType=mediaType,  # type: ignore[arg-type]
        filename=filename,
        mimeType=mimeType,
        capturedAt=capturedAt,
        immichCreatedAt=parseIso(payload.get("createdAt")),
        immichUpdatedAt=parseIso(payload.get("updatedAt")),
        width=width,
        height=height,
        durationSeconds=durationSeconds,
        fileSizeBytes=fileSizeBytes,
        checksum=checksum,
    )
