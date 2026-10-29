from __future__ import annotations

import logging
import math
import statistics
from pathlib import Path

import cv2
import numpy as np
import pillow_heif
from PIL import Image

from .progress import NULL_PROGRESS, Progress

pillow_heif.register_heif_opener()

log = logging.getLogger(__name__)

# --- How sharpness is judged ----------------------------------------------------
#
# Every photo is scored at one fixed size (FOCUS_EDGE px on its long edge), so a big
# photo and a small copy of it are comparable. The score is the sharpest part of the
# picture, not the whole-picture average: a portrait with a crisp face and a softly
# blurred background is a good photo, and an average would call it blurry.
# "Sharpest part" is the FOCUS_PERCENTILE-th percentile of the Laplacian variance of a
# TILE_ROWS x TILE_COLS grid of tiles.
#
# A second number, `detail`, says whether the picture has any structure to judge. A
# plain sky or wall has nothing for a sharpness test to find, so its low score means
# "empty", not "blurry", and it is never flagged as blurry.
FOCUS_EDGE = 640
TILE_ROWS, TILE_COLS = 6, 8
FOCUS_PERCENTILE = 90
DETAIL_EDGE = 160
LOW_DETAIL = 3.0  # 99th-percentile edge strength, per pixel, on the 160 px version

# Blur score (Laplacian variance) is content-dependent, not just focus-dependent -
# a sharp photo of a plain wall scores low, a slightly-soft photo of a detailed brick
# wall scores high. Published guidance (e.g. pyimagesearch's canonical writeup) is
# consistently "there's no universal threshold, sample your own sharp/blurry photos
# and pick a value between them" - which is exactly the manual tuning we want to avoid.
# Instead, the threshold is derived per-library from its own score distribution using
# Tukey's IQR outlier method: flag photos that are unusually blurry *relative to the
# rest of this person's own photos*, rather than against a fixed magic number that
# happens to suit someone else's camera and subject matter.
MIN_PHOTOS_FOR_ADAPTIVE_THRESHOLD = 20  # below this, quartiles aren't meaningful
ABSOLUTE_BLUR_FLOOR = 12.0  # catches near-blank/extremely blurred images regardless of the rest of the library
OUTLIER_FENCE_K = 1.5  # Tukey's standard "mild outlier" fence


def _adaptive_blur_threshold(scores: list[float]) -> float:
    if len(scores) < MIN_PHOTOS_FOR_ADAPTIVE_THRESHOLD:
        return ABSOLUTE_BLUR_FLOOR
    # Blur variance is strictly positive and heavily right-skewed (a long tail of
    # highly-detailed sharp photos stretches Q3 out much further than Q1 sits above
    # zero) - computing the IQR fence on the raw scale sends it deeply negative and
    # it never flags anything. Working in log-space first is the standard fix for
    # this kind of skewed, ratio-like data, and keeps the fence meaningful.
    log_scores = [math.log(s + 1.0) for s in scores]
    q1, _, q3 = statistics.quantiles(log_scores, n=4, method="inclusive")
    low_fence_log = q1 - OUTLIER_FENCE_K * (q3 - q1)
    low_fence = math.exp(low_fence_log) - 1.0
    return max(low_fence, ABSOLUTE_BLUR_FLOOR)


def sharpness_of(gray: np.ndarray) -> tuple[float, float]:
    """(focus, detail) for an 8-bit greyscale picture already at its working size."""
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    h, w = laplacian.shape
    tiles = [
        laplacian[r * h // TILE_ROWS:(r + 1) * h // TILE_ROWS, c * w // TILE_COLS:(c + 1) * w // TILE_COLS].var()
        for r in range(TILE_ROWS) for c in range(TILE_COLS)
    ]
    focus = float(np.percentile(tiles, FOCUS_PERCENTILE))

    small = cv2.resize(gray, (DETAIL_EDGE, max(1, round(DETAIL_EDGE * h / w))), interpolation=cv2.INTER_AREA)
    small = small.astype(np.float32)
    strength = np.hypot(cv2.Sobel(small, cv2.CV_32F, 1, 0), cv2.Sobel(small, cv2.CV_32F, 0, 1)) / 8.0
    return focus, float(np.percentile(strength, 99))


def compute_sharpness(path: Path) -> tuple[float, float] | None:
    """(focus, detail) for a photo, or None if it can't be read. Higher focus = sharper."""
    try:
        with Image.open(path) as img:
            img.draft("L", (FOCUS_EDGE, FOCUS_EDGE))  # JPEGs decode at reduced size, much faster
            img = img.convert("L")
            if max(img.size) > FOCUS_EDGE:
                scale = FOCUS_EDGE / max(img.size)
                img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                                 Image.Resampling.LANCZOS)
            arr = np.array(img)
    except Exception as exc:
        log.warning("Failed to load %s for blur scoring: %s", path, exc)
        return None
    return sharpness_of(arr)


def run_quality_scoring(conn, progress: Progress = NULL_PROGRESS) -> dict:
    # detail_score IS NULL also picks up photos scored by the older whole-image method,
    # so a library scanned before this version is scored again once.
    rows = conn.execute(
        "SELECT id, path FROM photos WHERE status = 'active' AND media_type = 'photo' "
        "AND (blur_score IS NULL OR detail_score IS NULL) AND error IS NULL"
    ).fetchall()

    stats = {"scored": 0, "errors": 0}
    progress.start(len(rows))
    try:
        for row in rows:
            progress.check()
            result = compute_sharpness(Path(row["path"]))
            progress.advance(1, Path(row["path"]).name)
            if result is None:
                stats["errors"] += 1
                continue
            conn.execute(
                "UPDATE photos SET blur_score = ?, detail_score = ? WHERE id = ?", (*result, row["id"])
            )
            stats["scored"] += 1
            if stats["scored"] % 200 == 0:
                conn.commit()
    finally:
        conn.commit()  # keep partial work if the scan is cancelled mid-way
    return stats


def flag_blurry_photos(conn) -> int:
    # Pictures with no structure (a sky, a wall) can't be judged, so they neither count
    # towards the library's sharpness picture nor get flagged.
    scored_rows = conn.execute(
        "SELECT id, blur_score FROM photos WHERE status = 'active' AND blur_score IS NOT NULL "
        "AND detail_score IS NOT NULL AND detail_score >= ?",
        (LOW_DETAIL,),
    ).fetchall()
    if not scored_rows:
        return 0

    threshold = _adaptive_blur_threshold([row["blur_score"] for row in scored_rows])
    log.info("Blurry-photo threshold for this library: %.1f", threshold)

    flagged = {row["id"] for row in scored_rows if row["blur_score"] < threshold}

    # A suggestion nobody has acted on yet is withdrawn if the photo no longer qualifies
    # (a better method, or the library changed). Decided ones are left alone.
    stale = [
        r["id"] for r in conn.execute(
            "SELECT id, photo_id FROM recommendations WHERE reason = 'blurry' AND decision = 'pending'"
        ) if r["photo_id"] not in flagged
    ]
    conn.executemany("DELETE FROM recommendations WHERE id = ?", [(i,) for i in stale])

    count = 0
    for photo_id in sorted(flagged):
        # Ignore decision status here on purpose: if the user already reviewed this
        # (approved or rejected) via the review UI, don't re-flag it on the next scan.
        existing = conn.execute(
            "SELECT id FROM recommendations WHERE photo_id = ? AND reason = 'blurry'",
            (photo_id,),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO recommendations (photo_id, reason, confidence, decision) VALUES (?, 'blurry', NULL, 'pending')",
            (photo_id,),
        )
        count += 1
    conn.commit()
    return count
