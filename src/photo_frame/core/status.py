"""Build the status and presentation models the API returns."""

from __future__ import annotations

from photo_frame.core.settings import SettingsService
from photo_frame.core.time import ageLabel, parseIso
from photo_frame.models.display import DisplayState
from photo_frame.models.media import MediaRecord, PresentationMedia
from photo_frame.models.system import SystemState


def displayState(settings: SettingsService) -> DisplayState:
    return DisplayState(
        presentationMode=settings.presentationMode(),
        photoDurationSeconds=settings.photoDurationSeconds(),
        showOverlay=settings.showOverlay(),
        videosEnabled=settings.videosEnabled(),
        transition=settings.transition(),
        newWindowHours=settings.newWindowHours(),
    )


def systemState(settings: SettingsService) -> SystemState:
    return SystemState(
        cacheCeilingBytes=settings.cacheCeilingBytes(),
        reservedBytes=settings.reservedBytes(),
        syncIncrementalMinutes=settings.syncIncrementalMinutes(),
        syncReconcileHours=settings.syncReconcileHours(),
        httpTimeoutSeconds=settings.httpTimeoutSeconds(),
        downloadTimeoutSeconds=settings.downloadTimeoutSeconds(),
    )


def presentationMedia(media: MediaRecord, isNew: bool) -> PresentationMedia:
    captured = parseIso(media.capturedAt)
    firstSeen = parseIso(media.firstSeenAt)
    return PresentationMedia(
        id=media.id,
        mediaType=media.mediaType,
        mimeType=media.mimeType,
        url=f"/media/{media.id}",
        width=media.width,
        height=media.height,
        durationSeconds=media.durationSeconds,
        isNew=isNew,
        addedLabel=f"added {ageLabel(firstSeen)}" if firstSeen else "",
        capturedLabel="" if captured is None else f"{captured.day} {captured.strftime('%b %Y')}",
        filename=media.filename,
    )
