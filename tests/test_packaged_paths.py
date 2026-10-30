"""Where a packaged build keeps its data, and bringing a library over from an earlier install."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import legacy_import, paths


class ResolveHomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.code = Path("C:/Program Files/WindowsApps/PhotoOrganizer")
        self.env = {"LOCALAPPDATA": "C:/Users/pat/AppData/Local"}

    def test_a_normal_install_keeps_its_data_beside_the_code(self) -> None:
        self.assertEqual(paths.resolve_home(self.code, {}, self.env), self.code)

    def test_a_packaged_build_uses_a_per_user_folder(self) -> None:
        home = paths.resolve_home(self.code, {"channel": "store"}, self.env)
        self.assertEqual(home, (Path("C:/Users/pat/AppData/Local") / "Photo Organizer").resolve())

    def test_the_override_wins_everywhere(self) -> None:
        env = {**self.env, "PHOTO_ORGANIZER_HOME": "C:/scratch/home"}
        self.assertEqual(paths.resolve_home(self.code, {"channel": "store"}, env), Path("C:/scratch/home").resolve())
        self.assertEqual(paths.resolve_home(self.code, {}, env), Path("C:/scratch/home").resolve())

    def test_package_info_is_read_from_the_app_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(paths.read_package_info(root), {})
            (root / "app").mkdir()
            (root / "app" / "package_info.json").write_text(json.dumps({"channel": "store"}), encoding="utf-8")
            self.assertEqual(paths.read_package_info(root), {"channel": "store"})
            (root / "app" / "package_info.json").write_text("not json", encoding="utf-8")
            self.assertEqual(paths.read_package_info(root), {})

    def test_this_checkout_is_not_a_packaged_build(self) -> None:
        self.assertIsNone(paths.CHANNEL)


def make_old_install(folder: Path) -> None:
    (folder / "data").mkdir(parents=True)
    (folder / "config.yaml").write_text('source_dir: "D:/Photos"\nquarantine_dir: "D:/Photos/Image Review"\n', encoding="utf-8")
    db = sqlite3.connect(folder / "data" / "index.db")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE photos (id INTEGER PRIMARY KEY, path TEXT)")
    db.execute("INSERT INTO photos (path) VALUES ('D:/Photos/a.jpg'), ('D:/Photos/b.jpg')")
    db.commit()
    db.close()


class ImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old, self.home = self.root / "old", self.root / "home"
        make_old_install(self.old)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_the_library_and_settings_are_copied_across(self) -> None:
        result = legacy_import.import_earlier_install(self.home, self.old)
        self.assertEqual(result["copied"], ["photo index", "settings"])
        db = sqlite3.connect(self.home / "data" / "index.db")
        try:
            rows = db.execute("SELECT path FROM photos ORDER BY id").fetchall()
        finally:
            db.close()
        self.assertEqual(rows, [("D:/Photos/a.jpg",), ("D:/Photos/b.jpg",)])
        self.assertIn("D:/Photos", (self.home / "config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(legacy_import.imported_from(self.home), str(self.old))

    def test_the_earlier_install_is_left_exactly_as_it_was(self) -> None:
        before = {p.name: p.read_bytes() for p in (self.old / "data").iterdir() if p.suffix == ".db"}
        config_before = (self.old / "config.yaml").read_bytes()
        legacy_import.import_earlier_install(self.home, self.old)
        self.assertEqual({p.name: p.read_bytes() for p in (self.old / "data").iterdir() if p.suffix == ".db"}, before)
        self.assertEqual((self.old / "config.yaml").read_bytes(), config_before)

    def test_it_happens_once_and_never_overwrites(self) -> None:
        legacy_import.import_earlier_install(self.home, self.old)
        (self.home / "data" / "index.db").unlink()  # the person clears their data on purpose
        self.assertIsNone(legacy_import.import_earlier_install(self.home, self.old))
        self.assertFalse((self.home / "data" / "index.db").exists())

    def test_a_library_that_already_exists_here_is_not_replaced(self) -> None:
        (self.home / "data").mkdir(parents=True)
        (self.home / "data" / "index.db").write_bytes(b"mine")
        self.assertIsNone(legacy_import.import_earlier_install(self.home, self.old))
        self.assertEqual((self.home / "data" / "index.db").read_bytes(), b"mine")

    def test_nothing_to_import_is_fine(self) -> None:
        self.assertIsNone(legacy_import.import_earlier_install(self.home, self.root / "missing"))
        empty = self.root / "empty"
        empty.mkdir()
        self.assertIsNone(legacy_import.import_earlier_install(self.home, empty))
        self.assertIsNone(legacy_import.import_earlier_install(self.old, self.old))
        self.assertIsNone(legacy_import.imported_from(self.home))

    def test_a_damaged_index_leaves_no_half_import_behind(self) -> None:
        (self.old / "data" / "index.db").write_bytes(b"this is not a database" * 100)
        for sidecar in (self.old / "data").glob("index.db-*"):
            sidecar.unlink()
        self.assertIsNone(legacy_import.import_earlier_install(self.home, self.old))
        self.assertFalse((self.home / "config.yaml").exists())
        self.assertFalse((self.home / "data" / "index.db").exists())
        self.assertIsNone(legacy_import.imported_from(self.home))


if __name__ == "__main__":
    unittest.main()
