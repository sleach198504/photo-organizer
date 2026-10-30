"""What gets flagged for review: only screenshots and truly empty frames. Documents, whiteboards, food
and memes are tags for filtering, never review items."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from app import content_tagging
from app.db import connect, get_meta
from app.review import CATEGORY_BY_KEY, review_overview
from app.summary import library_summary


def picture(fn) -> Image.Image:
    y, x = np.mgrid[0:96, 0:128]
    return Image.fromarray(np.clip(fn(x, y), 0, 255).astype(np.uint8), "L").convert("RGB")


class LooksEmptyTests(unittest.TestCase):
    def test_black_and_flat_frames_are_empty(self) -> None:
        self.assertTrue(content_tagging.looks_empty(Image.new("RGB", (200, 150), (0, 0, 0))))
        self.assertTrue(content_tagging.looks_empty(Image.new("RGB", (200, 150), (128, 128, 128))))
        self.assertTrue(content_tagging.looks_empty(Image.new("RGB", (200, 150), (255, 255, 255))))

    def test_a_pocket_shot_with_noise_is_empty(self) -> None:
        rng = np.random.RandomState(1)
        noise = picture(lambda x, y: 4 + rng.randint(0, 12, x.shape))
        self.assertTrue(content_tagging.looks_empty(noise))

    def test_a_night_scene_with_lit_windows_is_not_empty(self) -> None:
        def night(x, y):
            base = 25 + 0 * x
            return np.where((x % 24 < 6) & (y % 20 < 8), 230, base)  # windows

        self.assertFalse(content_tagging.looks_empty(picture(night)))

    def test_a_dim_picture_with_one_bright_light_is_not_empty(self) -> None:
        self.assertFalse(content_tagging.looks_empty(picture(lambda x, y: np.where((x - 64) ** 2 + (y - 48) ** 2 < 150, 240, 8))))

    def test_an_ordinary_photo_is_not_empty(self) -> None:
        rng = np.random.RandomState(2)
        self.assertFalse(content_tagging.looks_empty(picture(lambda x, y: 90 + 60 * np.sin(x / 9.0) + rng.randint(0, 30, x.shape))))


class ReviewCategoryTests(unittest.TestCase):
    def test_only_real_clutter_is_a_review_category(self) -> None:
        for key in ("document", "whiteboard", "food", "meme"):
            self.assertNotIn(key, CATEGORY_BY_KEY)
        for key in ("screenshot", "blank", "blurry"):
            self.assertIn(key, CATEGORY_BY_KEY)

    def test_the_model_is_no_longer_asked_about_blank(self) -> None:
        self.assertNotIn("blank", content_tagging.CATEGORY_PROMPTS)


class FlagPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.conn = connect(self.root / "index.db")
        self.addCleanup(self.conn.close)

    def photo(self, name: str, image: Image.Image, tag: str | None) -> int:
        path = self.root / name
        image.save(path)
        cur = self.conn.execute(
            "INSERT INTO photos (path, size_bytes, mtime, sha256, status, indexed_at, media_type, content_tags) "
            "VALUES (?, 1, 0, ?, 'active', 'now', 'photo', ?)",
            (str(path), name, tag),
        )
        return cur.lastrowid

    def flag(self, photo_id: int, reason: str, decision: str = "pending") -> None:
        self.conn.execute(
            "INSERT INTO recommendations (photo_id, reason, confidence, decision) VALUES (?, ?, 0.9, ?)",
            (photo_id, reason, decision),
        )

    def reasons(self, photo_id: int) -> list[tuple[str, str]]:
        return [(r["reason"], r["decision"]) for r in self.conn.execute(
            "SELECT reason, decision FROM recommendations WHERE photo_id = ? ORDER BY reason", (photo_id,))]

    def tag(self, photo_id: int) -> str | None:
        return self.conn.execute("SELECT content_tags FROM photos WHERE id = ?", (photo_id,)).fetchone()["content_tags"]

    def test_earlier_flags_are_tidied_once(self) -> None:
        night = self.photo("night.jpg", picture(lambda x, y: np.where((x % 24 < 6) & (y % 20 < 8), 230, 25)), "blank")
        black = self.photo("black.jpg", Image.new("RGB", (64, 48), (0, 0, 0)), "blank")
        receipt = self.photo("receipt.jpg", Image.new("RGB", (64, 48), (200, 200, 200)), "document")
        meal = self.photo("meal.jpg", Image.new("RGB", (64, 48), (200, 90, 40)), "food")
        kept = self.photo("kept.jpg", Image.new("RGB", (64, 48), (200, 90, 40)), "food")
        for pid, reason in ((night, "blank"), (black, "blank"), (receipt, "document"), (meal, "food")):
            self.flag(pid, reason)
        self.flag(kept, "food", decision="rejected")  # the person already looked at this one
        self.conn.commit()

        content_tagging.apply_flag_policy(self.conn)

        self.assertEqual(self.reasons(night), [])            # not empty: no longer flagged...
        self.assertIsNone(self.tag(night))                    # ...and no longer called blank
        self.assertEqual(self.reasons(black), [("blank", "pending")])  # really empty: stays
        self.assertEqual(self.tag(black), "blank")
        self.assertEqual(self.reasons(receipt), [])          # filter-only: flag gone
        self.assertEqual(self.tag(receipt), "document")       # tag kept, for the filter
        self.assertEqual(self.reasons(meal), [])
        self.assertEqual(self.reasons(kept), [("food", "rejected")])  # earlier decisions are left alone
        self.assertEqual(get_meta(self.conn, "flag_policy"), content_tagging.FLAG_POLICY_VERSION)

    def test_it_does_not_run_twice(self) -> None:
        content_tagging.apply_flag_policy(self.conn)
        later = self.photo("later.jpg", Image.new("RGB", (64, 48), (200, 90, 40)), "food")
        self.flag(later, "food")
        self.conn.commit()
        content_tagging.apply_flag_policy(self.conn)
        self.assertEqual(self.reasons(later), [("food", "pending")])

    def test_a_missing_file_does_not_stop_the_tidy_up(self) -> None:
        gone = self.photo("gone.jpg", Image.new("RGB", (64, 48), (0, 0, 0)), "blank")
        (self.root / "gone.jpg").unlink()
        self.flag(gone, "blank")
        self.conn.commit()
        content_tagging.apply_flag_policy(self.conn)  # must not raise
        self.assertEqual(get_meta(self.conn, "flag_policy"), content_tagging.FLAG_POLICY_VERSION)


class FilterCountTests(unittest.TestCase):
    def test_the_summary_counts_filterable_kinds_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "index.db")
            try:
                for i, tag in enumerate(["food", "food", "document", "screenshot", None]):
                    conn.execute(
                        "INSERT INTO photos (path, size_bytes, mtime, sha256, status, indexed_at, media_type, content_tags) "
                        "VALUES (?, 1, 0, ?, 'active', 'now', 'photo', ?)", (f"p{i}.jpg", str(i), tag))
                conn.commit()
                self.assertEqual(library_summary(conn)["tags"], {"food": 2, "document": 1})
                self.assertEqual(review_overview(conn)["flagged_photos"], 0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
