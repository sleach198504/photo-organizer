"""The labelling tool: sampling, saving, exporting and the local page's server."""
from __future__ import annotations

import json
import random
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from dev.evalkit import label_server, label_store, prepare, truth as truthmod


def _hash(bits: int) -> str:
    return f"{bits:016x}"


def _flip(bits: int, n: int, rng: random.Random) -> int:
    for position in rng.sample(range(64), n):
        bits ^= 1 << position
    return bits


class SamplingTests(unittest.TestCase):
    def setUp(self) -> None:
        rng = random.Random(1)
        self.rows: list[prepare.Row] = []
        i = 0
        # 10 look-alike pairs far apart in time, 10 time-adjacent bursts of unrelated pictures,
        # and 200 ordinary photos with nothing near them in look or time.
        for k in range(10):
            base = rng.getrandbits(64)
            for flips in (0, 3):
                i += 1
                self.rows.append(prepare.Row(i, _hash(_flip(base, flips, rng)), 1_000_000 + k * 100_000 + flips * 9_000, 100.0))
        for k in range(10):
            for j in range(3):
                i += 1
                self.rows.append(prepare.Row(i, _hash(rng.getrandbits(64)), 5_000_000 + k * 100_000 + j * 10, 100.0))
        for k in range(200):
            i += 1
            self.rows.append(prepare.Row(i, _hash(rng.getrandbits(64)), 20_000_000 + k * 50_000, float(k + 1)))

    def test_candidate_sets_find_look_alikes_and_bursts_only(self) -> None:
        sets = prepare.candidate_sets(self.rows)
        sizes = sorted(len(s) for s in sets)
        self.assertEqual(sizes, [2] * 10 + [3] * 10)
        self.assertTrue(all(len(set(s)) == len(s) for s in sets))

    def test_sample_has_no_repeats_and_respects_page_sizes(self) -> None:
        clumps = prepare.sample_clumps(self.rows, 100, seed=3)
        all_ids = [i for c in clumps for i in c["ids"]]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        for c in clumps:
            limit = prepare.MAX_CLUMP if c["kind"] == "candidate-set" else prepare.PAGE
            self.assertLessEqual(len(c["ids"]), limit)
        self.assertGreaterEqual(len(all_ids), 90)

    def test_sample_mixes_the_three_kinds_and_singles_have_no_neighbours(self) -> None:
        clumps = prepare.sample_clumps(self.rows, 100, seed=3)
        kinds = {c["kind"] for c in clumps}
        self.assertEqual(kinds, {"candidate-set", "soft-focus-candidate", "random"})
        in_a_set = {i for s in prepare.candidate_sets(self.rows) for i in s}
        for c in clumps:
            if c["kind"] != "candidate-set":
                self.assertFalse(set(c["ids"]) & in_a_set)

    def test_soft_candidates_lean_towards_the_soft_end(self) -> None:
        clumps = prepare.sample_clumps(self.rows, 120, seed=9)
        blur = {r.id: r.blur for r in self.rows}
        soft = [blur[i] for c in clumps if c["kind"] == "soft-focus-candidate" for i in c["ids"]]
        self.assertTrue(soft)
        self.assertLess(sum(soft) / len(soft), 100.5)  # the plain median of the 1..200 scores

    def test_same_seed_same_sample(self) -> None:
        a = prepare.sample_clumps(self.rows, 100, seed=4)
        b = prepare.sample_clumps(self.rows, 100, seed=4)
        self.assertEqual(a, b)
        self.assertNotEqual(a, prepare.sample_clumps(self.rows, 100, seed=5))


def _make_project(root: Path) -> Path:
    """A tiny project: 5 photos, two of them byte-identical copies."""
    source = root / "library"
    source.mkdir()
    for name, colour in (("a.jpg", (200, 30, 30)), ("b.jpg", (30, 200, 30)), ("c.jpg", (30, 30, 200)), ("d.jpg", (90, 90, 90))):
        Image.new("RGB", (64, 48), colour).save(source / name)
    shutil.copy2(source / "a.jpg", source / "a_copy.jpg")
    folder = root / "project"
    folder.mkdir()
    names = ["a.jpg", "a_copy.jpg", "b.jpg", "c.jpg", "d.jpg"]
    sha = {"a.jpg": "A", "a_copy.jpg": "A", "b.jpg": "B", "c.jpg": "C", "d.jpg": "D"}
    (folder / "project.json").write_text(json.dumps({
        "version": 1, "name": "tiny", "source": str(source), "seed": 1, "library_size": 5,
        "clumps": [{"id": 1, "kind": "candidate-set", "ids": [1, 2, 3]}, {"id": 2, "kind": "random", "ids": [4, 5]}],
        "photos": {str(i): {"rel": n, "w": 64, "h": 48, "taken": None, "bytes": 1} for i, n in enumerate(names, 1)},
        "private": {str(i): {"sha256": sha[n]} for i, n in enumerate(names, 1)},
    }), encoding="utf-8")
    return folder


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = _make_project(Path(self.tmp.name))
        self.project = label_store.load_project(self.folder)

    def labels(self, **changes) -> dict:
        base = label_store.empty_labels()
        base.update(changes)
        return base

    def test_bad_labels_are_refused_and_good_ones_survive_a_reload(self) -> None:
        bad_cases = [
            self.labels(photos={"99": {"cat": "other", "blur": "sharp"}}),
            self.labels(photos={"1": {"cat": "pizza", "blur": "sharp"}}),
            self.labels(photos={"1": {"cat": "food", "blur": "fuzzy"}}),
            self.labels(groups=[{"id": "g1", "members": ["1"], "best": []}]),
            self.labels(groups=[{"id": "g1", "members": ["1", "2"], "best": ["3"]}]),
            self.labels(groups=[{"id": "g1", "members": ["1", "2"], "best": []},
                                {"id": "g2", "members": ["2", "3"], "best": []}]),
            self.labels(done=[42]),
            self.labels(queries=[{"text": "x", "relevant": ["77"]}]),
        ]
        for bad in bad_cases:
            with self.assertRaises(label_store.LabelError, msg=str(bad)):
                label_store.save_labels(self.folder, bad)
        self.assertFalse((self.folder / "labels.json").exists())

        good = self.labels(done=[1], photos={"1": {"cat": "food", "blur": "soft"}},
                           groups=[{"id": "g1", "members": ["1", "2"], "best": ["1"]}])
        label_store.save_labels(self.folder, good)
        self.assertEqual(label_store.load_labels(self.folder), good)
        self.assertFalse((self.folder / "labels.json.tmp").exists())

    def test_export_builds_a_valid_dataset_from_finished_sets_only(self) -> None:
        label_store.save_labels(self.folder, self.labels(
            done=[1],
            photos={"1": {"cat": "document", "blur": "soft"}, "2": {"cat": "other", "blur": "unsure"},
                    "3": {"cat": "other", "blur": "sharp"}},
            groups=[{"id": "g1", "members": ["1", "2"], "best": ["1", "2"]},
                    {"id": "g2", "members": ["3", "4"], "best": ["3"]}],     # spans a set not finished yet
            queries=[{"text": "red square", "relevant": ["1", "5"]}, {"text": "nothing", "relevant": []}],
        ))
        info = label_store.export(self.folder)
        photos = Path(info["dataset"])
        self.assertEqual(sorted(p.name for p in photos.glob("*.jpg")), ["a.jpg", "a_copy.jpg", "b.jpg"])

        truth = truthmod.load(photos)
        self.assertEqual(truth.source, "hand-labelled")
        self.assertEqual(set(truth.tasks), {"near_duplicates", "keeper", "flags", "categories", "search"})
        kinds = {g.kind: g for g in truth.groups}
        self.assertEqual(sorted(kinds["near"].members), ["a.jpg", "a_copy.jpg"])
        self.assertEqual(sorted(kinds["exact"].members), ["a.jpg", "a_copy.jpg"])  # found from the file hashes
        self.assertEqual(len([g for g in truth.groups if g.kind == "near"]), 1)   # the half-finished group is held back
        self.assertEqual(sorted(truth.flags["a.jpg"]), ["blurry", "document"])
        self.assertEqual(truth.unsure, {"a_copy.jpg": ["blurry"]})
        self.assertEqual(truth.categories, {"a.jpg": "document", "a_copy.jpg": "other", "b.jpg": "other"})
        self.assertEqual([(q.text, q.relevant) for q in truth.queries], [("red square", ["a.jpg"])])

    def test_export_only_reads_the_library(self) -> None:
        source = Path(self.project["source"])
        before = {p.name: (p.stat().st_mtime, p.stat().st_size) for p in source.iterdir()}
        label_store.save_labels(self.folder, self.labels(done=[1, 2]))
        label_store.export(self.folder)
        label_store.export(self.folder)  # a second export replaces the first cleanly
        self.assertEqual(before, {p.name: (p.stat().st_mtime, p.stat().st_size) for p in source.iterdir()})

    def test_export_explains_what_is_wrong(self) -> None:
        with self.assertRaisesRegex(label_store.LabelError, "Nothing is finished"):
            label_store.export(self.folder)
        label_store.save_labels(self.folder, self.labels(done=[1]))
        (Path(self.project["source"]) / "b.jpg").unlink()
        with self.assertRaisesRegex(label_store.LabelError, "moved or been deleted"):
            label_store.export(self.folder)


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = _make_project(Path(self.tmp.name))
        self.client = TestClient(label_server.create_app(self.folder), base_url="http://127.0.0.1:8767")

    def test_project_hides_what_would_bias_the_labeller(self) -> None:
        data = self.client.get("/api/project").json()
        self.assertNotIn("private", data["project"])
        self.assertNotIn("sha256", json.dumps(data))
        self.assertEqual(data["progress"]["photos"], 5)

    def test_saving_validates_and_reports_progress(self) -> None:
        ok = self.client.put("/api/labels", json={**label_store.empty_labels(), "done": [1]})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["progress"]["photos_done"], 3)
        bad = self.client.put("/api/labels", json={**label_store.empty_labels(), "done": [9]})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("Not saved", bad.json()["detail"])

    def test_images_render_at_each_size_and_unknown_ones_404(self) -> None:
        for size in ("thumb", "preview", "full"):
            res = self.client.get(f"/img/1?size={size}")
            self.assertEqual((res.status_code, res.headers["content-type"]), (200, "image/jpeg"))
        self.assertEqual(self.client.get("/img/999").status_code, 404)
        self.assertEqual(self.client.get("/img/1?size=huge").status_code, 404)
        self.assertEqual(self.client.get("/img/..%2F..%2Fproject.json").status_code, 404)

    def test_other_websites_cannot_reach_the_photos(self) -> None:
        self.assertEqual(self.client.get("/img/1", headers={"Host": "rebind.example"}).status_code, 403)
        self.assertEqual(self.client.put("/api/labels", json=label_store.empty_labels(),
                                         headers={"Origin": "https://evil.example"}).status_code, 403)

    def test_page_and_shared_styles_are_served(self) -> None:
        self.assertIn("Photo labelling", self.client.get("/").text)
        self.assertEqual(self.client.get("/ui/state.js").status_code, 200)
        self.assertEqual(self.client.get("/static/css/tokens.css").status_code, 200)


if __name__ == "__main__":
    unittest.main()
