"""Thumbnails must show a photo's colours, not just its raw numbers."""
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageCms

from app import media

# A wide-gamut working space that ships with Windows, standing in for Display P3.
WIDE_GAMUT = Path(r"C:\Windows\System32\spool\drivers\color\ewrgb18.icm")
PATCH = (200, 40, 40)


def _thumb_pixel(path: Path) -> tuple[int, int, int]:
    thumb = Image.open(io.BytesIO(media._render_still(path, 400, 90)))
    return thumb.getpixel((10, 10))


def _close(a: tuple[int, ...], b: tuple[int, ...], tolerance: int = 4) -> bool:
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


class ColourManagedThumbnailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)

    def save(self, name: str, **options) -> Path:
        path = self.root / name
        Image.new("RGB", (800, 600), PATCH).save(path, quality=95, **options)
        return path

    @unittest.skipUnless(WIDE_GAMUT.exists(), "needs the Windows wide-gamut colour profile")
    def test_wide_gamut_photo_is_converted_to_srgb(self) -> None:
        icc = WIDE_GAMUT.read_bytes()
        path = self.save("wide.jpg", icc_profile=icc)
        expected = ImageCms.profileToProfile(
            Image.new("RGB", (4, 4), PATCH),
            ImageCms.ImageCmsProfile(io.BytesIO(icc)),
            ImageCms.createProfile("sRGB"),
            outputMode="RGB",
        ).getpixel((1, 1))
        got = _thumb_pixel(path)
        self.assertTrue(_close(got, expected), f"{got} should be near {expected}")
        self.assertFalse(_close(got, PATCH, 3), "raw numbers were stored without conversion")

    def test_untagged_photo_is_left_alone(self) -> None:
        self.assertTrue(_close(_thumb_pixel(self.save("plain.jpg")), PATCH))

    def test_srgb_tagged_photo_is_left_alone(self) -> None:
        srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        self.assertTrue(_close(_thumb_pixel(self.save("srgb.jpg", icc_profile=srgb)), PATCH))

    def test_unreadable_profile_falls_back_to_the_raw_colours(self) -> None:
        path = self.save("broken.jpg", icc_profile=b"not a real profile")
        self.assertTrue(_close(_thumb_pixel(path), PATCH))

    def test_old_cached_renditions_are_swept(self) -> None:
        with mock.patch.object(media, "THUMB_DIR", self.root):
            folder = self.root / "thumb" / "0"
            folder.mkdir(parents=True)
            old = folder / "7_100.jpg"
            current = folder / f"7_100_v{media.RENDER_VERSION}.jpg"
            old.write_bytes(b"x")
            current.write_bytes(b"x")
            self.assertEqual(media.remove_stale_renditions(), 1)
            self.assertFalse(old.exists())
            self.assertTrue(current.exists())


if __name__ == "__main__":
    unittest.main()
