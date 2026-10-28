"""Library browsing: summary, the photo grid, timeline, search, trips."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ... import content_tagging
from ...library import briefs_for_ids, list_media, photo_detail, timeline, video_sessions
from ...search import search_library
from ...summary import library_summary
from ...trips import get_trip_candidates, ignore_trip, restore_trip, run_trip_detection, set_trip_name
from ..deps import app_state, get_conn
from ..state import AppState

router = APIRouter(prefix="/api")


@router.get("/summary")
def summary(conn=Depends(get_conn)) -> dict:
    return library_summary(conn)


@router.get("/photos")
def photos(
    kind: str | None = None,
    person: str | None = None,
    category: str | None = None,
    flagged: bool = False,
    sort: str = "newest",
    offset: int = 0,
    limit: int = Query(200, le=1000),
    conn=Depends(get_conn),
) -> dict:
    return list_media(
        conn, kind=kind, person=person, category=category, flagged=flagged,
        sort=sort, offset=offset, limit=limit,
    )


@router.get("/timeline")
def photos_timeline(
    kind: str | None = None,
    person: str | None = None,
    category: str | None = None,
    flagged: bool = False,
    sort: str = "newest",
    conn=Depends(get_conn),
) -> list[dict]:
    return timeline(conn, kind=kind, person=person, category=category, flagged=flagged, sort=sort)


@router.get("/photo/{photo_id}")
def photo(photo_id: int, conn=Depends(get_conn)) -> dict:
    detail = photo_detail(conn, photo_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="That photo isn't in the library.")
    return detail


@router.get("/video-sessions")
def sessions(conn=Depends(get_conn)) -> list[dict]:
    return video_sessions(conn)


@router.get("/search")
def search(q: str, limit: int = 120, state: AppState = Depends(app_state), conn=Depends(get_conn)) -> dict:
    query = q.strip()
    if not content_tagging.models_downloaded():
        return {"ready": False, "query": query, "items": []}
    if not query:
        return {"ready": True, "query": "", "items": []}

    ranked = search_library(conn, state.clip(), query, top_k=limit)
    by_id = {item["id"]: item for item in briefs_for_ids(conn, [r["id"] for r in ranked])}
    items = []
    for r in ranked:
        item = by_id.get(r["id"])
        if item is None:
            continue
        item["score"] = round(r["score"], 3)
        item["offset"] = r["offset_seconds"]
        items.append(item)
    return {"ready": True, "query": query, "items": items}


# -- trips ----------------------------------------------------------------


def _trip_view(conn, trip: dict) -> dict:
    samples = briefs_for_ids(
        conn,
        [
            r["photo_id"]
            for r in conn.execute(
                "SELECT photo_id FROM trip_candidate_members WHERE trip_id = ? ORDER BY photo_id LIMIT 6",
                (trip["id"],),
            )
        ],
    )
    return {
        "id": trip["id"],
        "kind": trip["kind"],
        "start": trip["start_date"],
        "end": trip["end_date"],
        "name": trip["custom_name"] or trip["suggested_name"],
        "suggested": trip["suggested_name"],
        "custom": bool(trip["custom_name"]),
        "count": trip["photo_count"],
        "samples": samples,
    }


@router.get("/trips")
def trips(status: str = "pending", conn=Depends(get_conn)) -> list[dict]:
    return [_trip_view(conn, t) for t in get_trip_candidates(conn, status)]


@router.post("/trips/detect")
def detect_trips(conn=Depends(get_conn)) -> dict:
    return run_trip_detection(conn)


class TripName(BaseModel):
    name: str


@router.put("/trips/{trip_id}/name")
def rename_trip(trip_id: int, body: TripName, conn=Depends(get_conn)) -> dict:
    set_trip_name(conn, trip_id, body.name)
    return {"ok": True}


@router.post("/trips/{trip_id}/ignore")
def ignore(trip_id: int, conn=Depends(get_conn)) -> dict:
    ignore_trip(conn, trip_id)
    return {"ok": True}


@router.post("/trips/{trip_id}/restore")
def restore(trip_id: int, conn=Depends(get_conn)) -> dict:
    restore_trip(conn, trip_id)
    return {"ok": True}
