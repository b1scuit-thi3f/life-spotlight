"""HTML pages. They do not contain frame logic."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from photo_frame import __version__

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def presentation(request: Request):
    return request.app.state.templates.TemplateResponse(request, "presentation.html", {"version": __version__})


@router.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    return request.app.state.templates.TemplateResponse(
        request,
        "admin.html",
        {"version": __version__, "hostname": request.app.state.runtime.hostname},
    )


@router.get("/setup", response_class=HTMLResponse)
def setup(request: Request):
    return request.app.state.templates.TemplateResponse(request, "setup.html", {"version": __version__})
