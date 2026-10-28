"""The FastAPI application: JSON API, media, and the single-page UI shell."""
from __future__ import annotations

import logging
import os
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ..paths import STATIC_DIR
from .api import jobs, library, media, review, system
from .state import HEALTH_SENTINEL, SERVER_PORT, AppState

__all__ = ["create_app", "HEALTH_SENTINEL", "SERVER_PORT"]

log = logging.getLogger(__name__)

# How long the UI can go without a heartbeat before the server concludes the window
# is gone. Generous, and it must be seen twice, so a laptop waking from sleep (when
# the timestamp is hours old but the page is about to beat again) never kills it.
IDLE_GRACE_SECONDS = 90


def _idle_watcher(state: AppState) -> None:
    stale_checks = 0
    while True:
        time.sleep(15)
        reference = state.last_heartbeat or state.started_at  # not yet connected: grace from startup
        stale_checks = stale_checks + 1 if time.time() - reference > IDLE_GRACE_SECONDS else 0
        if stale_checks >= 2:
            log.info("No window connected - shutting down")
            os._exit(0)


def create_app(exit_when_idle: bool = False) -> FastAPI:
    app = FastAPI(title="Photo Organizer", docs_url=None, redoc_url=None, openapi_url=None)
    state = AppState()
    app.state.photo_state = state

    for module in (system, library, review, jobs):
        app.include_router(module.router)
    app.include_router(media.router)

    @app.get("/healthz", response_class=Response)
    def healthz() -> Response:
        # Distinguishes "our server is answering" from "something is listening on
        # this port" - a raw TCP connect can't tell those apart.
        return Response(content=HEALTH_SENTINEL, media_type="text/plain")

    @app.middleware("http")
    async def no_stale_ui(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static"):
            # Local and fast, so always revalidate: a new version must never be
            # shadowed by yesterday's cached script.
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error on %s", request.url.path)
        return JSONResponse(
            {"detail": "Something went wrong on our side. Try again, and if it keeps happening restart the app."},
            status_code=500,
        )

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / "icons" / "favicon.ico")

    if exit_when_idle:
        threading.Thread(target=_idle_watcher, args=(state,), daemon=True, name="idle-watcher").start()

    return app
