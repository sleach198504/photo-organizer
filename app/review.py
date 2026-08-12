from __future__ import annotations

from datetime import datetime

CONTENT_CATEGORIES = ["food", "screenshot", "document", "meme", "whiteboard", "blank"]


def get_pending_review_items(conn) -> list[dict]:
    """One entry per photo that has at least one pending recommendation, with all of
    that photo's pending reasons and (if it's part of a duplicate group) the group's
    suggested keeper, for side-by-side comparison in the review UI."""
    photo_ids = [
        row["photo_id"]
        for row in conn.execute(
            "SELECT DISTINCT photo_id FROM recommendations WHERE decision = 'pending' ORDER BY photo_id"
        )
    ]

    items = []
    for photo_id in photo_ids:
        photo = conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
        if photo is None:
            continue
        reasons = [
            row["reason"]
            for row in conn.execute(
                "SELECT reason FROM recommendations WHERE photo_id = ? AND decision = 'pending'",
                (photo_id,),
            )
        ]

        keeper = None
        group_row = conn.execute(
            """
            SELECT dg.id AS group_id
            FROM dup_group_members dgm
            JOIN dup_groups dg ON dg.id = dgm.group_id
            WHERE dgm.photo_id = ? AND dgm.is_keeper = 0
            """,
            (photo_id,),
        ).fetchone()
        if group_row:
            keeper_row = conn.execute(
                """
                SELECT p.id, p.path
                FROM dup_group_members dgm
                JOIN photos p ON p.id = dgm.photo_id
                WHERE dgm.group_id = ? AND dgm.is_keeper = 1
                """,
                (group_row["group_id"],),
            ).fetchone()
            if keeper_row:
                keeper = {"id": keeper_row["id"], "path": keeper_row["path"]}

        items.append({"photo": dict(photo), "reasons": reasons, "keeper": keeper})

    return items


def get_pending_duplicate_groups(conn) -> dict[str, list[dict]]:
    """One entry per dup_group (not per photo) for the three duplicate-type review
    sections, so a burst of 5 similar photos shows as one group of 5 - keeper
    included - with every member individually selectable, instead of 4 disconnected
    "keeper vs this one" pairs. A group is included as long as at least one of its
    non-keeper members still has a pending decision; the keeper itself never gets
    its own recommendation row (see dedupe.py), so it's always offered here as a
    free choice rather than something that needs resolving."""
    kind_to_reason = {
        "exact": "exact_duplicate",
        "near": "near_duplicate",
        "video_near": "video_near_duplicate",
    }
    result: dict[str, list[dict]] = {reason: [] for reason in kind_to_reason.values()}

    for kind, reason in kind_to_reason.items():
        group_ids = [
            row["group_id"]
            for row in conn.execute(
                """
                SELECT DISTINCT dgm.group_id AS group_id
                FROM dup_group_members dgm
                JOIN dup_groups dg ON dg.id = dgm.group_id AND dg.kind = ?
                JOIN recommendations r ON r.photo_id = dgm.photo_id AND r.reason = ? AND r.decision = 'pending'
                """,
                (kind, reason),
            )
        ]
        for group_id in group_ids:
            member_rows = conn.execute(
                """
                SELECT p.*, dgm.is_keeper AS is_keeper
                FROM dup_group_members dgm
                JOIN photos p ON p.id = dgm.photo_id
                WHERE dgm.group_id = ?
                """,
                (group_id,),
            ).fetchall()
            members = []
            for row in member_rows:
                photo = dict(row)
                is_keeper = bool(photo.pop("is_keeper"))
                if not is_keeper:
                    rec = conn.execute(
                        "SELECT decision FROM recommendations WHERE photo_id = ? AND reason = ?",
                        (photo["id"], reason),
                    ).fetchone()
                    if rec and rec["decision"] != "pending":
                        continue  # already decided in an earlier partial pass
                members.append({"photo": photo, "is_keeper": is_keeper})
            if members:
                result[reason].append({"group_id": group_id, "members": members})

    return result


def bucket_items(items: list[dict]) -> dict[str, list[dict]]:
    """Group review items into display sections. Priority order matters only for
    which section an item shows up in when it has multiple reasons."""
    buckets: dict[str, list[dict]] = {
        "exact_duplicate": [],
        "near_duplicate": [],
        "video_near_duplicate": [],
        "blurry": [],
        "screen_recording": [],
        "video": [],
        **{category: [] for category in CONTENT_CATEGORIES},
    }
    for item in items:
        reasons = item["reasons"]
        if "exact_duplicate" in reasons:
            buckets["exact_duplicate"].append(item)
        elif "near_duplicate" in reasons:
            buckets["near_duplicate"].append(item)
        elif "video_near_duplicate" in reasons:
            buckets["video_near_duplicate"].append(item)
        elif "blurry" in reasons:
            buckets["blurry"].append(item)
        elif "screen_recording" in reasons:
            buckets["screen_recording"].append(item)
        elif "video" in reasons:
            buckets["video"].append(item)
        else:
            for category in CONTENT_CATEGORIES:
                if category in reasons:
                    buckets[category].append(item)
                    break
    return buckets


def get_no_person_months(conn) -> list[dict]:
    """Year-month buckets (newest first) with counts, for the 'photos without a
    person' browse page. This category can be huge, so grouping happens in SQL
    rather than pulling every row into Python."""
    rows = conn.execute(
        """
        SELECT
          CASE WHEN taken_at IS NOT NULL THEN strftime('%Y-%m', taken_at)
               ELSE strftime('%Y-%m', mtime, 'unixepoch') END AS year_month,
          COUNT(*) AS count
        FROM photos
        WHERE status = 'active' AND has_person = 0
        GROUP BY year_month
        ORDER BY year_month DESC
        """
    ).fetchall()
    return [{"year_month": row["year_month"], "count": row["count"]} for row in rows]


def get_no_person_photos_for_month(conn, year_month: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM photos
        WHERE status = 'active' AND has_person = 0
        AND (CASE WHEN taken_at IS NOT NULL THEN strftime('%Y-%m', taken_at)
                  ELSE strftime('%Y-%m', mtime, 'unixepoch') END) = ?
        ORDER BY COALESCE(taken_at, datetime(mtime, 'unixepoch'))
        """,
        (year_month,),
    ).fetchall()
    return [dict(row) for row in rows]


def _video_timestamp(row) -> datetime:
    if row["taken_at"]:
        try:
            return datetime.fromisoformat(row["taken_at"])
        except ValueError:
            pass
    return datetime.fromtimestamp(row["mtime"])


def get_video_sessions(conn, window_minutes: int = 30) -> list[dict]:
    """Groups active videos into 'sessions' - runs where consecutive videos (by
    taken_at, falling back to mtime) are within window_minutes of each other, so a
    batch from the same event can be reviewed together. Pure browsing aid, not a
    recommendation - recomputed fresh on every page load, same philosophy as
    get_no_person_months (no persistence, no per-session decisions to preserve)."""
    rows = conn.execute(
        "SELECT * FROM photos WHERE status = 'active' AND media_type = 'video'"
    ).fetchall()
    if not rows:
        return []

    rows = sorted(rows, key=_video_timestamp)

    sessions: list[list] = []
    current: list = []
    prev_ts = None
    for row in rows:
        ts = _video_timestamp(row)
        if prev_ts is not None and (ts - prev_ts).total_seconds() > window_minutes * 60:
            sessions.append(current)
            current = []
        current.append(row)
        prev_ts = ts
    if current:
        sessions.append(current)

    result = [
        {
            "start": _video_timestamp(members[0]).isoformat(),
            "end": _video_timestamp(members[-1]).isoformat(),
            "count": len(members),
            "videos": [dict(m) for m in members],
        }
        for members in sessions
    ]
    result.reverse()  # newest session first
    return result
