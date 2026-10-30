"""Proves a built payload works, using the payload's own Python.

    build\\payload\\runtime\\python.exe packaging\\smoke_payload.py build\\payload <a folder of photos>

It runs the app out of the payload exactly as the launcher would, but with a throwaway
%LocalAppData% so it never touches real settings or data: package detection, a first-run config,
the web app, the recognition model, and a full scan of the given folder.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path


def main() -> int:
    payload, photos = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    scratch = tempfile.mkdtemp(prefix="po-smoke-")
    os.environ["LOCALAPPDATA"] = scratch
    os.environ.pop("PHOTO_ORGANIZER_HOME", None)

    problems: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("ok    " if ok else "FAIL  ") + what, flush=True)
        if not ok:
            problems.append(what)

    check(sys.version_info[:2] == (3, 12), f"runs on Python 3.12 (got {sys.version.split()[0]})")
    check(Path(sys.executable).resolve().parent == payload / "runtime", "is the payload's own Python")

    from app import content_tagging, paths

    check(paths.CODE_ROOT == payload, "the app is the payload's copy")
    check(paths.CHANNEL in ("store", "installer"), f"knows it is a packaged build ({paths.CHANNEL})")
    check(paths.APP_HOME == (Path(scratch) / "Photo Organizer").resolve(), "keeps its data under %LocalAppData%")

    check(content_tagging.models_downloaded(), "the recognition model is present")
    backend = content_tagging.create_backend()
    check(type(backend).__name__ == "OnnxClipBackend", "the model verifies and loads (ONNX, no PyTorch)")
    for banned in ("torch", "transformers", "tkinter"):
        try:
            __import__(banned)
            check(False, f"{banned} is not present")
        except ImportError:
            check(True, f"{banned} is not present")

    from app.jobs import Job
    from app.pipeline import SCAN_STAGES, run_scan
    from app.settings import get_config, read_settings, update_settings
    from app.web.app import create_app

    create_app()
    check(True, "the web app starts")
    update_settings({"source_dir": str(photos)})
    check((paths.APP_HOME / "config.yaml").is_file(), "the first-run settings file is created")
    job = Job("scan", SCAN_STAGES)
    job.start()
    worker = threading.Thread(target=run_scan, args=(job, get_config(), read_settings()), daemon=True)
    worker.start()
    worker.join(600)
    snapshot = job.snapshot()
    check(snapshot["state"] == "done", f"a full scan finishes ({snapshot['state']}, {snapshot.get('error')})")
    stages = {s["key"]: s["state"] for s in snapshot["stages"]}
    check(stages.get("content") == "done", f"recognition ran ({stages.get('content')})")
    result = snapshot.get("summary") or {}
    check(result.get("scanned", 0) > 0 and result.get("problems", 1) == 0, f"photos read without problems ({result})")
    check(not (payload / "config.yaml").exists() and not (payload / "data").exists(), "nothing was written into the payload")

    print("\nPASSED" if not problems else f"\n{len(problems)} problem(s)", flush=True)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
