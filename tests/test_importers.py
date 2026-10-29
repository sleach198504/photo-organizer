"""Importers for public benchmark datasets, tried on small look-alike folders."""
from __future__ import annotations

import tempfile
import zipfile
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


def _write_xlsx(path: Path, rows: list[tuple[str, int]]) -> None:
    """A minimal two-column workbook shaped like CERTH's: names as shared strings, labels as numbers."""
    strings = ["Image Name"] + [name for name, _ in rows]
    shared = "".join(f"<si><t>{s}</t></si>" for s in strings)
    body = '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>0</v></c></row>'
    for i, (_, label) in enumerate(rows, start=2):
        body += f'<row r="{i}"><c r="A{i}" t="s"><v>{i - 1}</v></c><c r="B{i}"><v>{label}</v></c></row>'
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>{shared}</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{body}</sheetData></worksheet>")


class CerthSheetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        folder = self.root / "EvaluationSet" / "NaturalBlurSet"
        folder.mkdir(parents=True)
        digital = self.root / "EvaluationSet" / "DigitalBlurSet"
        digital.mkdir()
        for i, blur in enumerate((0, 0, 6, 6, 6), start=1):
            _picture(i, blur).save(folder / f"Original_{i}.jpg")
        for i, blur in enumerate((0, 9, 9), start=1):
            _picture(50 + i, blur).save(digital / f"DiskR10_{i}.jpg")
        # CERTH's own files: no extension in one, a trailing space and extension in the other
        _write_xlsx(self.root / "EvaluationSet" / "NaturalBlurSet.xlsx",
                    [(f"Original_{i}", label) for i, label in enumerate((-1, -1, 1, 1, 1), start=1)])
        _write_xlsx(self.root / "EvaluationSet" / "DigitalBlurSet.xlsx",
                    [(f"DiskR10_{i}.jpg ", label) for i, label in enumerate((-1, 1, 1), start=1)])

    def test_spreadsheet_labels_are_read(self) -> None:
        labels = importers.read_xlsx_labels(self.root / "EvaluationSet" / "NaturalBlurSet.xlsx")
        self.assertEqual(labels["Original_3"], 1)
        self.assertEqual(labels["Original_1"], -1)
        self.assertNotIn("Image Name", labels)

    def test_mixed_folders_are_labelled_by_their_spreadsheet(self) -> None:
        t = importers.import_certh(self.root, "natural")
        self.assertEqual(sorted(t.flags), [f"EvaluationSet/NaturalBlurSet/Original_{i}.jpg" for i in (3, 4, 5)])
        self.assertEqual(t.notes["EvaluationSet/NaturalBlurSet/Original_1.jpg"], "undistorted")
        self.assertEqual(t.notes["EvaluationSet/DigitalBlurSet/DiskR10_1.jpg"], "undistorted")
        self.assertEqual(len(t.unsure), 2)                      # the artificial ones, left out
        everything = importers.import_certh(self.root, "all")
        self.assertEqual(len(everything.flags), 5)

    def test_an_image_missing_from_its_spreadsheet_is_reported(self) -> None:
        _picture(99).save(self.root / "EvaluationSet" / "NaturalBlurSet" / "Original_99.jpg")
        with self.assertRaisesRegex(importers.ImportError_, "NaturalBlurSet"):
            importers.import_certh(self.root)
