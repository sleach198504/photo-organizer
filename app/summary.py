"""Whole-library numbers for Home and the sidebar badges."""
from __future__ import annotations

from .db import CURRENT_META_VERSION, get_meta
from .marks import mark_summary
from .review import review_overview


def library_summary(conn) -> dict:
    counts = {"photo": 0, "video": 0}
    bytes_active = 0
    quarantined = {"count": 0, "bytes": 0}
    organized = 0
    for row in conn.execute(
        "SELECT status, media_type, COUNT(*) AS n, SUM(size_bytes) AS b FROM photos GROUP BY status, media_type"
    ):
        if row["status"] == "active":
            counts[row["media_type"]] = row["n"]
            bytes_active += row["b"] or 0
        elif row["status"] == "quarantined":
            quarantined["count"] += row["n"]
            quarantined["bytes"] += row["b"] or 0
        elif row["status"] == "organized":
            organized += row["n"]

    review = review_overview(conn)
    dated = conn.execute(
        "SELECT COUNT(*) c FROM photos WHERE status = 'active' AND taken_at IS NOT NULL"
    ).fetchone()["c"]
    trips = conn.execute("SELECT COUNT(*) c FROM trip_candidates WHERE status = 'pending'").fetchone()["c"]
    # Rows read by an older version of the app are missing details (capture dates, video
    # info). A scan fills them in without re-reading file contents, so just say so.
    stale = conn.execute(
        "SELECT COUNT(*) c FROM photos WHERE status = 'active' AND meta_version < ?", (CURRENT_META_VERSION,)
    ).fetchone()["c"]
    # What the recognition model found that is worth browsing by but not worth flagging (see
    # content_tagging.FLAGGED_CATEGORIES): the Photos page offers these as a filter.
    tags = {
        r["content_tags"]: r["n"]
        for r in conn.execute(
            "SELECT content_tags, COUNT(*) AS n FROM photos WHERE status = 'active' AND media_type = 'photo' "
            "AND content_tags IN ('document', 'whiteboard', 'food', 'meme') GROUP BY content_tags"
        )
    }
    activity = [
        {"id": r["id"], "ts": r["ts"], "kind": r["kind"], "title": r["title"], "detail": r["detail"]}
        for r in conn.execute("SELECT * FROM activity ORDER BY id DESC LIMIT 8")
    ]
    return {
        "photos": counts["photo"],
        "videos": counts["video"],
        "bytes": bytes_active,
        "dated": dated,
        "organized": organized,
        "removed": quarantined,
        "trips": trips,
        "needs_rescan": stale,
        "review": review,
        "tags": tags,
        "marks": mark_summary(conn),
        "last_scan": get_meta(conn, "last_scan_at"),
        "activity": activity,
    }
