from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import pillow_heif
from PIL import Image

from . import video_frames
from .db import CURRENT_META_VERSION
from .hashing import perceptual_hash, sha256_file
from .metadata import extract_photo_metadata, extract_video_metadata
from .progress import NULL_PROGRESS, Progress

pillow_heif.register_heif_opener()

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
LIVE_PAIR_EXTS = {".mov", ".mp4"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v"}

# Folders the OS or other tools create that never hold the person's own photos.
_SKIPPED_DIR_NAMES = {"$recycle.bin", "system volume information"}

# Known iPhone screen-recording pixel dimensions (device native resolution -
# point resolution x scale factor). Screen recordings are captured at the exact
# display resolution, which is a very different shape from ordinary camera video
# (1920x1080, 3840x2160, 1280x720, etc). This is a best-effort heuristic, not a
# certain signal - newer/older devices not in this list won't be caught, and it's
# always just a reviewable flag, never used to auto-quarantine anything.
SCREEN_RECORDING_DIMENSIONS = {
    (640, 1136),    # iPhone 5/5s/SE (1st gen)
    (750, 1334),    # iPhone 6/6s/7/8/SE (2nd/3rd gen)
    # iPhone 6+/6s+/7+/8+ portrait (1080x1920) is deliberately NOT listed here:
    # its landscape transpose, 1920x1080, is standard 1080p Full HD - the single
    # most common ordinary camera-video resolution there is. Including it would
    # misflag a large fraction of completely normal videos.
    (1125, 2436),   # iPhone X/XS/11 Pro
    (828, 1792),    # iPhone XR/11
    (1242, 2688),   # iPhone XS Max/11 Pro Max
    (1080, 2340),   # iPhone 12 mini/13 mini
    (1170, 2532),   # iPhone 12/12 Pro/13/13 Pro/14
    (1284, 2778),   # iPhone 12 Pro Max/13 Pro Max/14 Plus/14 Pro Max
    (1179, 2556),   # iPhone 14 Pro/15/15 Pro/16/16 Pro
    (1290, 2796),   # iPhone 15 Plus/15 Pro Max/16 Plus/16 Pro Max
}


def looks_like_screen_recording(width: int | None, height: int | None) -> bool:
    if not width or not height:
        return False
    dims = (width, height)
    return dims in SCREEN_RECORDING_DIMENSIONS or (dims[1], dims[0]) in SCREEN_RECORDING_DIMENSIONS


# Screens whose shape is close to an ordinary photo's, so the shape alone proves nothing:
# tablets, laptops and the 3:2 and 16:10 screens in between. Matched by exact size.
SCREEN_SIZES_LIKE_PHOTOS = {
    (2048, 1536), (2732, 2048), (2360, 1640), (2388, 1668), (2266, 1488), (2160, 1620), (1668, 1194),
    (2224, 1668), (2736, 1824), (2880, 1920), (3000, 2000), (1920, 1200), (2560, 1600), (2880, 1800),
    (1280, 800), (1440, 900), (1680, 1050),
}
MIN_SCREEN_SHORT_EDGE = 600  # a thumbnail-sized PNG is a saved picture, not a screen capture
TALL_SCREEN_RATIO = 1.7      # long edge / short edge: phones and 16:9 and wider desktop screens


def looks_like_screenshot(
    path: Path, camera_model: str | None, width: int | None = None, height: int | None = None
) -> bool:
    """Metadata-only screenshot check - no model inference needed, and far more
    reliable than a vision model's guess. A phone/computer screenshot is (a)
    saved as PNG (iOS and Android's screen-capture format; a camera photo is
    HEIC/JPG), (b) carries no camera Model EXIF tag, since nothing actually
    photographed it, and (c) is the shape of a screen. Photos re-saved as PNG by an
    editor also have (a) and (b), but they keep a photo's 4:3 or 3:2 shape; (c) tells
    the two apart. Without a size, the first two decide, as before."""
    if path.suffix.lower() != ".png" or camera_model:
        return False
    if not width or not height:
        return True
    short, long = sorted((width, height))
    if short < MIN_SCREEN_SHORT_EDGE:
        return False
    return long / short >= TALL_SCREEN_RATIO or (long, short) in SCREEN_SIZES_LIKE_PHOTOS


def scan_folder(source_dir: Path, exclude_dir: Path | None = None) -> tuple[list[Path], list[Path]]:
    """Every image and video under source_dir, skipping the review folder (and any
    hidden or OS-internal folders) entirely rather than testing each file against
    it - one prune of a directory is far cheaper than resolving every path."""
    exclude_norm = os.path.normcase(os.path.abspath(exclude_dir)) if exclude_dir else None
    images: list[Path] = []
    videos: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(source_dir):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".")
            and d.lower() not in _SKIPPED_DIR_NAMES
            and os.path.normcase(os.path.abspath(os.path.join(dirpath, d))) != exclude_norm
        ]
        for name in filenames:
            suffix = os.path.splitext(name)[1].lower()
            if suffix in IMAGE_EXTS:
                images.append(Path(dirpath, name))
            elif suffix in VIDEO_EXTS:
                videos.append(Path(dirpath, name))
    images.sort()
    videos.sort()
    return images, videos


def find_live_pair(image_path: Path) -> Path | None:
    stem = image_path.with_suffix("")
    for ext in LIVE_PAIR_EXTS:
        candidate = stem.with_suffix(ext)
        if candidate.exists():
            return candidate
    return None


def _refresh_metadata(conn, row_id: int, path: Path, is_video: bool) -> bool:
    """Re-read capture date/GPS for a file that hasn't changed on disk - used when
    the indexer learns to read something it used to miss (see CURRENT_META_VERSION).
    Cheap: opens the file header only, no hashing or pixel decoding."""
    try:
        if is_video:
            meta = extract_video_metadata(path)
        else:
            with Image.open(path) as img:
                meta = extract_photo_metadata(img)
    except Exception as exc:
        log.warning("Could not refresh metadata for %s: %s", path, exc)
        meta = {"taken_at": None, "camera_model": None, "gps_lat": None, "gps_lon": None}

    conn.execute(
        """
        UPDATE photos SET
            taken_at = COALESCE(?, taken_at),
            camera_model = COALESCE(?, camera_model),
            gps_lat = COALESCE(?, gps_lat),
            gps_lon = COALESCE(?, gps_lon),
            meta_version = ?
        WHERE id = ?
        """,
        (meta["taken_at"], meta["camera_model"], meta["gps_lat"], meta["gps_lon"], CURRENT_META_VERSION, row_id),
    )
    return True


def index_photo(conn, path: Path) -> bool:
    """Index or refresh a single photo. Returns True if the DB row changed."""
    stat = path.stat()
    existing = conn.execute(
        "SELECT id, size_bytes, mtime, meta_version FROM photos WHERE path = ?", (str(path),)
    ).fetchone()
    if existing and existing["size_bytes"] == stat.st_size and existing["mtime"] == stat.st_mtime:
        if existing["meta_version"] >= CURRENT_META_VERSION:
            return False
        return _refresh_metadata(conn, existing["id"], path, is_video=False)

    sha256 = sha256_file(path)
    live_pair = find_live_pair(path)

    error = None
    phash = width = height = None
    meta = {"taken_at": None, "camera_model": None, "gps_lat": None, "gps_lon": None}
    try:
        with Image.open(path) as img:
            img.load()
            width, height = img.size
            phash = perceptual_hash(img)
            meta = extract_photo_metadata(img)
    except Exception as exc:
        error = str(exc)
        log.warning("Failed to process %s: %s", path, exc)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO photos (
            path, live_pair_path, size_bytes, mtime, sha256, phash,
            width, height, taken_at, camera_model, gps_lat, gps_lon,
            status, indexed_at, error, meta_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            live_pair_path=excluded.live_pair_path,
            size_bytes=excluded.size_bytes,
            mtime=excluded.mtime,
            sha256=excluded.sha256,
            phash=excluded.phash,
            width=excluded.width,
            height=excluded.height,
            taken_at=excluded.taken_at,
            camera_model=excluded.camera_model,
            gps_lat=excluded.gps_lat,
            gps_lon=excluded.gps_lon,
            indexed_at=excluded.indexed_at,
            error=excluded.error,
            meta_version=excluded.meta_version
        """,
        (
            str(path), str(live_pair) if live_pair else None, stat.st_size, stat.st_mtime,
            sha256, phash, width, height, meta["taken_at"], meta["camera_model"],
            meta["gps_lat"], meta["gps_lon"], now, error, CURRENT_META_VERSION,
        ),
    )
    return True


def index_video(conn, path: Path) -> bool:
    """Index or refresh a single standalone video (not a Live Photo pair - those
    are indexed as part of their still image via index_photo). Returns True if
    the DB row changed."""
    stat = path.stat()
    existing = conn.execute(
        "SELECT id, size_bytes, mtime, meta_version FROM photos WHERE path = ?", (str(path),)
    ).fetchone()
    if existing and existing["size_bytes"] == stat.st_size and existing["mtime"] == stat.st_mtime:
        if existing["meta_version"] >= CURRENT_META_VERSION:
            return False
        return _refresh_metadata(conn, existing["id"], path, is_video=True)

    sha256 = sha256_file(path)

    error = None
    phash = width = height = duration = None
    is_screen_recording = None
    cap = video_frames.open_capture(path)
    try:
        if not cap.isOpened():
            raise RuntimeError("could not open video file")
        width = int(cap.get(video_frames.cv2.CAP_PROP_FRAME_WIDTH)) or None
        height = int(cap.get(video_frames.cv2.CAP_PROP_FRAME_HEIGHT)) or None
        duration = video_frames.get_duration_seconds(cap)
        frame = video_frames.grab_middle_frame(cap)
        if frame is not None:
            phash = perceptual_hash(frame)
        is_screen_recording = 1 if looks_like_screen_recording(width, height) else 0
    except Exception as exc:
        error = str(exc)
        log.warning("Failed to process video %s: %s", path, exc)
    finally:
        cap.release()

    meta = extract_video_metadata(path)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO photos (
            path, live_pair_path, size_bytes, mtime, sha256, phash,
            width, height, taken_at, camera_model, gps_lat, gps_lon,
            media_type, duration_seconds, is_screen_recording,
            status, indexed_at, error, meta_version
        ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 'video', ?, ?, 'active', ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            size_bytes=excluded.size_bytes,
            mtime=excluded.mtime,
            sha256=excluded.sha256,
            phash=excluded.phash,
            width=excluded.width,
            height=excluded.height,
            taken_at=excluded.taken_at,
            gps_lat=excluded.gps_lat,
            gps_lon=excluded.gps_lon,
            duration_seconds=excluded.duration_seconds,
            is_screen_recording=excluded.is_screen_recording,
            indexed_at=excluded.indexed_at,
            error=excluded.error,
            meta_version=excluded.meta_version
        """,
        (
            str(path), stat.st_size, stat.st_mtime, sha256, phash, width, height,
            meta["taken_at"], meta["gps_lat"], meta["gps_lon"],
            duration, is_screen_recording, now, error, CURRENT_META_VERSION,
        ),
    )
    return True


def run_index(
    conn, source_dir: Path, exclude_dir: Path | None = None, progress: Progress = NULL_PROGRESS
) -> dict:
    stats = {"scanned": 0, "indexed": 0, "skipped": 0, "errors": 0}

    progress.start(None, "Looking through your folder...")
    images, videos = scan_folder(source_dir, exclude_dir)
    progress.check()

    # A Live Photo's motion clip shares its still's name; it's indexed as part of
    # the still, not as a separate video.
    claimed_live_pairs = {pair for pair in (find_live_pair(p) for p in images) if pair}
    videos = [v for v in videos if v not in claimed_live_pairs]

    total = len(images) + len(videos)
    progress.start(total, f"Found {total:,} files")

    for path, indexer in [(p, index_photo) for p in images] + [(v, index_video) for v in videos]:
        progress.check()
        stats["scanned"] += 1
        try:
            changed = indexer(conn, path)
        except OSError as exc:
            log.warning("Could not read %s: %s", path, exc)
            stats["errors"] += 1
            progress.advance(1, path.name)
            continue
        stats["indexed" if changed else "skipped"] += 1
        progress.advance(1, path.name)
        if stats["scanned"] % 200 == 0:
            conn.commit()

    conn.commit()
    row = conn.execute("SELECT COUNT(*) c FROM photos WHERE error IS NOT NULL").fetchone()
    stats["errors"] = row["c"]
    return stats


MEDIUM_VIDEO_SECONDS = 60
LONG_VIDEO_SECONDS = 300
VIDEO_REVIEW_MODES = ("off", "all", "medium", "long")


def flag_videos_for_review(conn, mode: str) -> int:
    """Creates 'video' recommendations for active videos matching the configured
    review mode. Idempotent - skips videos that already have any decision recorded
    for this reason, same pattern as quality.flag_blurry_photos."""
    if mode not in VIDEO_REVIEW_MODES:
        raise ValueError(f"invalid video_review_mode: {mode}")
    if mode == "off":
        return 0

    if mode == "all":
        rows = conn.execute(
            "SELECT id FROM photos WHERE status = 'active' AND media_type = 'video'"
        ).fetchall()
    else:
        threshold = MEDIUM_VIDEO_SECONDS if mode == "medium" else LONG_VIDEO_SECONDS
        rows = conn.execute(
            "SELECT id FROM photos WHERE status = 'active' AND media_type = 'video' "
            "AND duration_seconds >= ?",
            (threshold,),
        ).fetchall()

    count = 0
    for row in rows:
        existing = conn.execute(
            "SELECT id FROM recommendations WHERE photo_id = ? AND reason = 'video'", (row["id"],)
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO recommendations (photo_id, reason, confidence, decision) VALUES (?, 'video', NULL, 'pending')",
            (row["id"],),
        )
        count += 1
    conn.commit()
    return count


def flag_screen_recordings(conn) -> int:
    """Creates 'screen_recording' recommendations for active videos the heuristic
    flagged. Idempotent, same pattern as flag_videos_for_review."""
    rows = conn.execute(
        "SELECT id FROM photos WHERE status = 'active' AND media_type = 'video' AND is_screen_recording = 1"
    ).fetchall()
    count = 0
    for row in rows:
        existing = conn.execute(
            "SELECT id FROM recommendations WHERE photo_id = ? AND reason = 'screen_recording'", (row["id"],)
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO recommendations (photo_id, reason, confidence, decision) VALUES (?, 'screen_recording', NULL, 'pending')",
            (row["id"],),
        )
        count += 1
    conn.commit()
    return count
