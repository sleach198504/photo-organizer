"""Picks which of your photos to label, and sets up a labelling project.

Labelling a whole library is out of the question, and a plain random sample would hold
almost no duplicates. So the sample is deliberately mixed:

* ~45% *candidate sets*: photos that might be the same moment, found with a deliberately
  loose test (looks alike at Hamming distance up to 12, OR taken within 45 seconds of each
  other). Looser than the app's own test, so the sample also contains look-alikes the app
  would miss.
* ~20% *soft-focus candidates*: single photos spread across the sharpness range, weighted
  towards the soft end, where the app has to decide.
* ~35% *random singles*: photos with no look-alike and no neighbour in the whole library,
  which show what the app does to ordinary photos.

Because the sample is enriched, absolute rates will not match your whole library. The
numbers are for comparing one engine with another on the same photos.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

LOOSE_HASH_DISTANCE = 12
BURST_WINDOW_SECONDS = 45
MAX_CLUMP = 12           # keeps one screen readable; bigger sets are cut at this size
PAGE = 12                # singles are shown a page at a time
SHARE_GROUPS, SHARE_SOFT = 0.45, 0.20

PROJECTS_DIR = Path(__file__).resolve().parents[2] / "eval_data"


@dataclass
class Row:
    id: int
    phash: str | None
    when: float          # seconds since epoch (capture time, else file time)
    blur: float | None


def parse_when(taken_at: str | None, mtime: float) -> float:
    if taken_at:
        try:
            return datetime.fromisoformat(taken_at).timestamp()
        except ValueError:
            pass
    return float(mtime or 0)


def candidate_sets(rows: list[Row]) -> list[list[int]]:
    """Photos that might belong together, by look or by time. Sets of one are omitted."""
    import imagehash

    from app.dedupe import _BKTree, _UnionFind

    uf, tree = _UnionFind(), _BKTree()
    for row in rows:
        uf.find(row.id)
        if row.phash:
            h = imagehash.hex_to_hash(row.phash)
            for other in tree.query(h, LOOSE_HASH_DISTANCE):
                uf.union(row.id, other)
            tree.add(h, row.id)

    ordered = sorted(rows, key=lambda r: r.when)
    for a, b in zip(ordered, ordered[1:]):
        if b.when - a.when <= BURST_WINDOW_SECONDS:
            uf.union(a.id, b.id)

    when = {r.id: r.when for r in rows}
    groups: dict[int, list[int]] = {}
    for row in rows:
        groups.setdefault(uf.find(row.id), []).append(row.id)
    return [sorted(ids, key=lambda i: when[i]) for ids in groups.values() if len(ids) > 1]


def sample_clumps(rows: list[Row], count: int, seed: int) -> list[dict]:
    """Returns clumps: {"kind", "ids"}. Every photo appears at most once."""
    rng = random.Random(seed)
    sets = candidate_sets(rows)
    in_a_set = {i for ids in sets for i in ids}
    chosen: set[int] = set()
    clumps: list[dict] = []

    rng.shuffle(sets)
    for ids in sets:
        if len(chosen) >= count * SHARE_GROUPS:
            break
        ids = ids[:MAX_CLUMP]
        clumps.append({"kind": "candidate-set", "ids": ids})
        chosen.update(ids)

    singles = [r for r in rows if r.id not in in_a_set]
    rng.shuffle(singles)

    scored = sorted((r for r in singles if r.blur is not None), key=lambda r: r.blur)
    soft: list[Row] = []
    if scored:
        # Ten equal-sized bins by sharpness; the softest three are sampled twice as densely.
        size = max(1, len(scored) // 10)
        bins = [scored[i:i + size] for i in range(0, len(scored), size)][:10]
        weights = [2 if i < 3 else 1 for i in range(len(bins))]
        quota = count * SHARE_SOFT
        total = sum(w * len(b) for w, b in zip(weights, bins)) or 1
        for w, b in zip(weights, bins):
            take = min(len(b), round(quota * w * len(b) / total))
            soft.extend(rng.sample(b, take))
    soft_ids = {r.id for r in soft}

    rest = [r for r in singles if r.id not in soft_ids]
    random_pick = rest[: max(0, count - len(chosen) - len(soft))]

    for kind, picked in (("soft-focus-candidate", soft), ("random", random_pick)):
        ids = [r.id for r in picked]
        chosen.update(ids)
        for start in range(0, len(ids), PAGE):
            clumps.append({"kind": kind, "ids": ids[start:start + PAGE]})

    rng.shuffle(clumps)
    return clumps


def project_dir(name: str) -> Path:
    return PROJECTS_DIR / name


def prepare(source: Path, name: str, count: int = 400, seed: int = 5, say=print) -> Path:
    """Reads the photo folder (never modifies it), samples, and writes project.json."""
    from app.db import session
    from app.indexer import run_index
    from app.progress import Progress
    from app.quality import run_quality_scoring

    source = source.resolve()
    if not source.is_dir():
        raise SystemExit(f"{source} is not a folder")
    folder = project_dir(name)
    if (folder / "project.json").exists():
        raise SystemExit(f"{folder} already exists. Pick another name, or delete that folder to start over.")
    folder.mkdir(parents=True, exist_ok=True)

    last = [0.0]

    def printer(done, total, detail):
        import time

        if time.time() - last[0] > 3:
            last[0] = time.time()
            say(f"  {done:,}/{total or '?'} {detail or ''}")

    db_path = folder / "index.db"
    with session(db_path) as conn:
        say(f"Reading {source} (this only reads your photos; it can take a while for a large library)")
        run_index(conn, source, progress=Progress(printer))
        say("Checking sharpness")
        run_quality_scoring(conn, Progress(printer))
        db_rows = conn.execute(
            "SELECT id, path, width, height, taken_at, mtime, phash, blur_score, sha256, size_bytes "
            "FROM photos WHERE status = 'active' AND media_type = 'photo' AND error IS NULL"
        ).fetchall()

    if len(db_rows) < count:
        say(f"Only {len(db_rows)} photos found; labelling all of them.")
        count = len(db_rows)
    rows = [Row(r["id"], r["phash"], parse_when(r["taken_at"], r["mtime"]), r["blur_score"]) for r in db_rows]
    clumps = sample_clumps(rows, count, seed)

    by_id = {r["id"]: r for r in db_rows}
    photos, private = {}, {}
    for clump in clumps:
        for i in clump["ids"]:
            r = by_id[i]
            photos[str(i)] = {
                "rel": Path(r["path"]).resolve().relative_to(source).as_posix(),
                "w": r["width"], "h": r["height"], "taken": r["taken_at"], "bytes": r["size_bytes"],
            }
            private[str(i)] = {"sha256": r["sha256"]}  # never sent to the labelling page
    for n, clump in enumerate(clumps, 1):
        clump["id"] = n

    (folder / "project.json").write_text(json.dumps({
        "version": 1, "name": name, "source": str(source), "seed": seed, "library_size": len(db_rows),
        "clumps": clumps, "photos": photos, "private": private,
    }, indent=1), encoding="utf-8")
    kinds = {}
    for c in clumps:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + len(c["ids"])
    say(f"Sampled {sum(kinds.values())} photos from {len(db_rows):,}: " + ", ".join(f"{v} {k}" for k, v in kinds.items()))
    say(f"Project ready: {folder}")
    return folder
