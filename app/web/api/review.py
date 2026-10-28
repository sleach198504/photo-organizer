"""Review: categories, marks (decisions not yet applied) and the Removed folder."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...actions import purge_photos, restore_photo
from ...db import log_activity
from ...library import BRIEF_COLUMNS, BRIEF_FROM, brief, list_removed
from ...marks import VALID_MARKS, clear_all_marks, mark_summary, previous_marks, set_marks, suggest_marks
from ...pipeline import run_apply_job
from ...review import list_category, review_overview
from ...settings import get_config
from ..deps import app_state, get_conn
from ..state import AppState

router = APIRouter(prefix="/api")


@router.get("/review/overview")
def overview(conn=Depends(get_conn)) -> dict:
    return review_overview(conn)


@router.get("/review/{key}")
def category(key: str, offset: int = 0, limit: int = 40, conn=Depends(get_conn)) -> dict:
    try:
        return list_category(conn, key, offset, limit)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown review category.")


# -- marks -----------------------------------------------------------------


class MarkBody(BaseModel):
    ids: list[int]
    mark: str | None = None  # 'remove' | 'keep' | None to clear


@router.get("/marks")
def marks_summary(conn=Depends(get_conn)) -> dict:
    return mark_summary(conn)


@router.get("/marks/items")
def marked_items(mark: str = "remove", offset: int = 0, limit: int = 300, conn=Depends(get_conn)) -> dict:
    if mark not in VALID_MARKS:
        raise HTTPException(status_code=400, detail="Unknown mark.")
    total = conn.execute(
        "SELECT COUNT(*) c FROM marks m JOIN photos p ON p.id = m.photo_id WHERE m.mark = ? AND p.status = 'active'",
        (mark,),
    ).fetchone()["c"]
    rows = conn.execute(
        f"SELECT {BRIEF_COLUMNS} FROM {BRIEF_FROM} WHERE m.mark = ? AND p.status = 'active' "
        f"ORDER BY m.marked_at DESC, p.id LIMIT ? OFFSET ?",
        (mark, max(1, min(limit, 1000)), max(0, offset)),
    ).fetchall()
    return {"total": total, "items": [brief(r) for r in rows]}


@router.put("/marks")
def put_marks(body: MarkBody, conn=Depends(get_conn)) -> dict:
    if body.mark is not None and body.mark not in VALID_MARKS:
        raise HTTPException(status_code=400, detail="Unknown mark.")
    previous = previous_marks(conn, body.ids)
    set_marks(conn, body.ids, body.mark)
    return {**mark_summary(conn), "previous": previous}


@router.post("/marks/clear")
def clear_marks(conn=Depends(get_conn)) -> dict:
    clear_all_marks(conn)
    return mark_summary(conn)


class SuggestBody(BaseModel):
    kinds: list[str] | None = None  # exact | near | video_near; None = all


@router.post("/marks/suggest")
def suggest(body: SuggestBody, conn=Depends(get_conn)) -> dict:
    result = suggest_marks(conn, body.kinds)
    return {**mark_summary(conn), **result}


@router.post("/marks/apply")
def apply(state: AppState = Depends(app_state)) -> dict:
    if state.any_job_running("scan", "organize", "apply"):
        raise HTTPException(status_code=409, detail="Wait for the current task to finish first.")
    job = state.jobs["apply"]
    job.start()
    threading.Thread(target=run_apply_job, args=(job, get_config()), daemon=True, name="apply").start()
    return {"started": True}


# -- removed ---------------------------------------------------------------


@router.get("/removed")
def removed(offset: int = 0, limit: int = 300, conn=Depends(get_conn)) -> dict:
    return list_removed(conn, offset, limit)


class IdsBody(BaseModel):
    ids: list[int] | None = None  # None = everything in the review folder


@router.post("/removed/restore")
def restore(body: IdsBody, conn=Depends(get_conn)) -> dict:
    config = get_config()
    if body.ids is None:
        ids = [r["id"] for r in conn.execute("SELECT id FROM photos WHERE status = 'quarantined'")]
    else:
        ids = body.ids
    restored = failed = 0
    for photo_id in ids:
        try:
            if restore_photo(conn, config, photo_id):
                restored += 1
            else:
                failed += 1
        except OSError:
            failed += 1
    if restored:
        log_activity(conn, "restored", f"Restored {restored:,} item{'s' if restored != 1 else ''} to your library")
    conn.commit()
    return {"restored": restored, "failed": failed}


class PurgeBody(IdsBody):
    confirm: str = ""


@router.post("/removed/purge")
def purge(body: PurgeBody, conn=Depends(get_conn)) -> dict:
    """The one irreversible action in the app, so it demands an explicit typed token
    on top of whatever confirmation the UI shows."""
    if body.confirm != "DELETE":
        raise HTTPException(status_code=400, detail="Deleting permanently needs confirmation.")
    result = purge_photos(conn, get_config(), body.ids)
    if result["deleted"]:
        log_activity(
            conn, "purged",
            f"Permanently deleted {result['deleted']:,} item{'s' if result['deleted'] != 1 else ''}",
            str(result["freed_bytes"]),
        )
    conn.commit()
    return result
