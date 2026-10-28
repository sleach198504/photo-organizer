"""Long-running work: scan, organize, and applying marks. All three are background
jobs the UI polls, so the window stays responsive and can show real progress."""
from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...media import warmer
from ...organize import (
    DEFAULT_TEMPLATE,
    TEMPLATES,
    clean_folder_name,
    get_folder_preview,
    preview_organize,
)
from ...pipeline import run_organize_job, run_scan
from ...settings import SettingsError, get_config, read_settings, update_settings
from ..deps import app_state, get_conn
from ..state import AppState

router = APIRouter(prefix="/api")


@router.get("/jobs/{name}")
def job_status(name: str, state: AppState = Depends(app_state)) -> dict:
    job = state.jobs.get(name)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown task.")
    snapshot = job.snapshot()
    if name == "scan":
        snapshot["thumbs"] = warmer.status()
    return snapshot


@router.post("/jobs/{name}/cancel")
def job_cancel(name: str, state: AppState = Depends(app_state)) -> dict:
    job = state.jobs.get(name)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown task.")
    job.request_cancel()
    return {"ok": True}


class ScanBody(BaseModel):
    source_dir: str | None = None
    quarantine_dir: str | None = None


@router.post("/scan/start")
def start_scan(body: ScanBody, state: AppState = Depends(app_state)) -> dict:
    if state.any_job_running():
        raise HTTPException(status_code=409, detail="Another task is still running.")
    patch = {k: v for k, v in body.model_dump().items() if v}
    try:
        settings = update_settings(patch) if patch else read_settings()
    except SettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not settings["configured"]:
        raise HTTPException(status_code=400, detail="Choose your photos folder first.")

    job = state.jobs["scan"]
    job.start()
    threading.Thread(target=run_scan, args=(job, get_config(), settings), daemon=True, name="scan").start()
    return {"started": True}


# -- organize --------------------------------------------------------------


class OrganizeBody(BaseModel):
    dest_dir: str
    folder_name: str = ""
    template: str = DEFAULT_TEMPLATE
    excluded: list[str] = []
    exclude_mode: str = "skip"


def _destination(body: OrganizeBody, config) -> Path:
    dest = body.dest_dir.strip()
    if not dest:
        raise HTTPException(status_code=400, detail="Choose a folder to file your photos into.")
    root = Path(dest)
    if body.folder_name.strip():
        root = root / clean_folder_name(body.folder_name)
    try:
        resolved = root.resolve()
        if resolved == config.quarantine_dir.resolve() or resolved.is_relative_to(config.quarantine_dir.resolve()):
            raise HTTPException(status_code=400, detail="Pick a folder outside the review folder.")
    except OSError:
        pass
    if body.exclude_mode not in ("skip", "move_as_is"):
        raise HTTPException(status_code=400, detail="Unknown option for the folders you left out.")
    return root


@router.get("/organize/state")
def organize_state(conn=Depends(get_conn)) -> dict:
    config = get_config()
    settings = read_settings()
    active = conn.execute("SELECT COUNT(*) c FROM photos WHERE status = 'active'").fetchone()["c"]
    return {
        "dest_dir": settings["organize_dest_dir"],
        "active": active,
        "folders": get_folder_preview(conn, config.source_dir),
        "templates": [{"key": k, **v} for k, v in TEMPLATES.items()],
        "default_template": DEFAULT_TEMPLATE,
    }


@router.post("/organize/preview")
def organize_preview(body: OrganizeBody, conn=Depends(get_conn)) -> dict:
    config = get_config()
    root = _destination(body, config)
    result = preview_organize(conn, config.source_dir, set(body.excluded), body.exclude_mode, body.template)
    result["dest_root"] = str(root)
    return result


@router.post("/organize/start")
def organize_start(body: OrganizeBody, state: AppState = Depends(app_state)) -> dict:
    if state.any_job_running():
        raise HTTPException(status_code=409, detail="Another task is still running.")
    config = get_config()
    root = _destination(body, config)
    try:
        update_settings({"organize_dest_dir": body.dest_dir.strip()})
    except SettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job = state.jobs["organize"]
    job.start()
    threading.Thread(
        target=run_organize_job,
        args=(job, config, root, set(body.excluded), body.exclude_mode, body.template),
        daemon=True,
        name="organize",
    ).start()
    return {"started": True}
