from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pillow_heif
from PIL import ExifTags, Image

from . import video_frames
from .hashing import perceptual_hash, sha256_file

pillow_heif.register_heif_opener()

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
LIVE_PAIR_EXTS = {".mov", ".mp4"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v"}

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


def looks_like_screenshot(path: Path, camera_model: str | None) -> bool:
    """Metadata-only screenshot check - no model inference needed, and far more
    reliable than a vision model's guess. A phone/computer screenshot is (a)
    saved as PNG (iOS and Android's screen-capture format; a camera photo is
    HEIC/JPG) and (b) carries no camera Model EXIF tag, since nothing actually
    photographed it. Requiring both keeps this from misflagging the rare real
    photo that happens to be saved as PNG but still has a camera Model."""
    return path.suffix.lower() == ".png" and not camera_model


GPS_TAG = next((k for k, v in ExifTags.TAGS.items() if v == "GPSInfo"), None)
DATETIME_ORIGINAL_TAG = next((k for k, v in ExifTags.TAGS.items() if v == "DateTimeOriginal"), None)
MODEL_TAG = next((k for k, v in ExifTags.TAGS.items() if v == "Model"), None)


def iter_image_files(source_dir: Path, exclude_dir: Path | None = None):
    exclude_resolved = exclude_dir.resolve() if exclude_dir else None
    for path in source_dir.rglob("*"):
        if exclude_resolved is not None:
            try:
                if path.resolve().is_relative_to(exclude_resolved):
                    continue
            except OSError:
                pass
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            yield path


def iter_video_files(source_dir: Path, exclude_dir: Path | None = None):
    exclude_resolved = exclude_dir.resolve() if exclude_dir else None
    for path in source_dir.rglob("*"):
        if exclude_resolved is not None:
            try:
                if path.resolve().is_relative_to(exclude_resolved):
                    continue
            except OSError:
                pass
        if path.is_file() and path.suffix.lower() in VIDEO_EXTS:
            yield path


def find_live_pair(image_path: Path) -> Path | None:
    stem = image_path.with_suffix("")
    for ext in LIVE_PAIR_EXTS:
        candidate = stem.with_suffix(ext)
        if candidate.exists():
            return candidate
    return None


def _to_degrees(value) -> float:
    d, m, s = value
    return float(d) + float(m) / 60 + float(s) / 3600


def extract_exif(image: Image.Image) -> dict:
    result = {"taken_at": None, "camera_model": None, "gps_lat": None, "gps_lon": None}
    exif = image.getexif()
    if not exif:
        return result

    if DATETIME_ORIGINAL_TAG and DATETIME_ORIGINAL_TAG in exif:
        raw = exif[DATETIME_ORIGINAL_TAG]
        try:
            result["taken_at"] = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S").isoformat()
        except (ValueError, TypeError):
            pass

    if MODEL_TAG and MODEL_TAG in exif:
        result["camera_model"] = str(exif[MODEL_TAG]).strip("\x00").strip()

    gps_ifd = None
    if GPS_TAG:
        try:
            gps_ifd = exif.get_ifd(GPS_TAG)
        except Exception:
            gps_ifd = None
    if gps_ifd:
        try:
            lat = _to_degrees(gps_ifd[2])
            if gps_ifd.get(1) == "S":
                lat = -lat
            lon = _to_degrees(gps_ifd[4])
            if gps_ifd.get(3) == "W":
                lon = -lon
            result["gps_lat"] = lat
            result["gps_lon"] = lon
        except (KeyError, TypeError, ZeroDivisionError):
            pass

    return result


def index_photo(conn, path: Path) -> bool:
    """Index or refresh a single photo. Returns True if the DB row changed."""
    stat = path.stat()
    existing = conn.execute(
        "SELECT id, size_bytes, mtime FROM photos WHERE path = ?", (str(path),)
    ).fetchone()
    if existing and existing["size_bytes"] == stat.st_size and existing["mtime"] == stat.st_mtime:
        return False

    sha256 = sha256_file(path)
    live_pair = find_live_pair(path)

    error = None
    phash = width = height = None
    exif_data = {"taken_at": None, "camera_model": None, "gps_lat": None, "gps_lon": None}
    try:
        with Image.open(path) as img:
            img.load()
            width, height = img.size
            phash = perceptual_hash(img)
            exif_data = extract_exif(img)
    except Exception as exc:
        error = str(exc)
        log.warning("Failed to process %s: %s", path, exc)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO photos (
            path, live_pair_path, size_bytes, mtime, sha256, phash,
            width, height, taken_at, camera_model, gps_lat, gps_lon,
            status, indexed_at, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
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
            error=excluded.error
        """,
        (
            str(path), str(live_pair) if live_pair else None, stat.st_size, stat.st_mtime,
            sha256, phash, width, height, exif_data["taken_at"], exif_data["camera_model"],
            exif_data["gps_lat"], exif_data["gps_lon"], now, error,
        ),
    )
    return True


def index_video(conn, path: Path) -> bool:
    """Index or refresh a single standalone video (not a Live Photo pair - those
    are indexed as part of their still image via index_photo). Returns True if
    the DB row changed."""
    stat = path.stat()
    existing = conn.execute(
        "SELECT id, size_bytes, mtime FROM photos WHERE path = ?", (str(path),)
    ).fetchone()
    if existing and existing["size_bytes"] == stat.st_size and existing["mtime"] == stat.st_mtime:
        return False

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

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO photos (
            path, live_pair_path, size_bytes, mtime, sha256, phash,
            width, height, taken_at, camera_model, gps_lat, gps_lon,
            media_type, duration_seconds, is_screen_recording,
            status, indexed_at, error
        ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, 'video', ?, ?, 'active', ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            size_bytes=excluded.size_bytes,
            mtime=excluded.mtime,
            sha256=excluded.sha256,
            phash=excluded.phash,
            width=excluded.width,
            height=excluded.height,
            duration_seconds=excluded.duration_seconds,
            is_screen_recording=excluded.is_screen_recording,
            indexed_at=excluded.indexed_at,
            error=excluded.error
        """,
        (
            str(path), stat.st_size, stat.st_mtime, sha256, phash, width, height,
            duration, is_screen_recording, now, error,
        ),
    )
    return True


def run_index(conn, source_dir: Path, exclude_dir: Path | None = None) -> dict:
    stats = {"scanned": 0, "indexed": 0, "skipped": 0, "errors": 0}
    claimed_live_pairs: set[Path] = set()

    for path in iter_image_files(source_dir, exclude_dir):
        stats["scanned"] += 1
        live_pair = find_live_pair(path)
        if live_pair:
            claimed_live_pairs.add(live_pair)
        if index_photo(conn, path):
            stats["indexed"] += 1
        else:
            stats["skipped"] += 1
        if stats["scanned"] % 500 == 0:
            conn.commit()
            log.info("Scanned %d files so far...", stats["scanned"])

    for path in iter_video_files(source_dir, exclude_dir):
        if path in claimed_live_pairs:
            continue
        stats["scanned"] += 1
        if index_video(conn, path):
            stats["indexed"] += 1
        else:
            stats["skipped"] += 1
        if stats["scanned"] % 500 == 0:
            conn.commit()
            log.info("Scanned %d files so far...", stats["scanned"])

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
