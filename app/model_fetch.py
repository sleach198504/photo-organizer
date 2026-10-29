"""Fetches the recognition model for the installer.

Setup runs `python -m app.model_fetch` once. The files, their sizes and their checksums are
listed in model_manifest.json, which ships inside the app, so a download is only ever accepted
if it is byte-for-byte what that version of the app was tested with. Interrupted downloads
resume where they stopped. This is the only place the app downloads anything; it is never
called while the app is running.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from . import onnx_clip

log = logging.getLogger(__name__)

MANIFEST_PATH = Path(__file__).with_name("model_manifest.json")
CHUNK = 1 << 20
ATTEMPTS = 5
REPORT_EVERY = 10  # percent


class FetchError(RuntimeError):
    pass


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_complete(path: Path, entry: dict) -> bool:
    return path.is_file() and path.stat().st_size == entry["size"] and sha256_of(path) == entry["sha256"]


def _mb(n: int) -> str:
    return f"{n / (1 << 20):,.0f} MB"


def _download(url: str, part: Path, entry: dict, say: Callable[[str], None]) -> None:
    """One attempt. Appends to `part` from wherever it stopped."""
    size = entry["size"]
    have = part.stat().st_size if part.exists() else 0
    if have > size:
        part.unlink()
        have = 0
    request = urllib.request.Request(url, headers={"User-Agent": "PhotoOrganizerSetup"})
    if have:
        request.add_header("Range", f"bytes={have}-")
    with urllib.request.urlopen(request, timeout=60) as response:
        if have and response.status != 206:  # the server ignored the range: start again
            have = 0
        mode = "ab" if have else "wb"
        next_report = (have * 100 // size // REPORT_EVERY + 1) * REPORT_EVERY
        with part.open(mode) as out:
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                have += len(chunk)
                percent = have * 100 // size
                if percent >= next_report:
                    say(f"  {entry['name']}: {_mb(have)} of {_mb(size)} ({min(percent, 100)}%)")
                    next_report = (percent // REPORT_EVERY + 1) * REPORT_EVERY


def fetch_model(
    dest: Path = onnx_clip.MODEL_DIR,
    base_url: str | None = None,
    manifest: dict | None = None,
    say: Callable[[str], None] = print,
    wait: Callable[[float], None] | None = None,
) -> None:
    """Makes `dest` hold exactly the files in the manifest, downloading only what is missing or
    damaged. Raises FetchError when a file cannot be fetched or does not match its checksum."""
    wait = wait or time.sleep
    manifest = manifest or load_manifest()
    base = (base_url or manifest["base_url"]).rstrip("/")
    dest.mkdir(parents=True, exist_ok=True)

    todo = [e for e in manifest["files"] if not _is_complete(dest / e["name"], e)]
    if not todo:
        say("The recognition model is already installed.")
        return
    say(f"Downloading the recognition model ({_mb(sum(e['size'] for e in todo))}, one time only)...")

    for entry in todo:
        target, part = dest / entry["name"], dest / (entry["name"] + ".part")
        say(f"Downloading {entry['name']} ({_mb(entry['size'])})...")
        last_error: Exception | None = None
        for attempt in range(1, ATTEMPTS + 1):
            try:
                _download(f"{base}/{entry['name']}", part, entry, say)
                if part.stat().st_size != entry["size"] or sha256_of(part) != entry["sha256"]:
                    part.unlink()
                    raise FetchError(f"{entry['name']} arrived damaged")
                shutil.move(str(part), str(target))
                last_error = None
                break
            except urllib.error.HTTPError as exc:
                exc.close()
                last_error = exc
                if exc.code == 416 and part.exists():  # our partial file does not fit the server's: restart it
                    part.unlink()
                elif exc.code in (401, 403, 404):
                    break  # retrying cannot help
            except (urllib.error.URLError, OSError, FetchError) as exc:
                last_error = exc
            if attempt < ATTEMPTS:
                say(f"  Connection problem ({last_error}). Trying again...")
                wait(min(30.0, 2.0 ** attempt))
        if last_error is not None:
            raise FetchError(f"Could not download {entry['name']}: {last_error}")

    if not onnx_clip.verify_files(dest):
        raise FetchError("The downloaded model files do not match their recorded checksums")
    say("The recognition model is ready.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download the recognition model (run by Setup).")
    parser.add_argument("--base-url", help="fetch from here instead of the address in the manifest (testing)")
    parser.add_argument("--dest", type=Path, default=onnx_clip.MODEL_DIR)
    args = parser.parse_args(argv)
    try:
        fetch_model(args.dest, args.base_url, say=lambda line: print(line, flush=True))
    except (FetchError, OSError, ValueError, KeyError) as exc:
        print(f"Could not get the recognition model: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
