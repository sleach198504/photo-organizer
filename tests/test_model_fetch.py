"""The installer's model download: checksums, resuming, and refusing anything that does not match."""
from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from app import model_fetch, onnx_clip

FILES = {"visual.onnx": b"v" * 300_000, "text.onnx": b"t" * 200_000, "tokenizer.json": b'{"tok": 1}'}


def make_model(folder: Path) -> dict:
    """Writes a tiny stand-in model and returns a manifest describing it."""
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in FILES.items():
        (folder / name).write_bytes(data)
    meta = {"files": {n: hashlib.sha256(d).hexdigest() for n, d in FILES.items()}}
    (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    entries = [
        {"name": n, "size": (folder / n).stat().st_size, "sha256": model_fetch.sha256_of(folder / n)}
        for n in onnx_clip.REQUIRED_FILES
    ]
    return {"base_url": "http://unused.invalid", "files": entries}


class RangeHandler(SimpleHTTPRequestHandler):
    """A static file server that also answers Range requests, like GitHub's does."""

    requests: list = []

    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:
        RangeHandler.requests.append((self.path, self.headers.get("Range")))
        path = Path(self.translate_path(self.path))
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        start = 0
        rng = self.headers.get("Range")
        if rng:
            start = int(rng.split("=")[1].rstrip("-"))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(data) - start))
        self.end_headers()
        self.wfile.write(data[start:])


class FetchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.hosted = self.root / "hosted"
        self.manifest = make_model(self.hosted)
        handler = partial(RangeHandler, directory=str(self.hosted))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.said: list[str] = []
        RangeHandler.requests = []

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def fetch(self, dest: Path) -> None:
        model_fetch.fetch_model(dest, self.base, self.manifest, self.said.append, wait=lambda s: None)

    def test_downloads_every_file_and_the_result_verifies(self) -> None:
        dest = self.root / "models"
        self.fetch(dest)
        self.assertTrue(onnx_clip.model_files_present(dest))
        self.assertTrue(onnx_clip.verify_files(dest))
        self.assertFalse(list(dest.glob("*.part")))
        self.assertTrue(any("ready" in line for line in self.said))

    def test_a_second_run_downloads_nothing(self) -> None:
        dest = self.root / "models"
        self.fetch(dest)
        RangeHandler.requests.clear()
        self.fetch(dest)
        self.assertEqual(RangeHandler.requests, [])
        self.assertIn("already installed", self.said[-1])

    def test_only_missing_or_damaged_files_are_fetched_again(self) -> None:
        dest = self.root / "models"
        self.fetch(dest)
        (dest / "text.onnx").write_bytes(b"damaged")
        (dest / "tokenizer.json").unlink()
        RangeHandler.requests.clear()
        self.fetch(dest)
        self.assertEqual(sorted(p for p, _ in RangeHandler.requests), ["/text.onnx", "/tokenizer.json"])
        self.assertTrue(onnx_clip.verify_files(dest))

    def test_an_interrupted_download_resumes_from_where_it_stopped(self) -> None:
        dest = self.root / "models"
        dest.mkdir()
        (dest / "visual.onnx.part").write_bytes(FILES["visual.onnx"][:100_000])
        self.fetch(dest)
        self.assertIn(("/visual.onnx", "bytes=100000-"), RangeHandler.requests)
        self.assertEqual((dest / "visual.onnx").read_bytes(), FILES["visual.onnx"])

    def test_a_leftover_partial_file_from_a_different_version_is_not_trusted(self) -> None:
        dest = self.root / "models"
        dest.mkdir()
        (dest / "visual.onnx.part").write_bytes(b"x" * 100_000)  # a plausible size, wrong bytes
        self.fetch(dest)  # the first attempt fails its checksum, the retry starts clean
        self.assertTrue(onnx_clip.verify_files(dest))

    def test_a_file_that_does_not_match_its_checksum_is_refused(self) -> None:
        (self.hosted / "text.onnx").write_bytes(b"t" * 200_000 + b"tampered")
        dest = self.root / "models"
        with self.assertRaisesRegex(model_fetch.FetchError, "text.onnx"):
            self.fetch(dest)
        self.assertFalse((dest / "text.onnx").exists(), "a bad file must never be left where the app would use it")

    def test_a_missing_file_fails_without_endless_retries(self) -> None:
        (self.hosted / "tokenizer.json").unlink()
        with self.assertRaisesRegex(model_fetch.FetchError, "tokenizer.json"):
            self.fetch(self.root / "models")
        self.assertEqual(sum(1 for p, _ in RangeHandler.requests if p == "/tokenizer.json"), 1)

    def test_the_command_reports_failure_with_a_message_and_exit_code(self) -> None:
        with mock.patch.object(model_fetch.time, "sleep"):
            code = model_fetch.main(["--base-url", self.base, "--dest", str(self.root / "elsewhere")])
        self.assertEqual(code, 1)  # the real manifest's files are not on this test server


class ManifestTests(unittest.TestCase):
    def test_the_shipped_manifest_lists_every_file_the_app_needs(self) -> None:
        manifest = model_fetch.load_manifest()
        self.assertEqual(sorted(e["name"] for e in manifest["files"]), sorted(onnx_clip.REQUIRED_FILES))
        self.assertTrue(manifest["base_url"].startswith("https://"))
        for entry in manifest["files"]:
            self.assertEqual(len(entry["sha256"]), 64)
            self.assertGreater(entry["size"], 0)


if __name__ == "__main__":
    unittest.main()
