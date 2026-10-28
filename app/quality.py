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

MAX_DIMENSION = 1024  # downscale before scoring - much faster, negligible accuracy loss

# Blur score (variance of Laplacian) is content-dependent, not just focus-dependent -
# a sharp photo of a plain wall scores low, a slightly-soft photo of a detailed brick
# wall scores high. Published guidance (e.g. pyimagesearch's canonical writeup) is
# consistently "there's no universal threshold, sample your own sharp/blurry photos
# and pick a value between them" - which is exactly the manual tuning we want to avoid.
# Instead, the threshold is derived per-library from its own score distribution using
# Tukey's IQR outlier method: flag photos that are unusually blurry *relative to the
# rest of this person's own photos*, rather than against a fixed magic number that
# happens to suit someone else's camera and subject matter.
MIN_PHOTOS_FOR_ADAPTIVE_THRESHOLD = 20  # below this, quartiles aren't meaningful
ABSOLUTE_BLUR_FLOOR = 10.0  # catches near-blank/extremely blurred images regardless of the rest of the library
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


def compute_blur_score(path: Path) -> float | None:
    """Higher = sharper. Laplacian variance is a standard, fast, no-ML blur measure:
    a sharp image has lots of high-frequency edge detail, a blurry one doesn't."""
    try:
        with Image.open(path) as img:
            img = img.convert("L")
            if max(img.size) > MAX_DIMENSION:
                scale = MAX_DIMENSION / max(img.size)
                new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
                img = img.resize(new_size)
            arr = np.array(img)
    except Exception as exc:
        log.warning("Failed to load %s for blur scoring: %s", path, exc)
        return None
    return float(cv2.Laplacian(arr, cv2.CV_64F).var())


def run_quality_scoring(conn, progress: Progress = NULL_PROGRESS) -> dict:
    rows = conn.execute(
        "SELECT id, path FROM photos WHERE status = 'active' AND media_type = 'photo' "
        "AND blur_score IS NULL AND error IS NULL"
    ).fetchall()

    stats = {"scored": 0, "errors": 0}
    progress.start(len(rows))
    try:
        for row in rows:
            progress.check()
            score = compute_blur_score(Path(row["path"]))
            progress.advance(1, Path(row["path"]).name)
            if score is None:
                stats["errors"] += 1
                continue
            conn.execute("UPDATE photos SET blur_score = ? WHERE id = ?", (score, row["id"]))
            stats["scored"] += 1
            if stats["scored"] % 200 == 0:
                conn.commit()
    finally:
        conn.commit()  # keep partial work if the scan is cancelled mid-way
    return stats


def flag_blurry_photos(conn) -> int:
    scored_rows = conn.execute(
        "SELECT id, blur_score FROM photos WHERE status = 'active' AND blur_score IS NOT NULL"
    ).fetchall()
    if not scored_rows:
        return 0

    threshold = _adaptive_blur_threshold([row["blur_score"] for row in scored_rows])
    log.info("Blurry-photo threshold for this library: %.1f", threshold)

    rows = [row for row in scored_rows if row["blur_score"] < threshold]
    count = 0
    for row in rows:
        # Ignore decision status here on purpose: if the user already reviewed this
        # (approved or rejected) via the review UI, don't re-flag it on the next scan.
        existing = conn.execute(
            "SELECT id FROM recommendations WHERE photo_id = ? AND reason = 'blurry'",
            (row["id"],),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO recommendations (photo_id, reason, confidence, decision) VALUES (?, 'blurry', NULL, 'pending')",
            (row["id"],),
        )
        count += 1
    conn.commit()
    return count
