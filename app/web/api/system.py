"""App-level endpoints: version/status, settings, lifecycle, native folder picker."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ... import content_tagging, folder_dialog, legacy_import
from ...media import warmer
from ...paths import APP_HOME, CHANNEL, CODE_ROOT
from ...settings import REVIEW_SUBFOLDER_NAME, SettingsError, read_settings, update_settings
from ...version import __version__
from ..deps import get_conn
from ..state import AppState
from ..deps import app_state

router = APIRouter(prefix="/api")

RELEASES_URL = "https://api.github.com/repos/sleach198504/photo-organizer/releases/latest"


@router.get("/system")
def system(state: AppState = Depends(app_state)) -> dict:
    return {
        "version": __version__,
        "models_ready": content_tagging.models_downloaded(),
        "home": str(APP_HOME),
        "channel": CHANNEL,  # "store" when updates come from the Microsoft Store, else None
        "imported_from": legacy_import.imported_from(APP_HOME),
        "platform": sys.platform,
        "thumbs": warmer.status(),
    }


@router.get("/licences", response_class=PlainTextResponse)
def licences() -> str:
    """The open-source notices and the licence text that ship with the app, as one page."""
    parts = []
    for name in ("THIRD_PARTY_NOTICES.md", "LICENSE"):
        path = CODE_ROOT / name
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8"))
    if not parts:
        raise HTTPException(404, "The licence files are missing from this install.")
    return ("\n\n" + "=" * 72 + "\n\n").join(parts)


@router.post("/heartbeat")
def heartbeat(state: AppState = Depends(app_state)) -> dict:
    state.beat()
    return {"ok": True}


@router.post("/shutdown")
def shutdown() -> dict:
    def delayed_exit() -> None:
        time.sleep(0.4)
        os._exit(0)

    threading.Thread(target=delayed_exit, daemon=True).start()
    return {"ok": True}


@router.get("/settings")
def get_settings() -> dict:
    return read_settings()


class SettingsPatch(BaseModel):
    source_dir: str | None = None
    quarantine_dir: str | None = None
    organize_dest_dir: str | None = None
    auto_remove_exact_duplicates: bool | None = None
    similarity: str | None = None
    video_review_mode: str | None = None
    video_search_depth: str | None = None


@router.put("/settings")
def put_settings(patch: SettingsPatch) -> dict:
    try:
        return update_settings(patch.model_dump(exclude_none=True))
    except SettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class PickFolder(BaseModel):
    purpose: str = "photos"  # photos | review | organize
    initial: str | None = None


@router.post("/pick-folder")
def pick_folder(body: PickFolder, state: AppState = Depends(app_state)) -> dict:
    """Opens the real Windows folder picker. It is a native dialog, not a browser
    one, because a web page is not allowed to read a local folder path."""
    titles = {
        "photos": "Choose the folder that holds your photos",
        "review": "Choose where removed photos should wait for review",
        "organize": "Choose where to file your photos",
    }
    with state.pick_folder_lock:
        try:
            chosen = folder_dialog.choose_folder(titles.get(body.purpose, "Choose a folder"), body.initial)
        except OSError as exc:
            raise HTTPException(status_code=500, detail="Windows couldn't open the folder picker.") from exc

    if not chosen:
        return {"path": ""}
    path = str(Path(chosen))
    if body.purpose == "review" and Path(path).name != REVIEW_SUBFOLDER_NAME:
        path = str(Path(path) / REVIEW_SUBFOLDER_NAME)
    return {"path": path}


@router.post("/reveal/{photo_id}")
def reveal(photo_id: int, conn=Depends(get_conn)) -> dict:
    """Show a file in Windows Explorer."""
    row = conn.execute("SELECT path FROM photos WHERE id = ?", (photo_id,)).fetchone()
    if row is None or not Path(row["path"]).exists():
        raise HTTPException(status_code=404, detail="That file isn't on disk any more.")
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{os.path.normpath(row['path'])}"])
    return {"ok": True}


def _version_tuple(tag: str) -> tuple[int, ...]:
    parts = []
    for piece in tag.lstrip("vV").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


@router.get("/update-check")
def update_check() -> dict:
    """Asks GitHub for the latest release. Only ever called when the person clicks
    'Check for updates' - the app never phones home on its own. Not available in the Store build,
    which has no network access of its own at all."""
    if CHANNEL == "store":
        raise HTTPException(status_code=404, detail="Updates come from the Microsoft Store.")
    request = urllib.request.Request(RELEASES_URL, headers={"User-Agent": "PhotoOrganizer"})
    try:
        with urllib.request.urlopen(request, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Couldn't reach GitHub to check. Are you online?") from exc
    latest = data.get("tag_name", "")
    return {
        "current": __version__,
        "latest": latest.lstrip("vV"),
        "newer": bool(latest) and _version_tuple(latest) > _version_tuple(__version__),
        "url": data.get("html_url"),
    }
