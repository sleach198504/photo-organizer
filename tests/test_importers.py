"""Importers for public benchmark datasets, tried on small look-alike folders."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from dev.evalkit import importers, truth as truthmod
from dev.evalkit.engine import CurrentEngine
from dev.evalkit.score import score


def _picture(seed: int, blur: float = 0.0, size=(640, 480)) -> Image.Image:
    rng = np.random.RandomState(seed)
    base = Image.fromarray(rng.randint(0, 255, (size[1] // 8, size[0] // 8, 3), dtype=np.uint8)).resize(
        size, Image.Resampling.NEAREST)  # blocky shapes with hard edges
    grain = rng.randint(-12, 12, (size[1], size[0], 1))
    arr = np.clip(np.asarray(base).astype(np.int16) + grain, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    return img.filter(ImageFilter.GaussianBlur(blur)) if blur else img


class CerthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        seed = 0
        for folder, blur, n in (("TrainingSet/Undistorted", 0.0, 12), ("TrainingSet/Naturally-Blurred", 6.0, 6),
                                ("TrainingSet/Artificially-Blurred", 9.0, 4)):
            (self.root / folder).mkdir(parents=True)
            for _ in range(n):
                seed += 1
                _picture(seed, blur).save(self.root / folder / f"{seed:04d}.jpg", quality=92)

    def test_folder_names_decide_the_labels(self) -> None:
        for name, kind in (("TrainingSet/Undistorted/a.jpg", "sharp"), ("x/Naturally-Blurred/a.jpg", "natural"),
                           ("x/Artificially-Blurred/a.jpg", "artificial"), ("x/DigitalBlurSet/a.jpg", "artificial"),
                           ("x/unrelated/a.jpg", None)):
            self.assertEqual(importers.certh_kind(Path("/r") / name, Path("/r")), kind, name)

    def test_natural_only_leaves_artificial_blur_out_of_the_scores(self) -> None:
        t = importers.import_certh(self.root, "natural")
        self.assertEqual(len(t.flags), 6)
        self.assertEqual(len(t.unsure), 4)
        self.assertTrue(all(p.startswith("TrainingSet/Artificially-Blurred") for p in t.unsure))
        everything = importers.import_certh(self.root, "all")
        self.assertEqual((len(everything.flags), len(everything.unsure)), (10, 0))

    def test_unrecognised_folders_are_reported_not_guessed(self) -> None:
        (self.root / "Misc").mkdir()
        _picture(99).save(self.root / "Misc" / "z.jpg")
        with self.assertRaisesRegex(importers.ImportError_, "Misc"):
            importers.import_certh(self.root)

    def test_the_engine_can_be_scored_on_it(self) -> None:
        t = importers.import_certh(self.root, "natural")
        with tempfile.TemporaryDirectory() as work:
            result = CurrentEngine(content=False, sweep=False).run(self.root, Path(work))
        blurry = score(truthmod.load(self.root), result)["flags"]["by_reason"]["blurry"]
        self.assertEqual(blurry["recall"], 1.0)
        self.assertEqual(blurry["ignored_unsure"], 4)
        self.assertEqual(len(t.flags), blurry["positives"])


class CopydaysTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for sub in ("copydays_original", "copydays_strong"):
            (self.root / sub).mkdir()
        for block, copies in ((1000, 3), (1001, 2), (1002, 0)):
            _picture(block).save(self.root / "copydays_original" / f"{block}00.jpg")
            for k in range(1, copies + 1):
                _picture(block, blur=2.0 * k).save(self.root / "copydays_strong" / f"{block}{k:02d}.jpg")

    def test_groups_come_from_the_file_numbers(self) -> None:
        t = importers.import_copydays(self.root)
        by_id = {g.id: g for g in t.groups}
        self.assertEqual(set(by_id), {"copy1000", "copy1001"})        # 1002 is a lone distractor
        self.assertEqual(len(by_id["copy1000"].members), 4)
        self.assertEqual(by_id["copy1000"].best, ["copydays_original/100000.jpg"])
        self.assertEqual(set(t.tasks), {"near_duplicates", "keeper"})

    def test_a_folder_without_copies_explains_what_to_extract(self) -> None:
        for p in (self.root / "copydays_strong").iterdir():
            p.unlink()
        with self.assertRaisesRegex(importers.ImportError_, "copydays_strong"):
            importers.import_copydays(self.root)

    def test_other_folders_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            (Path(other) / "holiday.jpg").write_bytes(b"x")
            with self.assertRaisesRegex(importers.ImportError_, "Copydays-style"):
                importers.import_copydays(Path(other))


if __name__ == "__main__":
    unittest.main()
