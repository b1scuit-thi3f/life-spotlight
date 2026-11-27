"""Display settings sent to and from the admin and presentation pages."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PresentationMode = Literal["now", "newest", "random", "balanced"]
presentationModes: tuple[str, ...] = ("now", "newest", "random", "balanced")
transitions: tuple[str, ...] = ("none", "fade")


class DisplayUpdate(BaseModel):
    presentationMode: str | None = None
    photoDurationSeconds: int | None = Field(default=None, ge=3, le=300)
    showOverlay: bool | None = None
    videosEnabled: bool | None = None
    transition: str | None = None
    newWindowHours: int | None = Field(default=None, ge=1, le=720)


class DisplayState(BaseModel):
    presentationMode: str
    photoDurationSeconds: int
    showOverlay: bool
    videosEnabled: bool
    transition: str
    newWindowHours: int
