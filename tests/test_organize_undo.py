"""Organize can be undone: photos return where they came from, and nothing is lost on the way."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db import connect
from app.organize import run_organize, undo_info, undo_organize
from app.progress import Cancelled, Progress


class UndoOrganizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.library = root / "Photos"
        self.dest = root / "Filed"
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.ids: dict[str, int] = {}

        self.add("Camera Roll/a.jpg", "2024-03-05T10:00:00", live=True)
        self.add("Camera Roll/b.jpg", "2024-03-20T10:00:00")
        self.add("Downloads/c.jpg", "2023-11-01T10:00:00")

    def add(self, rel: str, taken: str, live: bool = False) -> None:
        path = self.library / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(rel.encode())
        live_path = None
        if live:
            live_path = path.with_suffix(".mov")
            live_path.write_bytes(b"clip")
        cur = self.conn.execute(
            "INSERT INTO photos (path, live_pair_path, size_bytes, mtime, sha256, taken_at, status, indexed_at, media_type) "
            "VALUES (?, ?, 1, 0, ?, ?, 'active', 'now', 'photo')",
            (str(path), str(live_path) if live_path else None, rel, taken),
        )
        self.conn.commit()
        self.ids[rel] = cur.lastrowid

    def organize(self, **kwargs) -> dict:
        return run_organize(self.conn, self.dest, self.library, **kwargs)

    def row(self, rel: str):
        return self.conn.execute("SELECT * FROM photos WHERE id = ?", (self.ids[rel],)).fetchone()

    def test_undo_puts_everything_back_including_live_clips(self) -> None:
        self.assertEqual(self.organize()["moved"], 3)
        self.assertFalse((self.library / "Camera Roll" / "a.jpg").exists())
        info = undo_info(self.conn)
        self.assertEqual(info["count"], 3)
        self.assertEqual(info["dest_root"], str(self.dest))

        stats = undo_organize(self.conn)
        self.assertEqual(stats, {"restored": 3, "missing": 0, "renamed": 0, "failed": 0})
        for rel in self.ids:
            self.assertEqual((self.library / rel).read_bytes(), rel.encode())
            self.assertEqual(self.row(rel)["status"], "active")
            self.assertEqual(Path(self.row(rel)["path"]), self.library / rel)
            self.assertIsNone(self.row(rel)["organized_from"])
        self.assertEqual((self.library / "Camera Roll" / "a.mov").read_bytes(), b"clip")
        self.assertEqual(Path(self.row("Camera Roll/a.jpg")["live_pair_path"]), self.library / "Camera Roll" / "a.mov")
        self.assertIsNone(undo_info(self.conn))

    def test_folders_organize_created_are_tidied_up_but_nothing_else(self) -> None:
        self.dest.mkdir()
        (self.dest / "keep-me.txt").write_text("not ours")
        self.organize()
        self.assertTrue(any(p.is_dir() for p in self.dest.iterdir()))
        undo_organize(self.conn)
        self.assertEqual([p.name for p in self.dest.iterdir()], ["keep-me.txt"])

    def test_a_destination_created_by_organize_is_removed_when_empty(self) -> None:
        self.organize()
        undo_organize(self.conn)
        self.assertFalse(self.dest.exists())

    def test_files_changed_since_are_not_lost_or_overwritten(self) -> None:
        self.organize()
        moved_b = Path(self.row("Camera Roll/b.jpg")["path"])
        moved_b.unlink()                                          # deleted since
        occupied = self.library / "Downloads" / "c.jpg"
        occupied.parent.mkdir(parents=True, exist_ok=True)
        occupied.write_bytes(b"a different file now lives here")  # original place taken

        stats = undo_organize(self.conn)
        self.assertEqual((stats["restored"], stats["missing"], stats["renamed"]), (2, 1, 1))
        self.assertEqual(occupied.read_bytes(), b"a different file now lives here")
        c = self.row("Downloads/c.jpg")
        self.assertEqual(Path(c["path"]).name, "c (1).jpg")
        self.assertEqual(Path(c["path"]).read_bytes(), b"Downloads/c.jpg")
        self.assertEqual(self.row("Camera Roll/b.jpg")["status"], "organized")  # still tracked, not forgotten

    def test_only_the_latest_run_can_be_undone(self) -> None:
        self.organize()
        self.add("Camera Roll/new.jpg", "2024-04-01T10:00:00")
        self.organize()
        info = undo_info(self.conn)
        self.assertEqual(info["count"], 1)
        undo_organize(self.conn)
        self.assertTrue((self.library / "Camera Roll" / "new.jpg").exists())
        self.assertFalse((self.library / "Camera Roll" / "a.jpg").exists())  # earlier run stays filed

    def test_a_run_stopped_part_way_can_still_be_undone(self) -> None:
        calls = {"n": 0}

        def stop_after_two() -> bool:
            calls["n"] += 1
            return calls["n"] > 2

        with self.assertRaises(Cancelled):
            self.organize(progress=Progress(should_cancel=stop_after_two))
        filed = self.conn.execute("SELECT COUNT(*) c FROM photos WHERE status = 'organized'").fetchone()["c"]
        self.assertEqual(filed, 2)
        self.assertEqual(undo_info(self.conn)["count"], 2)
        undo_organize(self.conn)
        self.assertTrue(all((self.library / rel).exists() for rel in self.ids))

    def test_undo_with_nothing_to_undo_does_nothing(self) -> None:
        self.assertIsNone(undo_info(self.conn))
        self.assertEqual(undo_organize(self.conn), {"restored": 0, "missing": 0, "renamed": 0, "failed": 0})


if __name__ == "__main__":
    unittest.main()
