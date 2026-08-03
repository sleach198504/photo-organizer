from __future__ import annotations

from pathlib import Path
from typing import Iterator

import cv2
from PIL import Image


def open_capture(path: Path) -> cv2.VideoCapture:
    return cv2.VideoCapture(str(path))


def get_duration_seconds(cap: cv2.VideoCapture) -> float | None:
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    if not fps or fps <= 0 or frame_count <= 0:
        return None
    return frame_count / fps


def _frame_to_image(frame) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def grab_middle_frame(cap: cv2.VideoCapture) -> Image.Image | None:
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    if frame_count > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count // 2)
    ok, frame = cap.read()
    if not ok:
        return None
    return _frame_to_image(frame)


def iter_sampled_frames(path: Path, interval_seconds: float) -> Iterator[tuple[float, Image.Image]]:
    """Yields (offset_seconds, frame) for a video, sampling roughly every
    interval_seconds. Always includes at least one frame (offset 0) even for
    videos shorter than the interval."""
    cap = open_capture(path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not fps or fps <= 0 or frame_count <= 0:
            return

        step_frames = max(1, int(round(interval_seconds * fps)))
        frame_index = 0
        while frame_index < frame_count:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = cap.read()
            if not ok:
                break
            yield frame_index / fps, _frame_to_image(frame)
            frame_index += step_frames
    finally:
        cap.release()
