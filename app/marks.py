"""Marks: decisions the person has made but not applied yet.

Marking a photo 'remove' or 'keep' is instant, free and reversible - it only writes a
row to the marks table. Nothing touches the disk until `apply_marks`, which is the
single commit point: 'remove' marks move files to the review folder, 'keep' marks
dismiss the suggestion for good. This is the culling-software model (flag freely, act
once) and it is what makes bulk review fast without making it scary.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from .actions import _resolve_pending_recommendations, quarantine_photo
from .config import Config
from .db import log_activity
from .progress import NULL_PROGRESS, Progress

log = logging.getLogger(__name__)

VALID_MARKS = ("remove", "keep")

# Which recommendation reason belongs to which duplicate-group kind.
GROUP_REASONS = {
    "exact": "exact_duplicate",
    "near": "near_duplicate",
    "video_near": "video_near_duplicate",
}


def set_marks(conn, photo_ids: list[int], mark: str | None) -> int:
    """Set (or, with mark=None, clear) the mark on each photo. Only photos still in
    the library can be marked. Returns how many rows changed."""
    if mark is not None and mark not in VALID_MARKS:
        raise ValueError(f"invalid mark: {mark}")
    ids = list(dict.fromkeys(int(i) for i in photo_ids))
    if not ids:
        return 0

    changed = 0
    now = datetime.now(timezone.utc).isoformat()
    for start in range(0, len(ids), 500):  # stay well under SQLite's variable limit
        chunk = ids[start:start + 500]
        placeholders = ",".join("?" * len(chunk))
        if mark is None:
            cur = conn.execute(f"DELETE FROM marks WHERE photo_id IN ({placeholders})", chunk)
            changed += cur.rowcount
            continue
        active = [
            row["id"]
            for row in conn.execute(
                f"SELECT id FROM photos WHERE status = 'active' AND id IN ({placeholders})", chunk
            )
        ]
        conn.executemany(
            "INSERT INTO marks (photo_id, mark, marked_at) VALUES (?, ?, ?) "
            "ON CONFLICT(photo_id) DO UPDATE SET mark = excluded.mark, marked_at = excluded.marked_at",
            [(photo_id, mark, now) for photo_id in active],
        )
        changed += len(active)
    conn.commit()
    return changed


def clear_all_marks(conn) -> int:
    cur = conn.execute("DELETE FROM marks")
    conn.commit()
    return cur.rowcount


def mark_summary(conn) -> dict:
    row = conn.execute(
        """
        SELECT
          SUM(CASE WHEN m.mark = 'remove' THEN 1 ELSE 0 END) AS remove_count,
          SUM(CASE WHEN m.mark = 'keep'   THEN 1 ELSE 0 END) AS keep_count,
          SUM(CASE WHEN m.mark = 'remove' THEN p.size_bytes ELSE 0 END) AS remove_bytes
        FROM marks m JOIN photos p ON p.id = m.photo_id
        WHERE p.status = 'active'
        """
    ).fetchone()
    return {
        "remove": row["remove_count"] or 0,
        "keep": row["keep_count"] or 0,
        "remove_bytes": row["remove_bytes"] or 0,
    }


def get_marks(conn) -> dict[int, str]:
    return {row["photo_id"]: row["mark"] for row in conn.execute("SELECT photo_id, mark FROM marks")}


def suggest_marks(conn, group_kinds: list[str] | None = None) -> dict:
    """Pre-mark every pending duplicate group the way the app would pick it: the
    suggested keeper is marked 'keep', every other member 'remove'. The person still
    reviews the result and presses apply, so this is a starting point, not an action."""
    kinds = group_kinds or list(GROUP_REASONS)
    now = datetime.now(timezone.utc).isoformat()
    removes: list[int] = []
    keeps: list[int] = []

    for kind in kinds:
        reason = GROUP_REASONS.get(kind)
        if reason is None:
            continue
        pending_groups = conn.execute(
            """
            SELECT DISTINCT dgm.group_id AS group_id
            FROM dup_group_members dgm
            JOIN dup_groups dg ON dg.id = dgm.group_id AND dg.kind = ?
            JOIN recommendations r ON r.photo_id = dgm.photo_id AND r.reason = ? AND r.decision = 'pending'
            JOIN photos p ON p.id = dgm.photo_id AND p.status = 'active'
            WHERE dgm.is_keeper = 0
            """,
            (kind, reason),
        ).fetchall()
        for group in pending_groups:
            members = conn.execute(
                """
                SELECT dgm.photo_id AS photo_id, dgm.is_keeper AS is_keeper
                FROM dup_group_members dgm JOIN photos p ON p.id = dgm.photo_id AND p.status = 'active'
                WHERE dgm.group_id = ?
                """,
                (group["group_id"],),
            ).fetchall()
            for member in members:
                (keeps if member["is_keeper"] else removes).append(member["photo_id"])

    conn.executemany(
        "INSERT INTO marks (photo_id, mark, marked_at) VALUES (?, 'remove', ?) "
        "ON CONFLICT(photo_id) DO UPDATE SET mark = 'remove', marked_at = excluded.marked_at",
        [(i, now) for i in removes],
    )
    conn.executemany(
        "INSERT INTO marks (photo_id, mark, marked_at) VALUES (?, 'keep', ?) "
        "ON CONFLICT(photo_id) DO UPDATE SET mark = 'keep', marked_at = excluded.marked_at",
        [(i, now) for i in keeps],
    )
    conn.commit()
    return {"remove": len(removes), "keep": len(keeps)}


def apply_marks(conn, config: Config, progress: Progress = NULL_PROGRESS) -> dict:
    """Carry out every mark: move 'remove' photos to the review folder, dismiss the
    suggestions for 'keep' photos, then clear the marks that were handled. A photo
    that fails to move keeps its mark so the person can see what is left to do."""
    removes = conn.execute(
        """
        SELECT m.photo_id AS id, p.size_bytes AS size_bytes
        FROM marks m JOIN photos p ON p.id = m.photo_id
        WHERE m.mark = 'remove' AND p.status = 'active'
        """
    ).fetchall()
    keeps = conn.execute(
        "SELECT photo_id FROM marks WHERE mark = 'keep'"
    ).fetchall()

    moved_ids: list[int] = []
    failed_ids: list[int] = []
    moved_bytes = 0
    progress.start(len(removes) + len(keeps))

    for row in removes:
        progress.check()
        try:
            if quarantine_photo(conn, config, row["id"]):
                moved_ids.append(row["id"])
                moved_bytes += row["size_bytes"] or 0
                conn.execute("DELETE FROM marks WHERE photo_id = ?", (row["id"],))
        except OSError as exc:
            log.warning("Could not move photo %s: %s", row["id"], exc)
            failed_ids.append(row["id"])
        progress.advance(1)

    kept_ids: list[int] = []
    for row in keeps:
        _resolve_pending_recommendations(conn, row["photo_id"], "rejected")
        conn.execute("DELETE FROM marks WHERE photo_id = ?", (row["photo_id"],))
        kept_ids.append(row["photo_id"])
        progress.advance(1)

    if moved_ids:
        log_activity(
            conn, "removed",
            f"Moved {len(moved_ids):,} item{'s' if len(moved_ids) != 1 else ''} to the review folder",
            f"{moved_bytes}",
        )
    conn.commit()
    return {
        "moved": len(moved_ids),
        "kept": len(kept_ids),
        "failed": len(failed_ids),
        "moved_ids": moved_ids,
        "moved_bytes": moved_bytes,
    }
