"""iPhone naming: IMG_E edited copies and .AAE edit files."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import dedupe, iphone
from app.actions import purge_photos, quarantine_photo, restore_photo
from app.config import Config
from app.db import connect
from app.organize import run_organize, undo_organize
from app.review import _group_why


class NamingTests(unittest.TestCase):
    def test_edited_copies_are_paired_with_their_originals_by_folder_and_number(self) -> None:
        a = Path("C:/P/Camera Roll")
        items = [
            (1, a / "IMG_1234.HEIC"), (2, a / "IMG_E1234.JPG"),            # the pair
            (3, a / "IMG_5555.JPG"),                                        # no edit
            (4, a / "IMG_E9999.JPG"),                                       # edit whose original is gone
            (5, Path("C:/P/Other") / "IMG_1234.JPG"),                       # same number, other folder
            (6, a / "img_e0042.jpg"), (7, a / "IMG_0042.JPG"),              # case and leading zeros
            (8, a / "DSC_1234.JPG"),
        ]
        self.assertEqual(sorted(iphone.edited_pairs(items)), [(2, 1), (6, 7)])

    def test_name_helpers(self) -> None:
        self.assertTrue(iphone.is_edit_of("IMG_E1234.JPG", "IMG_1234.HEIC"))
        self.assertFalse(iphone.is_edit_of("IMG_1234.HEIC", "IMG_E1234.JPG"))
        self.assertFalse(iphone.is_edit_of("IMG_E1234.JPG", "IMG_1235.HEIC"))
        self.assertTrue(iphone.is_edited_name("IMG_E77.jpg"))
        self.assertFalse(iphone.is_edited_name("IMG_77.jpg"))


class Library(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.library = root / "Photos"
        self.config = Config(self.library, root / "Review", root / "x.db", False, 6)
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.ids: dict[str, int] = {}

    def add(self, rel: str, data: bytes = b"x", taken: str = "2024-03-05T10:00:00", **cols) -> int:
        path = self.library / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        cols = {"phash": None, "width": 4000, "height": 3000, "blur_score": 300.0, "detail_score": 40.0, **cols}
        cur = self.conn.execute(
            "INSERT INTO photos (path, size_bytes, mtime, sha256, taken_at, status, indexed_at, media_type, phash, "
            "width, height, blur_score, detail_score) VALUES (?, 1, 0, ?, ?, 'active', 'now', 'photo', ?, ?, ?, ?, ?)",
            (str(path), rel, taken, cols["phash"], cols["width"], cols["height"], cols["blur_score"], cols["detail_score"]),
        )
        self.conn.commit()
        self.ids[rel] = cur.lastrowid
        return cur.lastrowid


class SidecarTests(Library):
    def setUp(self) -> None:
        super().setUp()
        self.add("Camera Roll/IMG_1234.HEIC")
        (self.library / "Camera Roll" / "IMG_1234.AAE").write_text("<edits/>")
        self.add("Camera Roll/IMG_2000.JPG")

    def aae(self, folder: Path, stem: str = "IMG_1234") -> Path:
        return folder / f"{stem}.AAE"

    def test_removing_and_restoring_a_photo_carries_its_edit_file(self) -> None:
        pid = self.ids["Camera Roll/IMG_1234.HEIC"]
        quarantine_photo(self.conn, self.config, pid)
        moved = Path(self.conn.execute("SELECT path FROM photos WHERE id = ?", (pid,)).fetchone()["path"])
        self.assertTrue(self.aae(moved.parent).exists())
        self.assertFalse(self.aae(self.library / "Camera Roll").exists())

        restore_photo(self.conn, self.config, pid)
        self.assertEqual(self.aae(self.library / "Camera Roll").read_text(), "<edits/>")
        self.assertFalse(any(self.config.quarantine_dir.rglob("*.AAE")))

    def test_deleting_for_good_removes_the_edit_file_only_inside_the_review_folder(self) -> None:
        pid = self.ids["Camera Roll/IMG_1234.HEIC"]
        quarantine_photo(self.conn, self.config, pid)
        stray = self.library / "Camera Roll" / "IMG_2000.AAE"      # belongs to a photo that stays
        stray.write_text("keep me")
        purge_photos(self.conn, self.config, [pid])
        self.assertFalse(any(self.config.quarantine_dir.rglob("*.AAE")))
        self.assertTrue(stray.exists())

    def test_filing_and_undoing_organize_carries_the_edit_file(self) -> None:
        dest = Path(self.tmp.name) / "Filed"
        run_organize(self.conn, dest, self.library)
        filed = Path(self.conn.execute("SELECT path FROM photos WHERE id = ?", (self.ids["Camera Roll/IMG_1234.HEIC"],))
                     .fetchone()["path"])
        self.assertTrue(self.aae(filed.parent).exists())
        self.assertFalse(self.aae(self.library / "Camera Roll").exists())
        undo_organize(self.conn)
        self.assertTrue(self.aae(self.library / "Camera Roll").exists())

    def test_it_is_left_alone_while_another_photo_with_the_name_remains(self) -> None:
        self.add("Camera Roll/IMG_1234.JPG")                         # a second file with the same name
        quarantine_photo(self.conn, self.config, self.ids["Camera Roll/IMG_1234.HEIC"])
        self.assertTrue(self.aae(self.library / "Camera Roll").exists())

    def test_the_live_photo_clip_and_edit_file_both_go(self) -> None:
        clip = self.library / "Camera Roll" / "IMG_1234.MOV"
        clip.write_bytes(b"clip")
        self.conn.execute("UPDATE photos SET live_pair_path = ? WHERE id = ?", (str(clip), self.ids["Camera Roll/IMG_1234.HEIC"]))
        self.conn.commit()
        quarantine_photo(self.conn, self.config, self.ids["Camera Roll/IMG_1234.HEIC"])
        self.assertFalse(clip.exists())
        self.assertFalse(self.aae(self.library / "Camera Roll").exists())
        self.assertEqual(len(list(self.config.quarantine_dir.rglob("IMG_1234.*"))), 3)


class EditedCopyTests(Library):
    def test_an_edit_joins_its_original_even_when_the_pictures_no_longer_look_alike(self) -> None:
        original = self.add("Camera Roll/IMG_1234.HEIC", phash=f"{0x0123456789ABCDEF:016x}", width=4032, height=3024)
        edited = self.add("Camera Roll/IMG_E1234.JPG", phash=f"{0xFEDCBA9876543210:016x}", width=2800, height=2100)
        other = self.add("Camera Roll/IMG_9999.JPG", phash=f"{0x5555AAAA5555AAAA:016x}")
        self.assertEqual(dedupe.cluster_near_duplicates(self.conn, 6), 1)
        groups = self.conn.execute("SELECT group_id, photo_id, is_keeper FROM dup_group_members").fetchall()
        self.assertEqual(sorted(r["photo_id"] for r in groups), sorted([original, edited]))
        self.assertEqual([r["photo_id"] for r in groups if r["is_keeper"]], [edited], "the edit is the suggested keeper")
        self.assertNotIn(other, [r["photo_id"] for r in groups])

    def test_an_edit_joins_the_set_its_original_is_already_in(self) -> None:
        base = 0x13579BDF02468ACE
        burst1 = self.add("Camera Roll/IMG_1000.HEIC", phash=f"{base:016x}")
        burst2 = self.add("Camera Roll/IMG_1001.HEIC", phash=f"{base ^ 0b11:016x}")
        edit = self.add("Camera Roll/IMG_E1001.JPG", phash=f"{0xAAAAAAAA55555555:016x}")
        dedupe.cluster_near_duplicates(self.conn, 6)
        members = sorted(r["photo_id"] for r in self.conn.execute("SELECT photo_id FROM dup_group_members"))
        self.assertEqual(members, sorted([burst1, burst2, edit]))

    def test_without_an_original_nothing_is_grouped(self) -> None:
        self.add("Camera Roll/IMG_E1234.JPG", phash=f"{0x0123456789ABCDEF:016x}")
        self.assertEqual(dedupe.cluster_near_duplicates(self.conn, 6), 0)

    def test_the_explanation_names_the_edit(self) -> None:
        keeper = {"keeper": True, "name": "IMG_E1234.JPG", "w": 2800, "h": 2100, "blur": 300.0, "dur": None}
        original = {"keeper": False, "name": "IMG_1234.HEIC", "w": 4032, "h": 3024, "blur": 310.0, "dur": None}
        self.assertEqual(_group_why("near", [keeper, original]), "Your edited version. The original is the rest of this set.")


if __name__ == "__main__":
    unittest.main()
