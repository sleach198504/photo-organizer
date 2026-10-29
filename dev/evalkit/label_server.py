"""The labelling page: a small local web app for marking up the sampled photos.

It never shows the app's own opinions (sharpness scores, groups, flags), so your labels
are your own. Only the project folder is written to; your photo folder is read-only
until `export`, which copies finished photos into the project.
"""
from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import media
from app.paths import STATIC_DIR
from app.web import guard

from . import label_store

UI_DIR = Path(__file__).resolve().parent / "label_ui"
SIZES = {"thumb": (480, 80), "preview": (1800, 88), "full": (4096, 92)}  # long edge, JPEG quality
PORT = 8767


def create_app(folder: Path) -> FastAPI:
    project = label_store.load_project(folder)
    cache = folder / "cache"
    cache.mkdir(exist_ok=True)
    save_lock = threading.Lock()
    public = {k: v for k, v in project.items() if k != "private"}

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_requests_only(request: Request, call_next):
        h = request.headers
        if not guard.is_allowed(h.get("host"), h.get("origin"), h.get("sec-fetch-site")):
            return JSONResponse({"detail": guard.REFUSAL}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/api/project")
    def get_project() -> dict:
        labels = label_store.load_labels(folder)
        return {"project": public, "labels": labels, "progress": label_store.progress(project, labels)}

    @app.put("/api/labels")
    async def put_labels(request: Request) -> dict:
        labels = await request.json()
        try:
            with save_lock:
                label_store.save_labels(folder, labels)
        except (label_store.LabelError, KeyError, TypeError) as exc:
            raise HTTPException(400, f"Not saved: {exc}")
        return {"progress": label_store.progress(project, labels)}

    @app.post("/api/export")
    def post_export() -> dict:
        try:
            with save_lock:
                return label_store.export(folder)
        except label_store.LabelError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/img/{pid}")
    def image(pid: str, size: str = "thumb") -> FileResponse:
        info = project["photos"].get(pid)
        if info is None or size not in SIZES:
            raise HTTPException(404)
        target = cache / size / f"{pid}.jpg"
        if not target.exists():
            max_dim, quality = SIZES[size]
            source = Path(project["source"]) / info["rel"]
            try:
                data = media._render_still(source, max_dim, quality)
            except Exception as exc:  # an unreadable file should show, not crash the page
                raise HTTPException(422, f"Could not read {info['rel']}: {exc}")
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(data)
        return FileResponse(target, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(UI_DIR / "index.html")

    return app


def serve(folder: Path, open_browser: bool = True) -> None:
    import uvicorn
    import webbrowser

    url = f"http://127.0.0.1:{PORT}/"
    print(f"Labelling {folder.name}: {url}  (Ctrl+C to stop; your labels are saved as you go)")
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(folder), host="127.0.0.1", port=PORT, log_level="warning")
