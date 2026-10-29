"""Cloud placeholder files (OneDrive online-only) must be skipped, never opened."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from app import indexer
from app.db import connect


class AttributeTests(unittest.TestCase):
    def test_each_cloud_placeholder_flag_counts(self) -> None:
        for flag in (indexer.FILE_ATTRIBUTE_OFFLINE, indexer.FILE_ATTRIBUTE_RECALL_ON_OPEN,
                     indexer.FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS):
            with mock.patch.object(indexer.os, "stat", return_value=SimpleNamespace(st_file_attributes=flag | 0x20)):
                self.assertTrue(indexer.is_online_only("x.jpg"), hex(flag))

    def test_ordinary_files_and_other_systems_are_not_placeholders(self) -> None:
        with mock.patch.object(indexer.os, "stat", return_value=SimpleNamespace(st_file_attributes=0x20 | 0x2)):
            self.assertFalse(indexer.is_online_only("x.jpg"))            # archive + hidden
        with mock.patch.object(indexer.os, "stat", return_value=SimpleNamespace()):
            self.assertFalse(indexer.is_online_only("x.jpg"))            # no attributes at all (not Windows)
        self.assertFalse(indexer.is_online_only("does-not-exist.jpg"))   # unreadable is not "online only"


class ScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ("here.jpg", "cloud.jpg", "cloud.mov", "clip.mp4", "notes.txt"):
            (self.root / name).write_bytes(b"x")
        self.cloud = {self.root / "cloud.jpg", self.root / "cloud.mov"}

    def fake(self, path) -> bool:
        return Path(path) in self.cloud

    def test_placeholders_are_listed_separately_and_not_returned_as_photos(self) -> None:
        skipped: list[Path] = []
        with mock.patch.object(indexer, "is_online_only", self.fake):
            images, videos = indexer.scan_folder(self.root, online_only=skipped)
        self.assertEqual([p.name for p in images], ["here.jpg"])
        self.assertEqual([p.name for p in videos], ["clip.mp4"])
        self.assertEqual({p.name for p in skipped}, {"cloud.jpg", "cloud.mov"})

    def test_indexing_never_opens_a_placeholder_and_says_so(self) -> None:
        Image.new("RGB", (32, 32), (9, 99, 199)).save(self.root / "here.jpg")
        opened: list[str] = []
        real_open = Image.open

        def spy(path, *a, **k):
            opened.append(Path(str(path)).name)
            return real_open(path, *a, **k)

        conn = connect(":memory:")
        with mock.patch.object(indexer, "is_online_only", self.fake), mock.patch.object(Image, "open", spy), \
                self.assertLogs("app.indexer", level="INFO") as logs:
            stats = indexer.run_index(conn, self.root)
        conn.close()
        self.assertEqual(stats["online_only"], 2)
        self.assertNotIn("cloud.jpg", opened)
        self.assertTrue(any("online only" in m and "OneDrive" in m for m in logs.output))


if __name__ == "__main__":
    unittest.main()
