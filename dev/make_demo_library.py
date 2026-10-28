"""Builds a synthetic photo library for testing and demos - no real photos involved.

    python dev/make_demo_library.py <output folder> [--scale 1]

The library has known contents (the returned/printed `expected` dict), so tests can
assert exact results: bursts that should cluster, exact duplicates, blurry shots,
screenshots, document photos, two GPS trips, HEIC files, and videos (including a
similar pair and a long one) whose MP4 headers carry real creation dates.
"""
from __future__ import annotations

import argparse
import os
import shutil
import struct
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIC_OK = True
except Exception:  # pragma: no cover
    HEIC_OK = False

HOME = (43.1209, -75.2965)         # "home": Whitesboro, NY
ORLANDO = (28.5383, -81.3792)      # a 5-day trip
NYC = (40.7128, -74.0060)          # a single-day trip

MAC_EPOCH = datetime(1904, 1, 1)


def _font(size: int):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_scene(rng: np.random.RandomState, w: int = 1600, h: int = 1200) -> Image.Image:
    top = rng.randint(40, 230, 3)
    bottom = rng.randint(40, 230, 3)
    t = np.linspace(0, 1, h)[:, None, None]
    arr = (top * (1 - t) + bottom * t) * np.ones((h, w, 3))
    img = Image.fromarray(arr.astype("uint8"))
    d = ImageDraw.Draw(img)
    for _ in range(rng.randint(14, 30)):
        x, y = rng.randint(0, w), rng.randint(0, h)
        s = rng.randint(40, 380)
        color = tuple(int(c) for c in rng.randint(0, 255, 3))
        kind = rng.randint(0, 3)
        if kind == 0:
            d.ellipse([x, y, x + s, y + int(s * rng.uniform(0.5, 1.4))], fill=color)
        elif kind == 1:
            d.rectangle([x, y, x + s, y + int(s * rng.uniform(0.4, 1.2))], fill=color)
        else:
            d.polygon([(x, y), (x + s, y + rng.randint(0, s)), (x + rng.randint(0, s), y + s)], fill=color)
    grain = rng.randint(-14, 14, (h, w, 1))
    arr = np.clip(np.asarray(img).astype(np.int16) + grain, 0, 255).astype("uint8")
    return Image.fromarray(arr)


def burst_variant(rng: np.random.RandomState, base: Image.Image) -> Image.Image:
    dx, dy = int(rng.randint(-7, 8)), int(rng.randint(-7, 8))
    img = ImageChops.offset(base, dx, dy)
    return ImageEnhance.Brightness(img).enhance(1 + rng.uniform(-0.04, 0.04))


def _deg(value: float):
    value = abs(value)
    d = int(value)
    m = int((value - d) * 60)
    s = round((value - d - m / 60) * 3600, 2)
    return (float(d), float(m), float(s))


def exif_bytes(taken: datetime | None, gps=None, model: str | None = "iPhone 14 Pro"):
    exif = Image.Exif()
    if model:
        exif[0x010F] = "Apple"
        exif[0x0110] = model
    if taken:
        stamp = taken.strftime("%Y:%m:%d %H:%M:%S")
        ifd = exif.get_ifd(0x8769)
        ifd[0x9003] = stamp
        ifd[0x9004] = stamp
    if gps:
        g = exif.get_ifd(0x8825)
        g[1] = "N" if gps[0] >= 0 else "S"
        g[2] = _deg(gps[0])
        g[3] = "E" if gps[1] >= 0 else "W"
        g[4] = _deg(gps[1])
    return exif


def save_jpeg(img: Image.Image, path: Path, taken: datetime | None, gps=None, model="iPhone 14 Pro") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=90, exif=exif_bytes(taken, gps, model))
    if taken:
        ts = taken.timestamp()
        os.utime(path, (ts, ts))


def save_heic(img: Image.Image, path: Path, taken: datetime, gps=None) -> bool:
    if not HEIC_OK:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        img.save(path, format="HEIF", quality=80, exif=exif_bytes(taken, gps).tobytes())
    except Exception:
        return False
    ts = taken.timestamp()
    os.utime(path, (ts, ts))
    return True


def make_screenshot(rng: np.random.RandomState, w: int = 1170, h: int = 2532) -> Image.Image:
    dark = rng.rand() < 0.5
    bg, fg, accent = ((18, 18, 20), (235, 235, 240), (10, 132, 255)) if dark else ((246, 246, 248), (20, 20, 24), (0, 122, 255))
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    d.text((60, 40), "9:41", fill=fg, font=_font(56))
    d.text((60, 160), rng.choice(["Messages", "Settings", "Wallet", "Notes", "Maps"]), fill=fg, font=_font(92))
    y = 340
    while y < h - 300:
        d.rounded_rectangle([50, y, w - 50, y + 190], radius=36, fill=tuple(min(255, c + 22) if dark else max(0, c - 14) for c in bg))
        d.ellipse([90, y + 40, 200, y + 150], fill=accent)
        d.text((240, y + 38), "Contact " + str(rng.randint(100, 999)), fill=fg, font=_font(52))
        d.text((240, y + 108), "Tap to open this item", fill=tuple((c + 110) // 2 for c in fg), font=_font(40))
        y += 230
    return img


def make_document(rng: np.random.RandomState, w: int = 1700, h: int = 2200) -> Image.Image:
    img = Image.new("RGB", (w, h), (250, 249, 246))
    d = ImageDraw.Draw(img)
    d.text((140, 120), "RECEIPT  No. " + str(rng.randint(10000, 99999)), fill=(20, 20, 20), font=_font(84))
    y = 300
    words = ["Total", "Subtotal", "Tax", "Item", "Qty", "Card", "Thank", "Date", "Invoice", "Amount"]
    while y < h - 200:
        line = " ".join(rng.choice(words) for _ in range(rng.randint(3, 8))) + f"   ${rng.randint(1, 400)}.{rng.randint(10, 99)}"
        d.text((140, y), line, fill=(25, 25, 25), font=_font(48))
        y += 84
    return img


def write_video(path: Path, taken: datetime, frames: int, size=(640, 360), hue: float = 0.0, seed: int = 0) -> bool:
    """Writes a small MP4 and stamps a real creation date into its mvhd atom."""
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 24, size)
    if not writer.isOpened():
        return False
    rng = np.random.RandomState(seed)
    base = rng.randint(30, 200, 3)
    for i in range(frames):
        frame = np.zeros((size[1], size[0], 3), dtype="uint8")
        frame[:] = np.clip(base + hue + (i % 48), 0, 255)
        cx = int((i * 6) % size[0])
        cv2.circle(frame, (cx, size[1] // 2), 46, (255, 255, 255), -1)
        cv2.rectangle(frame, (40, 40 + (i % 30)), (180, 120 + (i % 30)), (20, 20, 20), -1)
        writer.write(frame)
    writer.release()
    stamp_mvhd(path, taken)
    ts = taken.timestamp()
    os.utime(path, (ts, ts))
    return True


def stamp_mvhd(path: Path, taken: datetime) -> None:
    """Overwrite the movie header's creation time (seconds since 1904, UTC)."""
    data = bytearray(path.read_bytes())
    pos = data.find(b"mvhd")
    if pos < 0:
        return
    version = data[pos + 4]
    # A naive datetime means local wall-clock time; mvhd stores UTC.
    utc = taken.astimezone(timezone.utc).replace(tzinfo=None)
    seconds = int((utc - MAC_EPOCH).total_seconds())
    if version == 0:
        struct.pack_into(">II", data, pos + 8, seconds, seconds)
    else:
        struct.pack_into(">QQ", data, pos + 8, seconds, seconds)
    path.write_bytes(bytes(data))


def build(out_dir: Path, scale: float = 1.0, seed: int = 7) -> dict:
    rng = np.random.RandomState(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    camera = out_dir / "Camera Roll"
    expected = {
        "burst_groups": 0, "burst_members": 0, "exact_duplicate_groups": 0, "blurry": 0,
        "screenshots": 0, "documents": 0, "heic": 0, "videos": 0, "similar_video_groups": 0,
        "long_videos": 0, "trips": 0, "day_trips": 0, "unique_scenes": 0, "photos_total": 0,
        "photos_with_taken_at": 0,
    }

    start = datetime(2023, 6, 3, 9, 0, 0)
    clock = [start]

    def tick(minutes: int | None = None) -> datetime:
        clock[0] += timedelta(minutes=minutes if minutes is not None else int(rng.randint(40, 900)))
        return clock[0]

    n = lambda base: max(1, int(round(base * scale)))
    counter = [6400]

    def next_name(ext: str = "jpg") -> str:
        counter[0] += 1
        return f"IMG_{counter[0]}.{ext}"

    # --- Ordinary one-off photos (some HEIC) ---
    for i in range(n(48)):
        scene = make_scene(rng)
        taken = tick()
        gps = (HOME[0] + rng.uniform(-0.02, 0.02), HOME[1] + rng.uniform(-0.02, 0.02))
        if i % 8 == 0 and save_heic(scene, camera / next_name("heic"), taken, gps):
            expected["heic"] += 1
        else:
            save_jpeg(scene, camera / next_name(), taken, gps)
        expected["unique_scenes"] += 1

    # --- Bursts: 3-6 near-identical shots a few seconds apart ---
    for g in range(n(8)):
        base = make_scene(rng)
        taken = tick()
        size = int(rng.randint(3, 7))
        for k in range(size):
            variant = base if k == 0 else burst_variant(rng, base)
            when = taken + timedelta(seconds=2 * k)
            gps = (HOME[0] + 0.001, HOME[1] - 0.001)
            if k == 1:  # make one member lower resolution so keeper choice is deterministic
                variant = variant.resize((1280, 960))
            save_jpeg(variant, camera / next_name(), when, gps)
        expected["burst_groups"] += 1
        expected["burst_members"] += size

    # --- Exact duplicates: byte-identical copies ---
    originals = sorted(camera.glob("*.jpg"))[: n(4)]
    for src in originals:
        shutil.copy2(src, camera / next_name())
        expected["exact_duplicate_groups"] += 1

    # --- Blurry shots ---
    for _ in range(n(8)):
        scene = make_scene(rng).filter(ImageFilter.GaussianBlur(22))
        save_jpeg(scene, camera / next_name(), tick(), (HOME[0], HOME[1]))
        expected["blurry"] += 1

    # --- Screenshots (PNG, no camera EXIF) ---
    for _ in range(n(10)):
        shot = make_screenshot(rng)
        target = out_dir / "Screenshots" / f"Screenshot {counter[0]}.png"
        counter[0] += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        shot.save(target)
        ts = tick().timestamp()
        os.utime(target, (ts, ts))
        expected["screenshots"] += 1

    # --- Document photos ---
    for _ in range(n(4)):
        save_jpeg(make_document(rng), camera / next_name(), tick(), (HOME[0], HOME[1]))
        expected["documents"] += 1

    # --- Trips (GPS far from home) ---
    trip_start = datetime(2025, 3, 10, 10, 0, 0)
    for day in range(5):
        for shot in range(3):
            scene = make_scene(rng)
            when = trip_start + timedelta(days=day, hours=shot * 3)
            gps = (ORLANDO[0] + rng.uniform(-0.05, 0.05), ORLANDO[1] + rng.uniform(-0.05, 0.05))
            save_jpeg(scene, out_dir / "Orlando" / next_name(), when, gps)
    expected["trips"] = 1
    for shot in range(10):
        scene = make_scene(rng)
        when = datetime(2025, 6, 21, 9, 0, 0) + timedelta(minutes=35 * shot)
        gps = (NYC[0] + rng.uniform(-0.03, 0.03), NYC[1] + rng.uniform(-0.03, 0.03))
        save_jpeg(scene, out_dir / "NYC Day" / next_name(), when, gps)
    expected["day_trips"] = 1

    # --- Videos ---
    vids = out_dir / "Videos"
    if write_video(vids / "IMG_9001.mp4", datetime(2024, 7, 4, 14, 22, 31), 96, seed=1):
        expected["videos"] += 1
        # a near-duplicate: same scene, slightly different brightness
        if write_video(vids / "IMG_9002.mp4", datetime(2024, 7, 4, 14, 24, 2), 120, hue=6, seed=1):
            expected["videos"] += 1
            expected["similar_video_groups"] = 1
        if write_video(vids / "IMG_9003.mp4", datetime(2024, 9, 1, 18, 5, 0), 72, seed=3):
            expected["videos"] += 1
        # a long one (over the 1 minute "medium" review threshold)
        if write_video(vids / "IMG_9004.mp4", datetime(2025, 1, 12, 11, 0, 0), 24 * 65, seed=5):
            expected["videos"] += 1
            expected["long_videos"] = 1

    expected["photos_total"] = sum(1 for p in out_dir.rglob("*") if p.suffix.lower() in {".jpg", ".heic", ".png"})
    expected["photos_with_taken_at"] = expected["photos_total"] - expected["screenshots"]
    return expected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    expected = build(args.out_dir, args.scale, args.seed)
    for key, value in expected.items():
        print(f"{key:>24}: {value}")


if __name__ == "__main__":
    main()
