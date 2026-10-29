"""Data behind the Review workspace.

A *category* is one reason the app flagged something. Duplicate-type categories are
*groups* (several photos competing with each other; one suggested keeper), the rest
are *flat* lists of individually flagged photos. Both share the same item shape so the
UI can mark, preview and compare them uniformly.
"""
from __future__ import annotations

from . import iphone
from .library import BRIEF_COLUMNS, brief

# Order matters: it is the order they appear in the sidebar. `kind` is how the UI lays
# them out; `group_kind` ties a group category to dup_groups.kind.
CATEGORIES = [
    {"key": "exact_duplicate", "label": "Exact duplicates", "kind": "group", "group_kind": "exact",
     "blurb": "Identical files. Keep one, remove the rest."},
    {"key": "near_duplicate", "label": "Similar photos", "kind": "group", "group_kind": "near",
     "blurb": "Bursts and near-identical shots. Pick the best of each set."},
    {"key": "video_near_duplicate", "label": "Similar videos", "kind": "group", "group_kind": "video_near",
     "blurb": "Clips that look like the same moment."},
    {"key": "blurry", "label": "Blurry", "kind": "flat",
     "blurb": "Softer than the rest of your library. Sharpest-looking are last."},
    {"key": "screenshot", "label": "Screenshots", "kind": "flat",
     "blurb": "Screen captures, usually safe to clear out."},
    {"key": "document", "label": "Documents and receipts", "kind": "flat",
     "blurb": "Photos of paperwork. Keep anything you might need."},
    {"key": "whiteboard", "label": "Whiteboards and notes", "kind": "flat",
     "blurb": "Photos of notes and boards."},
    {"key": "food", "label": "Food", "kind": "flat", "blurb": "Meals and plates."},
    {"key": "meme", "label": "Memes and saved images", "kind": "flat",
     "blurb": "Images saved from social media."},
    {"key": "blank", "label": "Blank or accidental", "kind": "flat",
     "blurb": "Dark, empty or pocket shots."},
    {"key": "video", "label": "Long videos", "kind": "flat",
     "blurb": "Videos over your length setting. They take the most space."},
    {"key": "screen_recording", "label": "Screen recordings", "kind": "flat",
     "blurb": "Videos of a phone screen."},
]
CATEGORY_BY_KEY = {c["key"]: c for c in CATEGORIES}


def review_overview(conn) -> dict:
    """Counts and reclaimable space per category, for the sidebar and Home."""
    stats = {c["key"]: {"count": 0, "photos": 0, "bytes": 0, "marked": 0} for c in CATEGORIES}

    # Flat categories: one row per (reason) with distinct photos, their bytes, marks.
    for row in conn.execute(
        """
        SELECT r.reason AS reason, COUNT(DISTINCT r.photo_id) AS photos, SUM(p.size_bytes) AS bytes,
               COUNT(DISTINCT CASE WHEN m.mark IS NOT NULL THEN r.photo_id END) AS marked
        FROM recommendations r
        JOIN photos p ON p.id = r.photo_id AND p.status = 'active'
        LEFT JOIN marks m ON m.photo_id = r.photo_id
        WHERE r.decision = 'pending'
        GROUP BY r.reason
        """
    ):
        entry = stats.get(row["reason"])
        if entry is not None and CATEGORY_BY_KEY[row["reason"]]["kind"] == "flat":
            entry.update(count=row["photos"], photos=row["photos"], bytes=row["bytes"] or 0, marked=row["marked"])

    # Group categories: count groups, plus the photos/bytes that could go.
    for category in CATEGORIES:
        if category["kind"] != "group":
            continue
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT dg.id) AS groups, COUNT(DISTINCT m.photo_id) AS photos,
                   SUM(p.size_bytes) AS bytes,
                   COUNT(DISTINCT CASE WHEN mk.mark IS NOT NULL THEN m.photo_id END) AS marked
            FROM dup_groups dg
            JOIN dup_group_members m ON m.group_id = dg.id AND m.is_keeper = 0
            JOIN recommendations r ON r.photo_id = m.photo_id AND r.reason = ? AND r.decision = 'pending'
            JOIN photos p ON p.id = m.photo_id AND p.status = 'active'
            LEFT JOIN marks mk ON mk.photo_id = m.photo_id
            WHERE dg.kind = ?
            """,
            (category["key"], category["group_kind"]),
        ).fetchone()
        stats[category["key"]].update(
            count=row["groups"] or 0, photos=row["photos"] or 0, bytes=row["bytes"] or 0, marked=row["marked"] or 0
        )

    categories = [{**c, **stats[c["key"]]} for c in CATEGORIES]
    flagged = conn.execute(
        """
        SELECT COUNT(*) AS photos, COALESCE(SUM(size_bytes), 0) AS bytes FROM (
            SELECT DISTINCT p.id AS id, p.size_bytes AS size_bytes
            FROM recommendations r JOIN photos p ON p.id = r.photo_id AND p.status = 'active'
            WHERE r.decision = 'pending'
        )
        """
    ).fetchone()
    return {
        "categories": categories,
        "flagged_photos": flagged["photos"],
        "flagged_bytes": flagged["bytes"],
        "duplicate_bytes": sum(c["bytes"] for c in categories if c["kind"] == "group"),
    }


def _group_why(kind: str, members: list[dict]) -> str:
    """One plain sentence on why the suggested keeper was picked - suggestions the
    person can't see the reasoning for are suggestions they can't trust."""
    keeper = next((m for m in members if m["keeper"]), None)
    others = [m for m in members if not m["keeper"]]
    if keeper is None or not others:
        return ""
    if kind == "exact":
        return "Identical files. Kept the first one found."
    if kind == "video_near":
        if (keeper["dur"] or 0) > max((o["dur"] or 0) for o in others):
            return "Longest clip, so most likely the complete take."
        return "Largest file of the set."
    if any(iphone.is_edit_of(keeper["name"], o["name"]) for o in others):
        return "Your edited version. The original is the rest of this set."
    keeper_px = (keeper["w"] or 0) * (keeper["h"] or 0)
    if keeper_px > max((o["w"] or 0) * (o["h"] or 0) for o in others):
        return f"Highest resolution ({keeper_px / 1e6:.1f} MP)."
    blurs = [o["blur"] for o in others if o["blur"] is not None]
    if keeper["blur"] is not None and blurs and keeper["blur"] >= max(blurs):
        return "Sharpest of the set."
    return "Best overall match."


def list_category(conn, key: str, offset: int = 0, limit: int = 40) -> dict:
    category = CATEGORY_BY_KEY.get(key)
    if category is None:
        raise KeyError(key)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    if category["kind"] == "group":
        return _list_groups(conn, category, offset, limit)

    order = {
        "blurry": "p.blur_score ASC, p.id",
        "video": "p.duration_seconds DESC, p.id",
        "screen_recording": "p.duration_seconds DESC, p.id",
    }.get(key, "r.confidence DESC, p.id")
    base = (
        "FROM recommendations r JOIN photos p ON p.id = r.photo_id AND p.status = 'active' "
        "LEFT JOIN marks m ON m.photo_id = p.id "
        "WHERE r.reason = ? AND r.decision = 'pending'"
    )
    # One recommendation per (photo, reason) by construction, so no DISTINCT needed.
    total = conn.execute(f"SELECT COUNT(*) c {base}", (key,)).fetchone()["c"]
    rows = conn.execute(
        f"SELECT {BRIEF_COLUMNS}, r.confidence AS confidence {base} ORDER BY {order} LIMIT ? OFFSET ?",
        (key, limit, offset),
    ).fetchall()
    items = []
    for row in rows:
        item = brief(row)
        item["confidence"] = row["confidence"]
        items.append(item)
    result = {"category": category, "total": total, "offset": offset, "items": items}
    if offset == 0:
        # Every id in display order, sent once so the UI can select ranges and "mark all"
        # without paging through a 50,000-photo category.
        result["ids"] = [r["id"] for r in conn.execute(f"SELECT p.id AS id {base} ORDER BY {order}", (key,))]
    return result


def _list_groups(conn, category: dict, offset: int, limit: int) -> dict:
    key, kind = category["key"], category["group_kind"]
    pending = """
        FROM dup_groups dg
        JOIN dup_group_members m ON m.group_id = dg.id AND m.is_keeper = 0
        JOIN recommendations r ON r.photo_id = m.photo_id AND r.reason = ? AND r.decision = 'pending'
        JOIN photos p ON p.id = m.photo_id AND p.status = 'active'
        WHERE dg.kind = ?
    """
    total = conn.execute(f"SELECT COUNT(DISTINCT dg.id) c {pending}", (key, kind)).fetchone()["c"]
    group_rows = conn.execute(
        f"SELECT dg.id AS id, SUM(p.size_bytes) AS reclaim {pending} "
        f"GROUP BY dg.id ORDER BY reclaim DESC, dg.id LIMIT ? OFFSET ?",
        (key, kind, limit, offset),
    ).fetchall()
    group_ids = [g["id"] for g in group_rows]

    members_by_group: dict[int, list[dict]] = {gid: [] for gid in group_ids}
    if group_ids:
        placeholders = ",".join("?" * len(group_ids))
        rows = conn.execute(
            f"""
            SELECT {BRIEF_COLUMNS}, dgm.group_id AS group_id, dgm.is_keeper AS is_keeper
            FROM dup_group_members dgm
            JOIN photos p ON p.id = dgm.photo_id AND p.status = 'active'
            LEFT JOIN marks m ON m.photo_id = p.id
            LEFT JOIN recommendations r
              ON r.photo_id = p.id AND r.reason = ? AND r.decision = 'pending'
            WHERE dgm.group_id IN ({placeholders}) AND (dgm.is_keeper = 1 OR r.id IS NOT NULL)
            """,
            (key, *group_ids),
        ).fetchall()
        for row in rows:
            item = brief(row)
            item["keeper"] = bool(row["is_keeper"])
            members_by_group[row["group_id"]].append(item)

    groups = []
    for g in group_rows:
        members = sorted(
            members_by_group[g["id"]],
            key=lambda m: (not m["keeper"], -((m["w"] or 0) * (m["h"] or 0)), m["id"]),
        )
        groups.append({
            "id": g["id"],
            "reclaim": g["reclaim"] or 0,
            "why": _group_why(kind, members),
            "members": members,
        })
    return {"category": category, "total": total, "offset": offset, "groups": groups}
