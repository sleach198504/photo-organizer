"""Read-side queries for browsing the library: the photo/video grid, its timeline,
per-photo detail, and video sessions.

Every item the UI shows goes through `brief()`, so a thumbnail looks and carries the
same data (size, date, mark, ...) wherever it appears.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

# Capture date when we have it, else the file's modified time in the same format so
# the two sort consistently together.
SORT_DATE = "COALESCE(p.taken_at, strftime('%Y-%m-%dT%H:%M:%S', p.mtime, 'unixepoch'))"

# Everything a thumbnail or list row needs, plus the mark - one place so every
# query selects the same columns.
BRIEF_COLUMNS = f"""
    p.id, p.path, p.media_type, p.width, p.height, p.size_bytes, p.mtime, p.taken_at,
    p.duration_seconds, p.blur_score, p.live_pair_path, p.content_tags, p.has_person,
    p.quarantined_at, {SORT_DATE} AS sort_date, m.mark AS mark
"""
BRIEF_FROM = "photos p LEFT JOIN marks m ON m.photo_id = p.id"


def brief(row) -> dict:
    return {
        "id": row["id"],
        "kind": row["media_type"],
        "w": row["width"],
        "h": row["height"],
        "size": row["size_bytes"],
        "date": row["sort_date"],
        "dur": row["duration_seconds"],
        "name": Path(row["path"]).name,
        "v": int(row["mtime"] or 0),
        "mark": row["mark"],
        "blur": round(row["blur_score"], 1) if row["blur_score"] is not None else None,
        "live": bool(row["live_pair_path"]),
        "tag": row["content_tags"],
    }


def briefs_for_ids(conn, ids: list[int]) -> list[dict]:
    """Briefs in the given order (ids that no longer exist are skipped)."""
    if not ids:
        return []
    by_id: dict[int, dict] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        placeholders = ",".join("?" * len(chunk))
        for row in conn.execute(
            f"SELECT {BRIEF_COLUMNS} FROM {BRIEF_FROM} WHERE p.id IN ({placeholders})", chunk
        ):
            by_id[row["id"]] = brief(row)
    return [by_id[i] for i in ids if i in by_id]


def _where(kind, person, category, flagged, status="active") -> tuple[str, list]:
    clauses = ["p.status = ?"]
    params: list = [status]
    if kind in ("photo", "video"):
        clauses.append("p.media_type = ?")
        params.append(kind)
    if person == "with":
        clauses.append("p.has_person = 1")
    elif person == "without":
        clauses.append("p.has_person = 0")
    if category:
        clauses.append("p.content_tags = ?")
        params.append(category)
    if flagged:
        clauses.append("EXISTS (SELECT 1 FROM recommendations r WHERE r.photo_id = p.id AND r.decision = 'pending')")
    return " AND ".join(clauses), params


def _order(sort: str) -> str:
    if sort == "oldest":
        return f"{SORT_DATE} ASC, p.id ASC"
    if sort == "largest":
        return "p.size_bytes DESC, p.id DESC"
    return f"{SORT_DATE} DESC, p.id DESC"


def list_media(
    conn, *, kind=None, person=None, category=None, flagged=False, sort="newest",
    offset: int = 0, limit: int = 200,
) -> dict:
    where, params = _where(kind, person, category, flagged)
    total = conn.execute(f"SELECT COUNT(*) c FROM photos p WHERE {where}", params).fetchone()["c"]
    rows = conn.execute(
        f"SELECT {BRIEF_COLUMNS} FROM {BRIEF_FROM} WHERE {where} ORDER BY {_order(sort)} LIMIT ? OFFSET ?",
        [*params, max(1, min(limit, 1000)), max(0, offset)],
    ).fetchall()
    return {"total": total, "offset": offset, "items": [brief(r) for r in rows]}


def timeline(conn, *, kind=None, person=None, category=None, flagged=False, sort="newest") -> list[dict]:
    """Month buckets with the grid offset each starts at - lets the UI jump straight
    to a month in a 50,000-photo library without loading everything before it."""
    where, params = _where(kind, person, category, flagged)
    rows = conn.execute(
        f"SELECT substr({SORT_DATE}, 1, 7) AS month, COUNT(*) AS n FROM photos p WHERE {where} "
        f"GROUP BY month ORDER BY month {'ASC' if sort == 'oldest' else 'DESC'}",
        params,
    ).fetchall()
    result, offset = [], 0
    for row in rows:
        result.append({"month": row["month"], "count": row["n"], "offset": offset})
        offset += row["n"]
    return result


def photo_detail(conn, photo_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT {BRIEF_COLUMNS}, p.camera_model, p.gps_lat, p.gps_lon, p.status, p.sha256 "
        f"FROM {BRIEF_FROM} WHERE p.id = ?",
        (photo_id,),
    ).fetchone()
    if row is None:
        return None

    detail = brief(row)
    detail.update(
        path=row["path"],
        folder=str(Path(row["path"]).parent),
        camera=row["camera_model"],
        gps=[row["gps_lat"], row["gps_lon"]] if row["gps_lat"] is not None else None,
        status=row["status"],
        person=None if row["has_person"] is None else bool(row["has_person"]),
    )
    detail["reasons"] = [
        r["reason"]
        for r in conn.execute(
            "SELECT reason FROM recommendations WHERE photo_id = ? AND decision = 'pending'", (photo_id,)
        )
    ]
    group = conn.execute(
        """
        SELECT dg.id AS group_id, dg.kind AS kind, dgm.is_keeper AS is_keeper,
               (SELECT COUNT(*) FROM dup_group_members x WHERE x.group_id = dg.id) AS members
        FROM dup_group_members dgm JOIN dup_groups dg ON dg.id = dgm.group_id
        WHERE dgm.photo_id = ?
        """,
        (photo_id,),
    ).fetchone()
    detail["group"] = (
        {"id": group["group_id"], "kind": group["kind"], "keeper": bool(group["is_keeper"]), "members": group["members"]}
        if group else None
    )
    return detail


def _timestamp(row) -> datetime:
    value = row["sort_date"]
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.fromtimestamp(row["mtime"])


def video_sessions(conn, window_minutes: int = 30) -> list[dict]:
    """Groups active videos into 'sessions' - runs where consecutive videos (by
    capture time, falling back to file time) are within window_minutes of each
    other - so a batch from the same event can be browsed together. Recomputed on
    demand; it's a browsing aid, not a stored decision."""
    rows = conn.execute(
        f"SELECT {BRIEF_COLUMNS} FROM {BRIEF_FROM} WHERE p.status = 'active' AND p.media_type = 'video'"
    ).fetchall()
    if not rows:
        return []

    rows = sorted(rows, key=_timestamp)
    sessions: list[list] = []
    current: list = []
    prev = None
    for row in rows:
        ts = _timestamp(row)
        if prev is not None and (ts - prev).total_seconds() > window_minutes * 60:
            sessions.append(current)
            current = []
        current.append(row)
        prev = ts
    if current:
        sessions.append(current)

    result = [
        {
            "start": _timestamp(members[0]).isoformat(),
            "end": _timestamp(members[-1]).isoformat(),
            "count": len(members),
            "bytes": sum(m["size_bytes"] or 0 for m in members),
            "items": [brief(m) for m in members],
        }
        for members in sessions
    ]
    result.reverse()  # newest first
    return result


def list_removed(conn, offset: int = 0, limit: int = 200) -> dict:
    """What has been moved to the review folder, most recently removed first."""
    where, params = _where(None, None, None, False, status="quarantined")
    row = conn.execute(
        f"SELECT COUNT(*) AS c, SUM(size_bytes) AS b FROM photos p WHERE {where}", params
    ).fetchone()
    rows = conn.execute(
        f"SELECT {BRIEF_COLUMNS} FROM {BRIEF_FROM} WHERE {where} "
        f"ORDER BY p.quarantined_at DESC, p.id DESC LIMIT ? OFFSET ?",
        [*params, max(1, min(limit, 1000)), max(0, offset)],
    ).fetchall()
    return {"total": row["c"], "bytes": row["b"] or 0, "offset": offset, "items": [brief(r) for r in rows]}
