"""Folder naming and layout rules for organizing."""
from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path

from app.organize import TOP_LEVEL_LABEL, clean_folder_name, dated_subfolder, photo_folder_label


class DatedSubfolderTest(unittest.TestCase):
    WHEN = datetime(2025, 3, 7, 18, 0)

    def test_layouts(self) -> None:
        expected = {
            "year_month": Path("2025/03"),
            "year_month_name": Path("2025/03 March"),
            "year_month_day": Path("2025/03/07"),
            "year": Path("2025"),
        }
        for template, path in expected.items():
            with self.subTest(template):
                self.assertEqual(dated_subfolder(self.WHEN, template), path)

    def test_unknown_template_falls_back_to_year_month(self) -> None:
        self.assertEqual(dated_subfolder(self.WHEN, "nonsense"), Path("2025/03"))


class CleanFolderNameTest(unittest.TestCase):
    def test_removes_characters_windows_rejects(self) -> None:
        self.assertEqual(clean_folder_name('Mom: "Best" trip? <2025>'), "Mom- -Best- trip- -2025-")

    def test_never_returns_an_empty_name(self) -> None:
        self.assertEqual(clean_folder_name("  ..  "), "Untitled")


class FolderLabelTest(unittest.TestCase):
    ROOT = Path("C:/Photos")

    def test_labels_are_folder_names_with_forward_slashes(self) -> None:
        # The UI compares these strings, so they must be identical on every code path.
        self.assertEqual(photo_folder_label(self.ROOT / "Camera Roll" / "IMG_1.jpg", self.ROOT), "Camera Roll")
        self.assertEqual(photo_folder_label(self.ROOT / "Trips" / "Orlando" / "IMG_2.jpg", self.ROOT), "Trips/Orlando")

    def test_files_directly_in_the_photos_folder_get_their_own_label(self) -> None:
        self.assertEqual(photo_folder_label(self.ROOT / "IMG_3.jpg", self.ROOT), TOP_LEVEL_LABEL)


if __name__ == "__main__":
    unittest.main()
