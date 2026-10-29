"""Runs an engine over a dataset and returns its answers in one neutral shape.

`EngineResult` is what the scorer reads, so a different engine (for example the ONNX one
planned next) only has to produce the same fields to be compared on the same data.
`CurrentEngine` drives the app's real pipeline stages against a throwaway database; it
touches only the dataset folder (read-only) and its own work folder.
"""
from __future__ import annotations

import os
import platform
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import truth as truthmod

# Hamming distances tried when sweeping the near-duplicate threshold.
SWEEP_DISTANCES = tuple(range(0, 15))
GROUP_REASONS = {"exact_duplicate", "near_duplicate", "video_near_duplicate"}


@dataclass
class EngineResult:
    engine: str
    paths: list[str]
    exact_groups: list[list[str]]
    near_groups: list[dict]                 # [{"members": [...], "keeper": path}]
    flags: dict[str, set[str]]              # reason -> paths flagged
    sharpness: dict[str, float]             # path -> score, higher = sharper
    categories: dict[str, str]              # path -> category (absent = none)
    near_sweep: dict[int, list[list[str]]] = field(default_factory=dict)
    search: dict[str, list[str]] = field(default_factory=dict)   # query -> ranked paths
    timings: dict[str, float] = field(default_factory=dict)      # stage -> seconds
    settings: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def machine_info() -> dict:
    ram_gb = None
    try:
        import psutil

        ram_gb = round(psutil.virtual_memory().total / 2**30, 1)
    except Exception:
        pass
    return {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "ram_gb": ram_gb,
        "python": platform.python_version(),
    }


class CurrentEngine:
    """The engine as shipped today: pHash + BK-tree, Laplacian sharpness, CLIP."""

    name = "current"

    def __init__(self, content: bool = True, sweep: bool = True) -> None:
        self.content = content
        self.sweep = sweep

    def run(self, dataset: Path, workdir: Path, queries: list[truthmod.Query] | None = None) -> EngineResult:
        # Imported here so merely listing datasets never loads OpenCV or the model.
        from app import content_tagging
        from app.db import session
        from app.dedupe import run_dedupe
        from app.indexer import run_index
        from app.quality import flag_blurry_photos, run_quality_scoring
        from app.search import search_library
        from app.settings import SIMILARITY_PRESETS

        dataset = dataset.resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        db_path = workdir / "eval.db"
        if db_path.exists():
            db_path.unlink()

        distance = SIMILARITY_PRESETS["balanced"]
        timings: dict[str, float] = {}
        notes: list[str] = []
        queries = queries or []
        search: dict[str, list[str]] = {}

        def timed(stage: str, fn):
            started = time.perf_counter()
            value = fn()
            timings[stage] = round(time.perf_counter() - started, 3)
            return value

        with session(db_path) as conn:
            timed("index", lambda: run_index(conn, dataset))
            timed("sharpness", lambda: (run_quality_scoring(conn), flag_blurry_photos(conn)))

            def settle(d: int):
                run_dedupe(conn, d, auto_quarantine_exact_duplicates=False)

            near_sweep: dict[int, list[list[str]]] = {}
            if self.sweep:
                for d in SWEEP_DISTANCES:
                    settle(d)
                    near_sweep[d] = self._near_groups(conn, dataset, with_keepers=False)
            timed("duplicates", lambda: settle(distance))

            if self.content and content_tagging.models_downloaded():
                backend = timed("model_load", content_tagging.ClipBackend)
                timed("content", lambda: content_tagging.run_content_tagging(conn, backend))
                for q in queries:
                    ranked = search_library(conn, backend, q.text, top_k=50)
                    search[q.text] = [self._rel(conn, r["id"], dataset) for r in ranked]
            elif self.content:
                notes.append("The recognition model is not installed, so content flags and search were skipped.")
            else:
                notes.append("Content recognition was turned off for this run.")

            rows = conn.execute(
                "SELECT id, path, blur_score, content_tags FROM photos WHERE status = 'active' AND media_type = 'photo'"
            ).fetchall()
            rel = {r["id"]: self._to_rel(r["path"], dataset) for r in rows}

            flags: dict[str, set[str]] = {}
            for r in conn.execute(
                "SELECT photo_id, reason FROM recommendations WHERE decision = 'pending'"
            ):
                if r["reason"] in GROUP_REASONS or r["photo_id"] not in rel:
                    continue
                flags.setdefault(r["reason"], set()).add(rel[r["photo_id"]])

            exact = [
                [rel[i] for i in ids if i in rel]
                for ids in self._members(conn, "exact").values()
            ]
            result = EngineResult(
                engine=self.name,
                paths=sorted(rel.values()),
                exact_groups=[g for g in exact if len(g) > 1],
                near_groups=self._near_groups(conn, dataset, with_keepers=True),
                flags=flags,
                sharpness={rel[r["id"]]: r["blur_score"] for r in rows if r["blur_score"] is not None},
                categories={rel[r["id"]]: r["content_tags"] for r in rows if r["content_tags"]},
                near_sweep=near_sweep,
                search=search,
                timings=timings,
                settings={"near_duplicate_hash_distance": distance, "content": self.content},
                notes=notes,
            )
        return result

    # -- reading the database back ----------------------------------------

    @staticmethod
    def _to_rel(path: str, dataset: Path) -> str:
        return Path(path).resolve().relative_to(dataset).as_posix()

    def _rel(self, conn, photo_id: int, dataset: Path) -> str:
        row = conn.execute("SELECT path FROM photos WHERE id = ?", (photo_id,)).fetchone()
        return self._to_rel(row["path"], dataset)

    @staticmethod
    def _members(conn, kind: str) -> dict[int, list[int]]:
        out: dict[int, list[int]] = {}
        for r in conn.execute(
            "SELECT dgm.group_id, dgm.photo_id FROM dup_group_members dgm "
            "JOIN dup_groups dg ON dg.id = dgm.group_id WHERE dg.kind = ?", (kind,)
        ):
            out.setdefault(r["group_id"], []).append(r["photo_id"])
        return out

    def _near_groups(self, conn, dataset: Path, with_keepers: bool):
        """Near groups with the members of each exact-duplicate set folded into the group
        that holds their keeper, so 'same picture' is judged the way a person sees it."""
        paths = {r["id"]: self._to_rel(r["path"], dataset) for r in conn.execute("SELECT id, path FROM photos")}
        exact_of: dict[int, list[int]] = {}
        for ids in self._members(conn, "exact").values():
            for i in ids:
                exact_of[i] = ids
        groups = []
        for group_id, ids in self._members(conn, "near").items():
            keeper = conn.execute(
                "SELECT photo_id FROM dup_group_members WHERE group_id = ? AND is_keeper = 1", (group_id,)
            ).fetchone()["photo_id"]
            expanded = sorted({m for i in ids for m in exact_of.get(i, [i])})
            members = [paths[i] for i in expanded]
            groups.append({"members": members, "keeper": paths[keeper]} if with_keepers else members)
        return groups
