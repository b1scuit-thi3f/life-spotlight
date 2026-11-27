"""Presentation playback endpoints and cached media files."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from photo_frame.core.settings import SettingsService
from photo_frame.core.status import displayState, presentationMedia
from photo_frame.models.media import PlaybackReport, PresentationNext

router = APIRouter()


@router.get("/api/presentation/next")
def nextMedia(request: Request, exclude: str = "") -> PresentationNext:
    app = request.app
    settings: SettingsService = app.state.settingsService
    selector = app.state.selector
    selector.newWindowHours = settings.newWindowHours()
    excludeIds = [int(part) for part in exclude.split(",") if part.strip().isdigit()]
    selection = selector.choose(
        app.state.repository.listPresent(videosEnabled=settings.videosEnabled()),
        settings.presentationMode(),
        excludeIds=excludeIds[-12:],
    )
    display = displayState(settings)
    if selection is None:
        return PresentationNext(media=None, display=display)
    app.state.db.setSync("currently_displayed_id", str(selection.media.id))
    return PresentationNext(
        media=presentationMedia(selection.media, selection.isNew),
        reason=selection.reason,
        display=display,
    )


@router.post("/api/presentation/played")
def played(request: Request, report: PlaybackReport):
    media = request.app.state.repository.get(report.mediaId)
    if media is None:
        raise HTTPException(status_code=404, detail="unknown media")
    request.app.state.repository.recordDisplay(
        media.id,
        durationSeconds=report.durationSeconds,
        completed=report.completed,
        audioEnabled=report.audioEnabled,
    )
    return {"ok": True}


@router.get("/media/{mediaId}")
def mediaFile(request: Request, mediaId: int):
    media = request.app.state.repository.get(mediaId)
    if media is None or not media.isPresent:
        raise HTTPException(status_code=404, detail="media is not available")
    cacheDir: Path = request.app.state.runtime.cacheDir
    path = Path(media.localPath).resolve()
    try:
        path.relative_to(cacheDir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="media path is not in the cache") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="cached file is missing")
    return FileResponse(path, media_type=media.mimeType or "application/octet-stream")
