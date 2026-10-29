"""The evaluation harness must itself be trustworthy: its scoring maths is checked by hand
here, and a tiny dataset is run through the real engine to prove the plumbing works."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dev.evalkit import metrics, report, synth, truth as truthmod
from dev.evalkit.engine import CurrentEngine
from dev.evalkit.score import headline, score


class MetricTests(unittest.TestCase):
    def test_pairwise_counts_pairs_not_groups(self) -> None:
        truth = [["a", "b", "c"], ["d", "e"]]
        predicted = [["a", "b"], ["c", "d", "e"]]
        m = metrics.pairwise_grouping(truth, predicted)
        # real pairs: ab ac bc de (4); found: ab de cd ce (4); correct: ab de (2)
        self.assertEqual((m["tp"], m["fp"], m["fn"]), (2, 2, 2))
        self.assertAlmostEqual(m["precision"], 0.5)
        self.assertAlmostEqual(m["recall"], 0.5)

    def test_perfect_and_empty_grouping(self) -> None:
        self.assertEqual(metrics.pairwise_grouping([["a", "b"]], [["b", "a"]])["f1"], 1.0)
        none = metrics.pairwise_grouping([["a", "b"]], [])
        self.assertEqual((none["tp"], none["recall"], none["f1"]), (0, 0.0, 0.0))
        self.assertIsNone(metrics.pairwise_grouping([], [])["f1"])

    def test_bcubed_rewards_leaving_strangers_alone(self) -> None:
        universe = ["a", "b", "c", "d"]
        perfect = metrics.bcubed([["a", "b"]], [["a", "b"]], universe)
        self.assertEqual((perfect["precision"], perfect["recall"]), (1.0, 1.0))
        lumped = metrics.bcubed([["a", "b"]], [["a", "b", "c", "d"]], universe)
        self.assertAlmostEqual(lumped["precision"], (0.5 + 0.5 + 0.25 + 0.25) / 4)
        self.assertEqual(lumped["recall"], 1.0)

    def test_shape_errors_name_merges_and_splits(self) -> None:
        shape = metrics.group_shape_errors([["a", "b"], ["c", "d"]], [["a", "b", "c"], ["d"]])
        self.assertEqual(shape["merged_groups"], 1)
        self.assertEqual(shape["split_groups"], 1)
        self.assertEqual(shape["largest_predicted_group"], 3)

    def test_keeper_accuracy_separates_wrong_from_ungrouped(self) -> None:
        cases = [
            {"id": "1", "best": ["a"], "chosen": "a", "tags": ["x"]},
            {"id": "2", "best": ["a"], "chosen": "b", "tags": ["x", "hard"]},
            {"id": "3", "best": ["a"], "chosen": None, "tags": ["hard"]},
        ]
        k = metrics.keeper_accuracy(cases)
        self.assertEqual(k["all"]["correct"], 1)
        self.assertEqual(k["all"]["answered"], 2)
        self.assertAlmostEqual(k["all"]["accuracy_when_answered"], 0.5)
        self.assertAlmostEqual(k["all"]["accuracy_overall"], 1 / 3)
        self.assertEqual(k["by_tag"]["hard"]["cases"], 2)
        self.assertEqual(k["wrong"], ["2"])

    def test_flag_scores_skip_unsure_photos(self) -> None:
        universe = ["a", "b", "c", "d", "e"]
        m = metrics.binary_flag(universe, positives={"a", "b"}, flagged={"a", "c", "e"}, unsure={"e"})
        self.assertEqual((m["tp"], m["fp"], m["fn"], m["tn"]), (1, 1, 1, 1))
        self.assertEqual(m["false_positive_paths"], ["c"])
        self.assertEqual(m["missed_paths"], ["b"])
        self.assertEqual(m["ignored_unsure"], 1)

    def test_average_precision(self) -> None:
        scores = {"a": 0.9, "b": 0.8, "c": 0.7, "d": 0.1}
        self.assertEqual(metrics.average_precision(scores, {"a", "b"}), 1.0)
        self.assertAlmostEqual(metrics.average_precision(scores, {"a", "c"}), (1 + 2 / 3) / 2)
        self.assertIsNone(metrics.average_precision(scores, set()))

    def test_multiclass_confusion(self) -> None:
        m = metrics.multiclass({"1": "food", "2": "food", "3": "doc"}, {"1": "food", "2": "doc"})
        self.assertAlmostEqual(m["accuracy"], 1 / 3)
        self.assertEqual(m["confusion"]["food"], {"food": 1, "doc": 1})
        self.assertEqual(m["confusion"]["doc"], {"other": 1})

    def test_retrieval(self) -> None:
        r = metrics.retrieval([
            {"text": "q1", "relevant": ["a"], "ranked": ["a", "b"]},
            {"text": "q2", "relevant": ["c"], "ranked": ["x", "c"]},
            {"text": "q3", "relevant": ["z"], "ranked": ["x", "y"]},
        ])
        self.assertAlmostEqual(r["recall_at_1"], 1 / 3)
        self.assertAlmostEqual(r["recall_at_5"], 2 / 3)
        self.assertAlmostEqual(r["mrr"], (1 + 0.5 + 0) / 3)


class TruthFileTests(unittest.TestCase):
    def test_bad_files_are_rejected_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "a.jpg").write_bytes(b"x")
            (folder / "b.jpg").write_bytes(b"x")
            good = truthmod.Truth("t", "test", ["near_duplicates"],
                                  groups=[truthmod.Group("g1", "near", ["a.jpg", "b.jpg"], ["a.jpg"])])
            truthmod.save(good, folder)
            self.assertEqual(truthmod.load(folder).groups[0].best, ["a.jpg"])

            bad = truthmod.Truth("t", "test", ["near_duplicates"],
                                 groups=[truthmod.Group("g1", "near", ["a.jpg", "missing.jpg"])])
            truthmod.save(bad, folder)
            with self.assertRaisesRegex(truthmod.TruthError, "missing"):
                truthmod.load(folder)

            overlap = truthmod.Truth("t", "test", ["near_duplicates"], groups=[
                truthmod.Group("g1", "near", ["a.jpg", "b.jpg"]), truthmod.Group("g2", "near", ["a.jpg", "b.jpg"])])
            truthmod.save(overlap, folder)
            with self.assertRaisesRegex(truthmod.TruthError, "groups"):
                truthmod.load(folder)

            best_outside = truthmod.Truth("t", "test", ["keeper"],
                                          groups=[truthmod.Group("g1", "near", ["a.jpg", "b.jpg"], ["c.jpg"])])
            truthmod.save(best_outside, folder)
            with self.assertRaisesRegex(truthmod.TruthError, "best"):
                truthmod.load(folder)


class EndToEndTests(unittest.TestCase):
    """Builds the smallest synthetic dataset and runs the real engine over it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.dataset = root / "ds"
        synth.build(cls.dataset, "tiny", seed=3)
        cls.truth = truthmod.load(cls.dataset)
        result = CurrentEngine(content=False, sweep=True).run(cls.dataset, root / "work")
        cls.result = result
        cls.scores = score(cls.truth, result)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_dataset_is_what_the_truth_says(self) -> None:
        self.assertEqual(len(self.result.paths), len(self.truth.notes))
        self.assertGreaterEqual(len(self.truth.groups), 10)

    def test_exact_copies_are_always_found(self) -> None:
        self.assertEqual(self.scores["exact"]["f1"], 1.0)

    def test_known_good_behaviour_does_not_regress(self) -> None:
        near = self.scores["near"]
        self.assertGreaterEqual(near["recall"], 0.9)
        keeper = self.scores["keeper"]["by_tag"]
        self.assertEqual(keeper["burst"]["accuracy_overall"], 1.0)
        self.assertEqual(keeper["recompressed"]["accuracy_overall"], 1.0)
        blurry = self.scores["flags"]["by_reason"]["blurry"]
        self.assertEqual(blurry["recall"], 1.0)

    def test_sweep_has_every_distance_and_recall_never_drops(self) -> None:
        sweep = self.scores["near"]["sweep"]
        self.assertEqual(list(sweep), [str(d) for d in range(15)])
        recalls = [row["recall"] for row in sweep.values()]
        self.assertEqual(recalls, sorted(recalls))

    def test_report_and_compare_render(self) -> None:
        run = report.build_run("ds", "current", self.scores, self.result.settings)
        text = report.markdown(run)
        self.assertIn("## Which photo to keep", text)
        self.assertIn("Threshold sweep", text)
        json.dumps(run, default=report._json_default)  # must serialise
        self.assertIn("near.f1", report.compare(run, run))
        self.assertIn("near.f1", headline(self.scores))


if __name__ == "__main__":
    unittest.main()
