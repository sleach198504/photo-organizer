"""Capture dates and locations: the data every date-based feature depends on."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from PIL import Image

from app.metadata import _parse_iso6709, extract_photo_metadata, extract_video_metadata
from dev.make_demo_library import exif_bytes, write_video


class PhotoMetadataTest(unittest.TestCase):
    def test_reads_date_camera_and_location_from_the_exif_sub_ifd(self) -> None:
        # iPhones store the capture date in the Exif sub-IFD, not the top-level
        # DateTime tag. Reading only the top level once left every photo undated.
        taken = datetime(2025, 3, 14, 9, 26, 53)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.jpg"
            Image.new("RGB", (32, 24), "gray").save(path, "JPEG", exif=exif_bytes(taken, gps=(28.5383, -81.3792)))
            with Image.open(path) as image:
                meta = extract_photo_metadata(image)
        self.assertEqual(meta["taken_at"], "2025-03-14T09:26:53")
        self.assertEqual(meta["camera_model"], "iPhone 14 Pro")
        self.assertAlmostEqual(meta["gps_lat"], 28.5383, places=3)
        self.assertAlmostEqual(meta["gps_lon"], -81.3792, places=3)

    def test_a_photo_without_exif_is_simply_undated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plain.png"
            Image.new("RGB", (8, 8)).save(path)
            with Image.open(path) as image:
                meta = extract_photo_metadata(image)
        self.assertIsNone(meta["taken_at"])
        self.assertIsNone(meta["gps_lat"])


class VideoMetadataTest(unittest.TestCase):
    def test_reads_the_creation_time_stamped_in_the_movie_header(self) -> None:
        taken = datetime(2024, 7, 4, 14, 22, 5)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clip.mp4"
            self.assertTrue(write_video(path, taken, frames=12))
            meta = extract_video_metadata(path)
        self.assertEqual(meta["taken_at"], taken.isoformat())

    def test_a_file_that_is_not_a_video_gives_empty_metadata_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "junk.mp4"
            path.write_bytes(b"\x00\x01 definitely not an mp4")
            meta = extract_video_metadata(path)
        self.assertIsNone(meta["taken_at"])

    def test_parses_apple_iso6709_locations(self) -> None:
        lat, lon = _parse_iso6709("+28.5383-081.3792+000.000/")
        self.assertAlmostEqual(lat, 28.5383)
        self.assertAlmostEqual(lon, -81.3792)


if __name__ == "__main__":
    unittest.main()
