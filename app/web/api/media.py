"""Serving thumbnails, previews and video. Every URL carries the file's modified time
(`?v=`), so a response can be cached forever - an edited file gets a new URL."""
from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ... import media
from ..deps import get_conn

log = logging.getLogger(__name__)
router = APIRouter(prefix="/media")

IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


def _row(conn, photo_id: int):
    row = conn.execute(
        "SELECT id, path, mtime, media_type FROM photos WHERE id = ?", (photo_id,)
    ).fetchone()
    if row is None or not Path(row["path"]).exists():
        raise HTTPException(status_code=404, detail="Not found")
    return row


def _rendition(kind: str, row) -> FileResponse:
    try:
        target = media.ensure(kind, row["id"], row["path"], row["mtime"], row["media_type"])
    except Exception as exc:  # undecodable file: the UI shows a placeholder tile
        log.debug("Could not render %s for photo %s: %s", kind, row["id"], exc)
        raise HTTPException(status_code=404, detail="Couldn't render this file") from exc
    return FileResponse(target, media_type="image/jpeg", headers=IMMUTABLE)


@router.get("/thumb/{photo_id}")
def thumb(photo_id: int, v: int = 0, conn=Depends(get_conn)) -> FileResponse:
    return _rendition("thumb", _row(conn, photo_id))


@router.get("/preview/{photo_id}")
def preview(photo_id: int, v: int = 0, conn=Depends(get_conn)) -> FileResponse:
    return _rendition("preview", _row(conn, photo_id))


@router.get("/original/{photo_id}")
def original(photo_id: int, v: int = 0, conn=Depends(get_conn)) -> FileResponse:
    """The full-resolution file for judging sharpness at 100%. Formats a browser
    can't display (HEIC, TIFF) are converted once to a high-quality JPEG."""
    row = _row(conn, photo_id)
    if row["media_type"] == "photo" and media.browser_displayable(row["path"]):
        media_type = mimetypes.guess_type(row["path"])[0] or "image/jpeg"
        return FileResponse(row["path"], media_type=media_type, headers=IMMUTABLE)
    return _rendition("original", row)


@router.get("/video/{photo_id}")
def video(photo_id: int, v: int = 0, conn=Depends(get_conn)) -> FileResponse:
    row = _row(conn, photo_id)
    if row["media_type"] != "video":
        raise HTTPException(status_code=404, detail="Not a video")
    media_type = mimetypes.guess_type(row["path"])[0] or "video/mp4"
    return FileResponse(row["path"], media_type=media_type)  # supports Range, so seeking works
