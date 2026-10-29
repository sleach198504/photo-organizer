"""Thumbnails and previews, cached on disk.

Rendering a thumbnail means decoding a multi-megapixel photo (HEIC especially), so
doing it per request - as the first version did - made every scroll through a large
library slow. Each rendition is generated once, written to the cache folder keyed by
photo id and file modified time (an edited file gets a fresh one), and served with a
far-future cache header afterwards. A background warmer fills the cache after a scan
so grids are instant the first time they're opened.
"""
from __future__ import annotations

import io
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pillow_heif
from PIL import Image, ImageCms, ImageOps

from . import video_frames
from .db import session
from .paths import THUMB_DIR

pillow_heif.register_heif_opener()

log = logging.getLogger(__name__)

SIZES = {
    "thumb": (400, 82),      # long edge in px, JPEG quality - grid cells and lists
    "preview": (2000, 88),   # the lightbox / compare view
    "original": (4096, 92),  # only used for formats a browser can't show natively
}
BROWSER_NATIVE = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


# Bumped whenever the pixels a rendition holds change, so older cached files are
# never served (and are swept away by `remove_stale_renditions`).
RENDER_VERSION = 2  # 2: colours converted to sRGB


def cache_file(kind: str, photo_id: int, mtime: float) -> Path:
    return THUMB_DIR / kind / str(photo_id // 1000) / f"{photo_id}_{int(mtime or 0)}_v{RENDER_VERSION}.jpg"


def remove_stale_renditions() -> int:
    """Delete cached files from earlier render versions. Returns how many were removed."""
    current = f"_v{RENDER_VERSION}.jpg"
    removed = 0
    if not THUMB_DIR.is_dir():
        return removed
    for stale in THUMB_DIR.rglob("*.jpg"):
        if not stale.name.endswith(current):
            try:
                stale.unlink()
                removed += 1
            except OSError:
                pass
    return removed


_SRGB = ImageCms.createProfile("sRGB")


def _to_srgb(img: Image.Image) -> Image.Image:
    """Photos from iPhones and good cameras are often Display P3 or Adobe RGB. Browsers
    treat an untagged JPEG as sRGB, so saving the raw numbers would wash those colours
    out. Converting here keeps what you see in the grid faithful to the photo."""
    icc = img.info.get("icc_profile")
    if icc:
        try:
            source = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            if "srgb" not in ImageCms.getProfileDescription(source).lower():
                return ImageCms.profileToProfile(img, source, _SRGB, outputMode="RGB")
        except (ImageCms.PyCMSError, OSError, ValueError) as exc:
            log.debug("Could not read the embedded colour profile, assuming sRGB: %s", exc)
    return img.convert("RGB")


def _render_still(path: Path, max_dim: int, quality: int) -> bytes:
    # Read the file in one go and decode from memory, so it is not held open (and so cannot
    # block moving the photo) while the slower conversion work runs.
    with Image.open(io.BytesIO(path.read_bytes())) as img:
        # For JPEGs this makes the decoder downscale while decoding (DCT scaling),
        # which is several times faster than decoding at full size then resizing.
        img.draft("RGB", (max_dim, max_dim))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "CMYK"):
            icc = img.info.get("icc_profile")
            img = img.convert("RGB")
            if icc:
                img.info["icc_profile"] = icc  # convert() drops it; _to_srgb needs it
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS, reducing_gap=2.0)
        img = _to_srgb(img)  # after shrinking, so far fewer pixels are converted
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()


def _render_video_frame(path: Path, max_dim: int, quality: int) -> bytes:
    cap = video_frames.open_capture(path)
    try:
        frame = video_frames.grab_middle_frame(cap)
    finally:
        cap.release()
    if frame is None:
        raise RuntimeError("could not read a frame from this video")
    img = frame.convert("RGB")
    img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def ensure(kind: str, photo_id: int, path: str, mtime: float, media_type: str) -> Path:
    """Path of the cached rendition, generating it first if needed. Raises if the
    source can't be decoded."""
    target = cache_file(kind, photo_id, mtime)
    if target.exists():
        return target

    max_dim, quality = SIZES[kind]
    source = Path(path)
    data = (
        _render_video_frame(source, max_dim, quality)
        if media_type == "video"
        else _render_still(source, max_dim, quality)
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(f".{threading.get_ident()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)  # atomic: a half-written file is never served
    return target


def browser_displayable(path: str) -> bool:
    return Path(path).suffix.lower() in BROWSER_NATIVE


# ---------------------------------------------------------------------------
# Background warmer
# ---------------------------------------------------------------------------


class ThumbWarmer:
    """Pre-generates grid thumbnails for the whole library in the background."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self.total = 0
        self.done = 0

    def status(self) -> dict:
        return {"running": self._running, "total": self.total, "done": self.done}

    def start(self, db_path: Path) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self.total = self.done = 0
        threading.Thread(target=self._run, args=(db_path,), daemon=True, name="thumb-warmer").start()

    def _run(self, db_path: Path) -> None:
        try:
            if remove_stale_renditions():
                log.info("Removed thumbnails from an older version; they will be redrawn")
            with session(db_path) as conn:
                rows = conn.execute(
                    "SELECT id, path, mtime, media_type FROM photos WHERE status = 'active' ORDER BY id DESC"
                ).fetchall()
            todo = [r for r in rows if not cache_file("thumb", r["id"], r["mtime"]).exists()]
            self.total = len(todo)

            def work(row) -> None:
                try:
                    ensure("thumb", row["id"], row["path"], row["mtime"], row["media_type"])
                except Exception as exc:  # one bad file must not stop the rest
                    log.debug("Could not pre-render %s: %s", row["path"], exc)
                finally:
                    self.done += 1

            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(work, todo))
        except Exception:
            log.exception("Thumbnail warm-up failed")
        finally:
            self._running = False


warmer = ThumbWarmer()
