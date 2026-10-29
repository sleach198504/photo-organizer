"""Builds a large library of tiny synthetic photos and times the API over it.

    python dev/stress_library.py 20000

Everything happens in a throwaway PHOTO_ORGANIZER_HOME (set by the tests package), so no
real data is touched. Recognition is skipped; this measures indexing, listing and review
queries, which are what a 50,000-photo library stresses.
"""
from __future__ import annotations

import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tests  # noqa: E402,F401  (points PHOTO_ORGANIZER_HOME at a temp folder)
from dev.make_demo_library import exif_bytes  # noqa: E402
from tests.helpers import LiveServer  # noqa: E402


def build(root: Path, n: int) -> None:
    rng = np.random.RandomState(1)
    start = datetime(2018, 1, 1, 8, 0)
    for i in range(n):
        folder = root / f"{2018 + i * 8 // n}" / f"batch{(i // 500):03d}"
        folder.mkdir(parents=True, exist_ok=True)
        # coarse random blocks, upscaled: distinct perceptual hashes, tiny files
        blocks = rng.randint(0, 255, (6, 8, 3), dtype="uint8")
        image = Image.fromarray(blocks).resize((256, 192), Image.NEAREST)
        taken = start + timedelta(minutes=int(i * (8 * 365 * 24 * 60) / n))
        image.save(folder / f"IMG_{i:06d}.jpg", "JPEG", quality=70, exif=exif_bytes(taken))
        if i % 97 == 0 and i:  # sprinkle exact duplicates
            (folder / f"IMG_{i:06d}_copy.jpg").write_bytes((folder / f"IMG_{i:06d}.jpg").read_bytes())


def timed(label: str, fn):
    t = time.perf_counter()
    result = fn()
    print(f"  {label:<44} {(time.perf_counter() - t) * 1000:8.0f} ms")
    return result


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    with tempfile.TemporaryDirectory(prefix="po-stress-") as tmp:
        library = Path(tmp) / "Photos"
        timed(f"build {n:,} images", lambda: build(library, n))
        with LiveServer() as server:
            timed("scan", lambda: (server.post("/api/scan/start", {"source_dir": str(library)}), server.wait_job("scan", 3600)))
            print("API timings:")
            _, summary = timed("GET /api/summary", lambda: server.get("/api/summary"))
            print(f"    items: {summary['photos']:,}  flagged: {summary['review']['flagged_photos']:,}")
            timed("GET /api/photos (first page)", lambda: server.get("/api/photos?kind=photo&limit=200"))
            timed("GET /api/photos (offset 15000)", lambda: server.get(f"/api/photos?kind=photo&offset={max(0, n - 5000)}&limit=200"))
            timed("GET /api/photos?sort=largest", lambda: server.get("/api/photos?kind=photo&sort=largest&limit=200"))
            timed("GET /api/timeline", lambda: server.get("/api/timeline?kind=photo"))
            timed("GET /api/review/overview", lambda: server.get("/api/review/overview"))
            timed("GET /api/review/exact_duplicate", lambda: server.get("/api/review/exact_duplicate?limit=20"))
            timed("GET /api/review/near_duplicate", lambda: server.get("/api/review/near_duplicate?limit=20"))
            timed("GET /api/review/blurry (first page+ids)", lambda: server.get("/api/review/blurry?limit=120"))
            ids = [i["id"] for i in server.get("/api/photos?kind=photo&limit=1000")[1]["items"]]
            timed("PUT /api/marks (1,000 ids)", lambda: server.put("/api/marks", {"ids": ids, "mark": "remove"}))
            timed("GET /api/summary (with marks)", lambda: server.get("/api/summary"))
            timed("POST /api/marks/apply (1,000 moves)", lambda: (server.post("/api/marks/apply"), server.wait_job("apply", 600)))


if __name__ == "__main__":
    main()
