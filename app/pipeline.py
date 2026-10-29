"""The scan and organize runners (executed on a background thread).

Each stage is idempotent - it only touches rows it hasn't processed yet - so a scan
that is cancelled, crashes, or is interrupted by closing the window simply resumes
where it stopped next time.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from . import content_tagging
from .actions import execute_approved_recommendations
from .config import Config
from .db import log_activity, session, set_meta
from .dedupe import run_dedupe
from .indexer import flag_screen_recordings, flag_videos_for_review, run_index
from .jobs import Job
from .marks import apply_marks
from .media import warmer
from .organize import run_organize, undo_organize
from .progress import Cancelled
from .quality import flag_blurry_photos, run_quality_scoring
from .review import review_overview
from .settings import VIDEO_SEARCH_DEPTHS
from .trips import run_trip_detection

log = logging.getLogger(__name__)

SCAN_STAGES = [
    ("index", "Reading your photos and videos"),
    ("sharpness", "Checking sharpness"),
    ("duplicates", "Finding duplicates and similar shots"),
    ("content", "Recognizing what is in your photos"),
    ("video_search", "Indexing videos for search"),
    ("finish", "Wrapping up"),
]

ORGANIZE_STAGES = [("move", "Filing your photos")]
UNDO_ORGANIZE_STAGES = [("move", "Putting your photos back")]


class _WarningCapture(logging.Handler):
    """Surfaces the app's own warnings (a file that couldn't be read, ...) on the job
    so the UI can say 'N files had problems' instead of silently dropping them."""

    def __init__(self, job: Job) -> None:
        super().__init__(level=logging.WARNING)
        self.job = job

    def emit(self, record: logging.LogRecord) -> None:
        self.job.warn(record.getMessage())


def run_scan(job: Job, config: Config, settings: dict) -> None:
    capture = _WarningCapture(job)
    app_logger = logging.getLogger("app")
    app_logger.addHandler(capture)
    started = time.time()
    try:
        with session(config.db_path) as conn:
            # 1. Read every file
            progress = job.begin("index")
            index_stats = run_index(conn, config.source_dir, exclude_dir=config.quarantine_dir, progress=progress)
            flag_videos_for_review(conn, settings["video_review_mode"])
            flag_screen_recordings(conn)
            job.end("index", note=f"{index_stats['scanned']:,} files, {index_stats['indexed']:,} new or changed")

            # 2. Sharpness
            progress = job.begin("sharpness")
            run_quality_scoring(conn, progress)
            flag_blurry_photos(conn)
            job.end("sharpness")

            # 3. Duplicates and similar shots
            progress = job.begin("duplicates")
            progress.start(1, "Comparing photos")
            dedupe_stats = run_dedupe(conn, config.near_duplicate_hash_distance, config.auto_quarantine_exact_duplicates)
            progress.advance(1)
            job.end(
                "duplicates",
                note=(
                    f"{dedupe_stats['exact_groups']:,} exact, {dedupe_stats['near_groups']:,} similar photo "
                    f"and {dedupe_stats['video_near_groups']:,} similar video groups"
                ),
            )

            # 4 + 5. Content recognition and video search (need the model)
            backend, unavailable = None, "The recognition model isn't installed. Run Setup again to install it."
            if content_tagging.models_downloaded():
                job.begin("content").detail("Loading the recognition model")
                try:
                    backend = content_tagging.create_backend()
                except content_tagging.ModelUnavailable as exc:
                    unavailable = str(exc)
            if backend:
                progress = job.begin("content")
                tag_stats = content_tagging.run_content_tagging(conn, backend, progress)
                job.end("content", note=f"{tag_stats['tagged']:,} photos checked")

                progress = job.begin("video_search")
                interval = VIDEO_SEARCH_DEPTHS.get(settings["video_search_depth"], 10.0)
                content_tagging.run_video_frame_embedding(conn, backend, interval, progress)
                job.end("video_search")
            else:
                job.skip("content", unavailable)
                job.skip("video_search", "Needs the recognition model.")

            # 6. Finish
            progress = job.begin("finish")
            progress.start(None, "Finishing up")
            auto_removed = execute_approved_recommendations(conn, config)
            try:
                run_trip_detection(conn)
            except Exception as exc:  # trips are a bonus; never fail a scan over them
                log.warning("Trip detection skipped: %s", exc)
            set_meta(conn, "last_scan_at", datetime.now(timezone.utc).isoformat())
            overview = review_overview(conn)
            log_activity(
                conn, "scan",
                f"Scanned {index_stats['scanned']:,} items",
                f"{overview['flagged_photos']:,} flagged for review",
            )
            conn.commit()
            job.end("finish")

        warmer.start(config.db_path)
        job.finish({
            "scanned": index_stats["scanned"],
            "changed": index_stats["indexed"],
            "problems": index_stats["errors"],
            "online_only": index_stats["online_only"],
            "flagged": overview["flagged_photos"],
            "auto_removed": auto_removed,
            "seconds": round(time.time() - started, 1),
        })
    except Cancelled:
        job.mark_cancelled()
    except Exception as exc:  # noqa: BLE001 - shown to a non-technical user, must not crash silently
        log.exception("Scan failed")
        job.fail(str(exc))
    finally:
        app_logger.removeHandler(capture)


def run_organize_job(
    job: Job, config: Config, dest_root: Path, excluded: set[str], exclude_mode: str, template: str
) -> None:
    capture = _WarningCapture(job)
    logging.getLogger("app").addHandler(capture)
    try:
        with session(config.db_path) as conn:
            progress = job.begin("move")
            stats = run_organize(conn, dest_root, config.source_dir, excluded, exclude_mode, template, progress)
            job.end("move")
        job.finish({"moved": stats["moved"], "skipped": stats["skipped"], "problems": stats["errors"], "dest": str(dest_root)})
    except Cancelled:
        job.mark_cancelled()
    except Exception as exc:  # noqa: BLE001
        log.exception("Organize failed")
        job.fail(str(exc))
    finally:
        logging.getLogger("app").removeHandler(capture)


def run_undo_organize_job(job: Job, config: Config) -> None:
    """Put the photos from the most recent Organize back where they came from."""
    capture = _WarningCapture(job)
    logging.getLogger("app").addHandler(capture)
    try:
        with session(config.db_path) as conn:
            progress = job.begin("move")
            stats = undo_organize(conn, progress)
            job.end("move")
        job.finish({"restored": stats["restored"], "missing": stats["missing"],
                    "renamed": stats["renamed"], "problems": stats["failed"]})
    except Cancelled:
        job.mark_cancelled()
    except Exception as exc:  # noqa: BLE001
        log.exception("Undoing Organize failed")
        job.fail(str(exc))
    finally:
        logging.getLogger("app").removeHandler(capture)


def run_apply_job(job: Job, config: Config) -> None:
    """Carry out every pending mark (move 'remove' photos to the review folder)."""
    try:
        with session(config.db_path) as conn:
            progress = job.begin("move")
            result = apply_marks(conn, config, progress)
            job.end("move")
        job.finish(result)
    except Cancelled:
        job.mark_cancelled()
    except Exception as exc:  # noqa: BLE001
        log.exception("Applying marks failed")
        job.fail(str(exc))
