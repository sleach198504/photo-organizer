"""Capture date, camera and GPS extraction for photos and videos.

Photos: iPhone (and most camera) JPEG/HEIC files keep DateTimeOriginal and friends in
the *Exif sub-IFD*, not the top-level IFD that Pillow's `getexif()` returns directly -
reading only the top level (as this module's predecessor did) silently yields no
capture date for essentially every real photo.

Videos: OpenCV exposes no container metadata, so the MP4/MOV atoms are parsed
directly. That's a small amount of code and avoids shipping ffprobe.
"""
from __future__ import annotations

import re
import struct
from datetime import datetime, timedelta
from pathlib import Path


EXIF_IFD = 0x8769
GPS_IFD = 0x8825
TAG_MODEL = 0x0110
TAG_DATETIME = 0x0132            # top-level "DateTime" (last modified) - weakest fallback
TAG_DATETIME_ORIGINAL = 0x9003   # when the shutter fired
TAG_DATETIME_DIGITIZED = 0x9004

_EMPTY = {"taken_at": None, "camera_model": None, "gps_lat": None, "gps_lon": None}


def _parse_exif_datetime(raw) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="ignore")
    text = str(raw).strip("\x00").strip()[:19]
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.year < 1990:  # cameras with a dead clock battery report 1970/1980
            return None
        return parsed.isoformat()
    return None


def _to_degrees(value) -> float:
    d, m, s = value
    return float(d) + float(m) / 60 + float(s) / 3600


def extract_photo_metadata(image) -> dict:
    """Capture date, camera model and GPS from an already-opened PIL image."""
    result = dict(_EMPTY)
    try:
        exif = image.getexif()
    except Exception:
        return result
    if not exif:
        return result

    exif_ifd = {}
    try:
        exif_ifd = exif.get_ifd(EXIF_IFD)
    except Exception:
        pass

    for source, tag in ((exif_ifd, TAG_DATETIME_ORIGINAL), (exif_ifd, TAG_DATETIME_DIGITIZED), (exif, TAG_DATETIME)):
        taken = _parse_exif_datetime(source.get(tag)) if source else None
        if taken:
            result["taken_at"] = taken
            break

    model = exif.get(TAG_MODEL)
    if model:
        result["camera_model"] = str(model).strip("\x00").strip() or None

    try:
        gps = exif.get_ifd(GPS_IFD)
    except Exception:
        gps = None
    if gps:
        try:
            lat = _to_degrees(gps[2])
            if gps.get(1) == "S":
                lat = -lat
            lon = _to_degrees(gps[4])
            if gps.get(3) == "W":
                lon = -lon
            if (lat, lon) != (0.0, 0.0):
                result["gps_lat"], result["gps_lon"] = lat, lon
        except (KeyError, TypeError, ZeroDivisionError, ValueError):
            pass
    return result


# ---------------------------------------------------------------------------
# MP4 / MOV
# ---------------------------------------------------------------------------

_MAC_EPOCH = datetime(1904, 1, 1)
_ISO6709 = re.compile(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)")


def _iter_boxes(f, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        header = f.read(8)
        if len(header) < 8:
            return
        size, kind = struct.unpack(">I4s", header)
        header_len = 8
        if size == 1:
            ext = f.read(8)
            if len(ext) < 8:
                return
            size = struct.unpack(">Q", ext)[0]
            header_len = 16
        elif size == 0:
            size = end - pos
        if size < header_len:
            return
        yield kind.decode("latin1"), pos + header_len, min(pos + size, end)
        pos += size


def _find_box(f, start: int, end: int, name: str):
    for kind, payload_start, payload_end in _iter_boxes(f, start, end):
        if kind == name:
            return payload_start, payload_end
    return None


def _parse_iso6709(text: str):
    match = _ISO6709.match(text.strip())
    if not match:
        return None, None
    try:
        lat, lon = float(match.group(1)), float(match.group(2))
    except ValueError:
        return None, None
    if (lat, lon) == (0.0, 0.0) or abs(lat) > 90 or abs(lon) > 180:
        return None, None
    return lat, lon


def _read_apple_keys(f, meta_start: int, meta_end: int) -> dict[str, str]:
    """The QuickTime 'mdta' key/value store iPhones use (creation date with its
    original UTC offset, GPS position)."""
    values: dict[str, str] = {}
    keys_box = _find_box(f, meta_start + 4, meta_end, "keys")
    ilst_box = _find_box(f, meta_start + 4, meta_end, "ilst")
    if not keys_box or not ilst_box:
        return values

    f.seek(keys_box[0] + 4)
    count = struct.unpack(">I", f.read(4))[0]
    names: list[str] = []
    for _ in range(min(count, 64)):
        size = struct.unpack(">I", f.read(4))[0]
        f.read(4)  # namespace, e.g. 'mdta'
        names.append(f.read(max(0, size - 8)).decode("utf-8", errors="ignore"))

    pos = ilst_box[0]
    while pos + 8 <= ilst_box[1]:
        f.seek(pos)
        size, index = struct.unpack(">II", f.read(8))
        if size < 8:
            break
        item_end = pos + size
        data = _find_box(f, pos + 8, item_end, "data")
        if data and 1 <= index <= len(names):
            f.seek(data[0] + 8)  # skip type indicator + locale
            raw = f.read(max(0, data[1] - data[0] - 8))
            values[names[index - 1]] = raw.decode("utf-8", errors="ignore").strip("\x00").strip()
        pos = item_end
    return values


def extract_video_metadata(path: Path) -> dict:
    """Capture date and GPS from an MP4/MOV header. Never raises - returns empty
    values for anything it can't find, since a video without metadata is normal."""
    result = dict(_EMPTY)
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            file_end = f.tell()
            moov = _find_box(f, 0, file_end, "moov")
            if not moov:
                return result

            mvhd_taken = None
            mvhd = _find_box(f, moov[0], moov[1], "mvhd")
            if mvhd:
                f.seek(mvhd[0])
                version = f.read(1)[0]
                f.read(3)
                seconds = struct.unpack(">Q" if version == 1 else ">I", f.read(8 if version == 1 else 4))[0]
                if seconds > 0:
                    try:
                        utc = _MAC_EPOCH + timedelta(seconds=seconds)
                        # mvhd is UTC; convert to this machine's local time as the
                        # best available stand-in for "when it was shot".
                        local = utc.replace(tzinfo=_utc()).astimezone().replace(tzinfo=None)
                        if local.year >= 1990:
                            mvhd_taken = local.isoformat()
                    except (OverflowError, OSError, ValueError):
                        pass

            apple = {}
            meta = _find_box(f, moov[0], moov[1], "meta")
            if meta:
                apple = _read_apple_keys(f, meta[0], meta[1])

            created = apple.get("com.apple.quicktime.creationdate")
            if created:
                try:
                    result["taken_at"] = datetime.fromisoformat(created).replace(tzinfo=None).isoformat()
                except ValueError:
                    pass
            if not result["taken_at"]:
                result["taken_at"] = mvhd_taken

            location = apple.get("com.apple.quicktime.location.ISO6709")
            if not location:
                udta = _find_box(f, moov[0], moov[1], "udta")
                if udta:
                    xyz = _find_box(f, udta[0], udta[1], "\xa9xyz")
                    if xyz:
                        f.seek(xyz[0] + 4)  # 2-byte length + 2-byte language
                        location = f.read(max(0, xyz[1] - xyz[0] - 4)).decode("utf-8", errors="ignore")
            if location:
                result["gps_lat"], result["gps_lon"] = _parse_iso6709(location)
    except (OSError, struct.error, IndexError):
        pass
    return result


def _utc():
    from datetime import timezone

    return timezone.utc
