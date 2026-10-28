"""Run the full scan pipeline from the command line against a library, printing
live progress. Developer tool: set PHOTO_ORGANIZER_HOME to an isolated folder first so
this never touches real settings or databases.

    set PHOTO_ORGANIZER_HOME=C:\\scratch\\home
    python dev/run_scan_cli.py C:\\scratch\\demo_lib
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import paths  # noqa: E402
from app.jobs import Job  # noqa: E402
from app.pipeline import SCAN_STAGES, run_scan  # noqa: E402
from app.settings import get_config, read_settings, update_settings  # noqa: E402


def main() -> None:
    source = Path(sys.argv[1]).resolve()
    print(f"home   : {paths.APP_HOME}")
    print(f"source : {source}")
    update_settings({"source_dir": str(source)})
    config, settings = get_config(), read_settings()

    job = Job("scan", SCAN_STAGES)
    job.start()
    worker = threading.Thread(target=run_scan, args=(job, config, settings), daemon=True)
    worker.start()

    last = ""
    while worker.is_alive():
        snap = job.snapshot()
        running = next((s for s in snap["stages"] if s["state"] == "running"), None)
        line = (
            f"  {running['label']}: {running['done']}/{running['total']}  {running['detail'] or ''}"
            if running else ""
        )
        if line != last:
            print(line)
            last = line
        time.sleep(0.4)

    snap = job.snapshot()
    print("\nstate  :", snap["state"], "| error:", snap["error"])
    for s in snap["stages"]:
        print(f"  [{s['state']:7}] {s['label']}  {s['note'] or ''}")
    print("summary:", snap["summary"])
    if snap["warnings"]:
        print("warnings:", snap["warnings"][:5])


if __name__ == "__main__":
    main()
