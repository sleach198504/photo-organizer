"""End-to-end: a synthetic phone dump goes through scan, review, marking, applying,
restoring, deleting and organizing - over real HTTP, the way the window drives it."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.actions import purge_photos
from app.config import Config
from app.db import session
from app.paths import CONFIG_PATH

from .helpers import LiveServer, build_library


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="photo-organizer-lib-")
        cls.library = Path(cls.tmp.name) / "Photos"
        cls.expected = build_library(cls.library)
        cls.server = LiveServer().__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.__exit__(None, None, None)
        cls.tmp.cleanup()

    # -- helpers -----------------------------------------------------------

    def scan(self) -> dict:
        status, body = self.server.post("/api/scan/start", {"source_dir": str(self.library)})
        self.assertEqual(status, 200, body)
        job = self.server.wait_job("scan")
        self.assertEqual(job["state"], "done", job.get("error"))
        return job

    def apply_marks(self) -> dict:
        status, body = self.server.post("/api/marks/apply")
        self.assertEqual(status, 200, body)
        job = self.server.wait_job("apply")
        self.assertEqual(job["state"], "done", job.get("error"))
        return job["summary"]

    def first_near_group(self) -> dict:
        status, data = self.server.get("/api/review/near_duplicate?limit=5")
        self.assertEqual(status, 200)
        self.assertTrue(data["groups"], "expected at least one similar-photo group")
        return data["groups"][0]

    # -- the whole lifecycle, in the order a person would do it -------------

    def test_lifecycle(self) -> None:
        server = self.server

        # Settings validate before they are saved, with a message fit to show.
        status, body = server.put("/api/settings", {"source_dir": str(self.library / "does-not-exist")})
        self.assertEqual(status, 400)
        self.assertIn("doesn't exist", body["detail"])

        # Scan.
        job = self.scan()
        self.assertEqual([s["state"] for s in job["stages"]].count("error"), 0)
        self.assertGreaterEqual(job["summary"]["scanned"], self.expected["photos_total"])

        status, summary = server.get("/api/summary")
        self.assertEqual(summary["videos"], self.expected["videos"])
        self.assertGreaterEqual(summary["dated"], self.expected["photos_with_taken_at"])
        categories = {c["key"]: c for c in summary["review"]["categories"]}
        self.assertEqual(categories["exact_duplicate"]["count"], self.expected["exact_duplicate_groups"])
        self.assertGreaterEqual(categories["near_duplicate"]["count"], self.expected["burst_groups"])
        self.assertGreaterEqual(categories["blurry"]["count"], 1)

        # A similar-photos group has one suggested keeper, listed first, with a reason.
        group = self.first_near_group()
        keepers = [m for m in group["members"] if m["keeper"]]
        self.assertEqual(len(keepers), 1)
        self.assertTrue(group["members"][0]["keeper"])
        self.assertTrue(group["why"])
        others = [m["id"] for m in group["members"] if not m["keeper"]]
        self.assertTrue(others)

        # Media is served and cacheable forever (the URL carries the mtime).
        status, headers, data = server.get_raw(f"/media/thumb/{keepers[0]['id']}?v=1")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "image/jpeg")
        self.assertIn("immutable", headers["cache-control"])
        self.assertEqual(server.get_raw("/media/thumb/99999999")[0], 404)

        # Marking is free and reversible: it changes nothing on disk.
        photo_paths = {pid: Path(server.get(f"/api/photo/{pid}")[1]["path"]) for pid in others}
        status, result = server.put("/api/marks", {"ids": others, "mark": "remove"})
        self.assertEqual(result["remove"], len(others))
        self.assertTrue(all(v is None for v in result["previous"].values()))
        self.assertTrue(all(p.exists() for p in photo_paths.values()))

        # Accepting suggestions never overrides a decision made by hand.
        status, _ = server.put("/api/marks", {"ids": [keepers[0]["id"]], "mark": "remove"})
        status, suggested = server.post("/api/marks/suggest", {"kinds": ["near"]})
        status, marks = server.get("/api/marks")
        status, items = server.get("/api/marks/items?mark=remove&limit=1000")
        marked_remove = {i["id"] for i in items["items"]}
        self.assertIn(keepers[0]["id"], marked_remove, "a manual choice was overwritten by suggestions")
        server.put("/api/marks", {"ids": [keepers[0]["id"]], "mark": None})

        # Undo is exact: the server reports what each photo was before.
        status, result = server.put("/api/marks", {"ids": others[:1], "mark": "keep"})
        self.assertEqual(result["previous"][str(others[0])], "remove")
        server.put("/api/marks", {"ids": others[:1], "mark": "remove"})
        server.post("/api/marks/clear")
        server.put("/api/marks", {"ids": others, "mark": "remove"})

        # Apply: files move to the review folder and are recorded for restore.
        applied = self.apply_marks()
        self.assertEqual(applied["moved"], len(others))
        self.assertEqual(applied["failed"], 0)
        self.assertTrue(all(not p.exists() for p in photo_paths.values()), "files should have left the library")
        status, removed = server.get("/api/removed")
        self.assertEqual(removed["total"], len(others))
        self.assertEqual(server.get("/api/marks")[1]["remove"], 0, "applied marks are cleared")

        # Restore puts every file back exactly where it was.
        status, restored = server.post("/api/removed/restore", {"ids": applied["moved_ids"]})
        self.assertEqual(restored, {"restored": len(others), "failed": 0})
        self.assertTrue(all(p.exists() for p in photo_paths.values()), "restore should return files to their folders")
        self.assertEqual(server.get("/api/removed")[1]["total"], 0)

        # Deleting for good needs the typed token, and only ever touches the review folder.
        server.put("/api/marks", {"ids": others, "mark": "remove"})
        self.apply_marks()
        status, body = server.post("/api/removed/purge", {"ids": None})
        self.assertEqual(status, 400)
        self.assertTrue(all(not p.exists() for p in photo_paths.values()))
        status, purged = server.post("/api/removed/purge", {"ids": None, "confirm": "DELETE"})
        self.assertEqual(purged["deleted"], len(others))
        self.assertEqual(server.get("/api/removed")[1]["total"], 0)

        self._purge_refuses_files_outside_the_review_folder()

        # Organize: preview equals what happens, labels are folder names (not Windows paths).
        status, info = server.get("/api/organize/state")
        self.assertTrue(all("\\" not in f["folder"] for f in info["folders"]))
        dest = Path(self.tmp.name) / "Organized"
        request = {"dest_dir": str(dest), "template": "year_month", "excluded": [], "exclude_mode": "skip"}
        status, preview = server.post("/api/organize/preview", request)
        self.assertEqual(status, 200, preview)
        self.assertGreater(preview["moving"], 0)
        self.assertFalse(dest.exists(), "previewing must not create or move anything")

        before = sorted(p.relative_to(self.library).as_posix() for p in self.library.rglob("*") if p.is_file())
        self.assertIsNone(server.get("/api/organize/state")[1]["undo"], "nothing to undo before filing")

        status, _ = server.post("/api/organize/start", request)
        self.assertEqual(status, 200)
        job = server.wait_job("organize")
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertEqual(job["summary"]["moved"], preview["moving"])
        filed = [p for p in dest.rglob("*") if p.is_file()]
        self.assertEqual(len(filed), preview["moving"])
        self.assertTrue(all(len(p.relative_to(dest).parts) >= 2 for p in filed), "files should be inside dated folders")

        # The last Organize can be undone: every file returns to where it was, and the dated
        # folders that were created are tidied away.
        status, info = server.get("/api/organize/state")
        self.assertEqual(info["undo"]["count"], preview["moving"])
        status, _ = server.post("/api/organize/undo")
        self.assertEqual(status, 200)
        job = server.wait_job("undo_organize")
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertEqual(job["summary"]["restored"], preview["moving"])
        self.assertEqual((job["summary"]["missing"], job["summary"]["renamed"], job["summary"]["problems"]), (0, 0, 0))
        after = sorted(p.relative_to(self.library).as_posix() for p in self.library.rglob("*") if p.is_file())
        self.assertEqual(after, before, "undo should leave the library exactly as it was")
        self.assertFalse(dest.exists(), "the destination Organize created should be gone")
        self.assertIsNone(server.get("/api/organize/state")[1]["undo"])
        self.assertEqual(server.post("/api/organize/undo")[0], 400, "a second undo has nothing to do")

    def _purge_refuses_files_outside_the_review_folder(self) -> None:
        """Even a corrupted database row must never get a real photo deleted."""
        config = Config.load(CONFIG_PATH)
        outside = Path(self.tmp.name) / "precious.jpg"
        outside.write_bytes(b"not really a photo")
        with session(config.db_path) as conn:
            conn.execute(
                "INSERT INTO photos (path, size_bytes, mtime, sha256, status, indexed_at) "
                "VALUES (?, 1, 0, 'x', 'quarantined', 'now')",
                (str(outside),),
            )
            conn.commit()
            result = purge_photos(conn, config, None)
            conn.execute("DELETE FROM photos WHERE path = ?", (str(outside),))
            conn.commit()
        self.assertTrue(outside.exists())
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["errors"], 1)


if __name__ == "__main__":
    unittest.main()
