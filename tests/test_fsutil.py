"""Moving a file must survive a short-lived lock, and still fail for a real problem."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import fsutil


class MoveFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / "a.jpg"
        self.src.write_bytes(b"photo")
        self.dest = Path(self.tmp.name) / "out" / "a.jpg"
        self.dest.parent.mkdir()

    def test_a_brief_lock_is_waited_out(self) -> None:
        real = fsutil.shutil.move
        calls = {"n": 0}

        def flaky(src, dest):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError(32, "being used by another process")
            return real(src, dest)

        with mock.patch.object(fsutil.shutil, "move", flaky), mock.patch.object(fsutil.time, "sleep") as sleep:
            fsutil.move_file(self.src, self.dest)
        self.assertEqual(calls["n"], 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertTrue(self.dest.exists() and not self.src.exists())

    def test_a_lock_that_never_clears_still_raises(self) -> None:
        with mock.patch.object(fsutil.shutil, "move", side_effect=PermissionError(32, "locked")) as move, \
                mock.patch.object(fsutil.time, "sleep"):
            with self.assertRaises(PermissionError):
                fsutil.move_file(self.src, self.dest)
        self.assertEqual(move.call_count, fsutil.MOVE_RETRIES)

    def test_other_errors_are_not_retried(self) -> None:
        with mock.patch.object(fsutil.shutil, "move", side_effect=FileNotFoundError("gone")) as move, \
                mock.patch.object(fsutil.time, "sleep") as sleep:
            with self.assertRaises(FileNotFoundError):
                fsutil.move_file(self.src, self.dest)
        self.assertEqual((move.call_count, sleep.call_count), (1, 0))


if __name__ == "__main__":
    unittest.main()
