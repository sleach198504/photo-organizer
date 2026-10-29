"""The screenshot-by-file-type rule: PNG, no camera, and the shape of a screen."""
from __future__ import annotations

import unittest
from pathlib import Path

from app.indexer import looks_like_screenshot as shot


class ScreenshotRuleTests(unittest.TestCase):
    def test_phone_and_desktop_screenshots(self) -> None:
        self.assertTrue(shot(Path("a.png"), None, 1170, 2532))   # iPhone
        self.assertTrue(shot(Path("a.png"), None, 1080, 2400))   # Android
        self.assertTrue(shot(Path("a.PNG"), None, 1920, 1080))   # desktop 16:9
        self.assertTrue(shot(Path("a.png"), None, 3440, 1440))   # ultrawide

    def test_tablet_and_laptop_screens_match_by_exact_size(self) -> None:
        self.assertTrue(shot(Path("a.png"), None, 2048, 1536))
        self.assertTrue(shot(Path("a.png"), None, 2736, 1824))

    def test_photos_saved_as_png_are_not_screenshots(self) -> None:
        self.assertFalse(shot(Path("a.png"), None, 1600, 1200))  # 4:3
        self.assertFalse(shot(Path("a.png"), None, 3000, 2000 + 1))  # 3:2, not a known screen size
        self.assertFalse(shot(Path("a.png"), "iPhone 14", 1170, 2532))  # has a camera

    def test_tiny_pictures_and_other_formats_are_not(self) -> None:
        self.assertFalse(shot(Path("a.png"), None, 300, 640))
        self.assertFalse(shot(Path("a.jpg"), None, 1170, 2532))

    def test_without_a_size_the_old_rule_applies(self) -> None:
        self.assertTrue(shot(Path("a.png"), None))
        self.assertFalse(shot(Path("a.png"), "iPhone"))


if __name__ == "__main__":
    unittest.main()
