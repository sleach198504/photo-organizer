from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .fsutil import unique_destination

log = logging.getLogger(__name__)


def _relative_dest(src: Path, source_dir: Path, quarantine_dir: Path) -> Path:
    try:
        rel = src.resolve().relative_to(source_dir.resolve())
    except ValueError:
        # Photo was indexed under a source_dir this install no longer points at -
        # fall back to just the filename rather than failing the whole move.
        rel = Path(src.name)
    return quarantine_dir / rel


def _resolve_pending_recommendations(conn, photo_id: int, decision: str) -> None:
    """Whenever a photo actually gets moved, close out any recommendations still
    sitting 'pending' for it - otherwise a photo quarantined via a path that
    doesn't go through decide() (e.g. the no-person browse page's batch-select)
    leaves a stale card pointing at an already-moved photo on the review page."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE recommendations SET decision = ?, decided_at = ? WHERE photo_id = ? AND decision = 'pending'",
        (decision, now, photo_id),
    )


def quarantine_photo(conn, config: Config, photo_id: int) -> bool:
    """Move a photo (and its Live Photo video pair, if any) into the review/quarantine
    folder. Safe to call more than once for the same photo - a no-op if it's already
    been moved. Returns True if a move actually happened."""
    row = conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
    if row is None or row["status"] != "active":
        return False

    src = Path(row["path"])
    if not src.exists():
        log.warning("Photo %s no longer exists on disk at %s - marking quarantined anyway", photo_id, src)
        conn.execute("UPDATE photos SET status = 'quarantined' WHERE id = ?", (photo_id,))
        _resolve_pending_recommendations(conn, photo_id, "approved")
        return True

    dest = unique_destination(_relative_dest(src, config.source_dir, config.quarantine_dir))
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))

    new_live_pair = None
    if row["live_pair_path"]:
        live_src = Path(row["live_pair_path"])
        if live_src.exists():
            live_dest = unique_destination(dest.with_suffix(live_src.suffix))
            shutil.move(str(live_src), str(live_dest))
            new_live_pair = str(live_dest)

    conn.execute(
        "UPDATE photos SET status = 'quarantined', path = ?, live_pair_path = ? WHERE id = ?",
        (str(dest), new_live_pair, photo_id),
    )
    _resolve_pending_recommendations(conn, photo_id, "approved")
    return True


def decide(conn, config: Config, photo_id: int, decision: str) -> None:
    if decision not in ("approved", "rejected"):
        raise ValueError(f"invalid decision: {decision}")

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE recommendations SET decision = ?, decided_at = ? WHERE photo_id = ? AND decision = 'pending'",
        (decision, now, photo_id),
    )
    if decision == "approved":
        quarantine_photo(conn, config, photo_id)
    conn.commit()


def quarantine_photos_batch(conn, config: Config, photo_ids: list[int]) -> dict:
    """For manual multi-select actions (e.g. the 'photos without a person' browse
    page) that aren't tied to a recommendation - moves each photo directly."""
    moved = 0
    for photo_id in photo_ids:
        if quarantine_photo(conn, config, photo_id):
            moved += 1
    conn.commit()
    return {"moved": moved}


def execute_approved_recommendations(conn, config: Config) -> int:
    """Move any photo that's already 'approved' but not yet moved - covers
    auto_quarantine_exact_duplicates, which marks recommendations approved at
    analysis time without moving the file itself."""
    rows = conn.execute(
        """
        SELECT DISTINCT r.photo_id
        FROM recommendations r
        JOIN photos p ON p.id = r.photo_id
        WHERE r.decision = 'approved' AND p.status = 'active'
        """
    ).fetchall()
    count = 0
    for row in rows:
        if quarantine_photo(conn, config, row["photo_id"]):
            count += 1
    conn.commit()
    return count


def get_quarantine_stats(conn) -> dict:
    """Reports what's actually sitting in the review folder right now, not just
    what the database last recorded - a row whose file was removed outside the
    app (by hand, antivirus, etc.) is dropped here rather than left to inflate
    the count or let a later purge silently no-op on a photo that isn't there."""
    rows = conn.execute(
        "SELECT id, path, live_pair_path, size_bytes FROM photos WHERE status = 'quarantined'"
    ).fetchall()
    total_bytes = 0
    count = 0
    for row in rows:
        if not Path(row["path"]).exists():
            conn.execute("DELETE FROM photos WHERE id = ?", (row["id"],))
            continue
        count += 1
        total_bytes += row["size_bytes"] or 0
        if row["live_pair_path"]:
            try:
                total_bytes += Path(row["live_pair_path"]).stat().st_size
            except OSError:
                pass
    conn.commit()
    return {"count": count, "total_bytes": total_bytes}


def _remove_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
        d = Path(dirpath)
        if d == root:
            continue
        try:
            if not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass


def purge_quarantined(conn, config: Config) -> dict:
    """Permanently delete every photo currently sitting in the review/quarantine
    folder. Irreversible - the caller is responsible for confirming with the user
    first (this function does not ask)."""
    rows = conn.execute(
        "SELECT id, path, live_pair_path FROM photos WHERE status = 'quarantined'"
    ).fetchall()

    deleted = 0
    errors = 0
    freed_bytes = 0
    for row in rows:
        path = Path(row["path"])
        try:
            if path.exists():
                freed_bytes += path.stat().st_size
                path.unlink()
            if row["live_pair_path"]:
                live_path = Path(row["live_pair_path"])
                if live_path.exists():
                    freed_bytes += live_path.stat().st_size
                    live_path.unlink()
            conn.execute("DELETE FROM photos WHERE id = ?", (row["id"],))
            deleted += 1
        except OSError as exc:
            log.warning("Failed to delete %s: %s", path, exc)
            errors += 1
    conn.commit()

    _remove_empty_dirs(config.quarantine_dir)
    return {"deleted": deleted, "errors": errors, "freed_bytes": freed_bytes}
