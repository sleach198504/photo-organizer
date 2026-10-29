"""Saving labels, and turning a finished labelling project into an evaluation dataset."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from . import truth as truthmod

CATEGORIES = ("other", "food", "screenshot", "document", "meme", "whiteboard", "blank")
BLUR = ("sharp", "soft", "unsure")
DATASET = "dataset"


class LabelError(ValueError):
    pass


def empty_labels() -> dict:
    return {"version": 1, "done": [], "photos": {}, "groups": [], "queries": []}


def load_project(folder: Path) -> dict:
    path = folder / "project.json"
    if not path.exists():
        raise LabelError(f"{path} not found. Run `prepare` first.")
    return json.loads(path.read_text(encoding="utf-8"))


def load_labels(folder: Path) -> dict:
    path = folder / "labels.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty_labels()


def validate_labels(labels: dict, project: dict) -> None:
    """Rejects a malformed save so a bug in the page can never corrupt hours of work."""
    photos = set(project["photos"])
    clumps = {c["id"] for c in project["clumps"]}
    if labels.get("version") != 1:
        raise LabelError("unsupported labels version")
    if not set(labels["done"]) <= clumps:
        raise LabelError("done lists a clump that does not exist")
    for pid, entry in labels["photos"].items():
        if pid not in photos:
            raise LabelError(f"unknown photo {pid}")
        if entry.get("cat") not in CATEGORIES:
            raise LabelError(f"photo {pid}: unknown category {entry.get('cat')!r}")
        if entry.get("blur") not in (*BLUR, None):
            raise LabelError(f"photo {pid}: unknown sharpness {entry.get('blur')!r}")
    seen: dict[str, str] = {}
    for group in labels["groups"]:
        if len(group["members"]) < 2:
            raise LabelError(f"group {group['id']} has fewer than two photos")
        if not set(group["best"]) <= set(group["members"]):
            raise LabelError(f"group {group['id']}: best must be members")
        for pid in group["members"]:
            if pid not in photos:
                raise LabelError(f"group {group['id']}: unknown photo {pid}")
            if pid in seen:
                raise LabelError(f"photo {pid} is in two groups")
            seen[pid] = group["id"]
    for query in labels["queries"]:
        if not set(query["relevant"]) <= photos:
            raise LabelError("a search query lists an unknown photo")


def save_labels(folder: Path, labels: dict) -> None:
    validate_labels(labels, load_project(folder))
    tmp = folder / "labels.json.tmp"
    tmp.write_text(json.dumps(labels, indent=1), encoding="utf-8")
    os.replace(tmp, folder / "labels.json")  # atomic: a crash never leaves half a file


def progress(project: dict, labels: dict) -> dict:
    done = set(labels["done"])
    total = sum(len(c["ids"]) for c in project["clumps"])
    finished = sum(len(c["ids"]) for c in project["clumps"] if c["id"] in done)
    return {"clumps": len(project["clumps"]), "clumps_done": len(done), "photos": total, "photos_done": finished}


def export(folder: Path) -> dict:
    """Copies every finished photo into <project>/dataset/photos and writes its truth.json.
    The originals are only read. Photos in clumps you have not finished are left out, so
    the dataset is fully labelled for every task it lists."""
    project, labels = load_project(folder), load_labels(folder)
    validate_labels(labels, project)
    done = set(labels["done"])
    if not done:
        raise LabelError("Nothing is finished yet. Finish at least one set of photos first.")

    dataset = folder / DATASET
    if dataset.exists():
        if dataset.resolve().parent != folder.resolve():
            raise LabelError("refusing to clear an unexpected folder")
        shutil.rmtree(dataset)  # our own earlier export; rebuilt below from the labels
    photos_dir = dataset / "photos"
    source = Path(project["source"])

    ids = [i for c in project["clumps"] if c["id"] in done for i in map(str, c["ids"])]
    rel_of = {i: project["photos"][i]["rel"] for i in ids}
    missing = [rel for rel in rel_of.values() if not (source / rel).is_file()]
    if missing:
        raise LabelError(f"{len(missing)} photo(s) have moved or been deleted since preparing, e.g. {missing[0]}")
    for i, rel in rel_of.items():
        target = photos_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, target)  # keeps the modified date the app reads

    def entry(i: str) -> dict:
        return labels["photos"].get(i, {"cat": "other", "blur": "sharp"})

    flags, unsure, categories = {}, {}, {}
    for i in ids:
        e, rel = entry(i), rel_of[i]
        categories[rel] = e["cat"]
        names = [] if e["cat"] == "other" else [e["cat"]]
        if e["blur"] == "soft":
            names.append("blurry")
        if names:
            flags[rel] = names
        if e["blur"] == "unsure":
            unsure[rel] = ["blurry"]

    groups, taken = [], set()
    for n, g in enumerate(labels["groups"], 1):
        members = [str(m) for m in g["members"]]
        if not all(m in rel_of for m in members):
            continue  # a group spanning a clump that is not finished yet
        taken.update(members)
        groups.append(truthmod.Group(
            id=f"near{n}", kind="near", members=[rel_of[m] for m in members],
            best=[rel_of[b] for b in map(str, g["best"])], tags=["hand-labelled"]))

    by_hash: dict[str, list[str]] = {}
    for i in ids:
        by_hash.setdefault(project["private"][i]["sha256"], []).append(rel_of[i])
    for n, members in enumerate((m for m in by_hash.values() if len(m) > 1), 1):
        groups.append(truthmod.Group(id=f"exact{n}", kind="exact", members=sorted(members),
                                     best=sorted(members), tags=["byte-identical"]))

    queries = [truthmod.Query(q["text"], [rel_of[str(p)] for p in q["relevant"] if str(p) in rel_of])
               for q in labels["queries"] if q["text"].strip()]
    queries = [q for q in queries if q.relevant]

    tasks = ["near_duplicates", "flags", "categories"]
    if any(g.best and g.kind == "near" for g in groups):
        tasks.insert(1, "keeper")
    if queries:
        tasks.append("search")
    truth = truthmod.Truth(
        name=project["name"], source="hand-labelled", tasks=tasks, groups=groups, flags=flags,
        unsure=unsure, categories=categories, queries=queries, content_reliable=True)
    truthmod.save(truth, photos_dir)
    truthmod.load(photos_dir)  # prove the file is valid
    return {
        "dataset": str(photos_dir),
        "photos": len(ids),
        "near_groups": sum(1 for g in groups if g.kind == "near"),
        "exact_groups": sum(1 for g in groups if g.kind == "exact"),
        "groups_without_best": sum(1 for g in groups if g.kind == "near" and not g.best),
        "soft": sum(1 for e in map(entry, ids) if e["blur"] == "soft"),
        "queries": len(queries),
        "tasks": tasks,
    }
