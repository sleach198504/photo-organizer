"""The ground-truth file that describes what the right answers are for a dataset.

A dataset is a folder of photos plus `truth.json` beside them. Paths are relative to the
folder and use forward slashes. Only the tasks listed in `tasks` are scored, and for those
tasks every photo that is not mentioned counts as a negative, so list a task only when
you labelled the whole folder for it.

    {
      "version": 1,
      "name": "synthetic-small",
      "source": "synthetic",
      "tasks": ["near_duplicates", "keeper", "flags"],
      "groups": [
        {"id": "g1", "kind": "near", "members": ["a.jpg", "b.jpg"], "best": ["a.jpg"],
         "tags": ["contested"]}
      ],
      "flags": {"c.jpg": ["blurry"]},
      "unsure": {"d.jpg": ["blurry"]},
      "categories": {"e.jpg": "food"},
      "queries": [{"text": "birthday cake", "relevant": ["e.jpg"]}]
    }

`best` lists every member that would be an acceptable keeper. `unsure` marks a photo whose
label a person could argue either way for that flag; it is left out of that flag's scores.
`content_reliable: false` says the pictures are generated, so flags that need the
recognition model (everything except blurry, and screenshots by file type) are not scored.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

TRUTH_FILE = "truth.json"
VERSION = 1
TASKS = ("near_duplicates", "keeper", "flags", "categories", "search")
GROUP_KINDS = ("near", "exact")


class TruthError(ValueError):
    pass


@dataclass
class Group:
    id: str
    kind: str
    members: list[str]
    best: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class Query:
    text: str
    relevant: list[str]


@dataclass
class Truth:
    name: str
    source: str
    tasks: list[str]
    groups: list[Group] = field(default_factory=list)
    flags: dict[str, list[str]] = field(default_factory=dict)
    unsure: dict[str, list[str]] = field(default_factory=dict)
    categories: dict[str, str] = field(default_factory=dict)
    queries: list[Query] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)  # path -> how it was made, for people reading failures
    # False for generated pictures: the recognition model is built for photographs and
    # mislabels abstract scenes, so its flags and categories are not scored on them.
    content_reliable: bool = True

    def to_json(self) -> dict:
        return {
            "version": VERSION,
            "name": self.name,
            "source": self.source,
            "tasks": self.tasks,
            "groups": [vars(g) for g in self.groups],
            "flags": self.flags,
            "unsure": self.unsure,
            "categories": self.categories,
            "queries": [vars(q) for q in self.queries],
            "notes": self.notes,
            "content_reliable": self.content_reliable,
        }

    def flag_names(self) -> list[str]:
        names = {name for labels in self.flags.values() for name in labels}
        names |= {name for labels in self.unsure.values() for name in labels}
        return sorted(names)


def save(truth: Truth, folder: Path) -> Path:
    path = folder / TRUTH_FILE
    path.write_text(json.dumps(truth.to_json(), indent=1, sort_keys=False), encoding="utf-8")
    return path


def load(folder: Path) -> Truth:
    path = folder / TRUTH_FILE
    if not path.exists():
        raise TruthError(f"{path} not found. A dataset needs a {TRUTH_FILE} beside its photos.")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("version") != VERSION:
        raise TruthError(f"{path}: unsupported version {raw.get('version')!r} (expected {VERSION})")
    truth = Truth(
        name=raw.get("name", folder.name),
        source=raw.get("source", "unknown"),
        tasks=list(raw.get("tasks", [])),
        groups=[Group(**g) for g in raw.get("groups", [])],
        flags={k: list(v) for k, v in raw.get("flags", {}).items()},
        unsure={k: list(v) for k, v in raw.get("unsure", {}).items()},
        categories=dict(raw.get("categories", {})),
        queries=[Query(**q) for q in raw.get("queries", [])],
        notes=dict(raw.get("notes", {})),
        content_reliable=bool(raw.get("content_reliable", True)),
    )
    validate(truth, folder)
    return truth


def validate(truth: Truth, folder: Path) -> None:
    """Fail loudly on a malformed file: a typo here would silently skew every score."""
    unknown = [t for t in truth.tasks if t not in TASKS]
    if unknown:
        raise TruthError(f"unknown task(s) {unknown}; choose from {list(TASKS)}")

    seen: dict[str, str] = {}
    ids: set[str] = set()
    for group in truth.groups:
        if group.id in ids:
            raise TruthError(f"duplicate group id {group.id!r}")
        ids.add(group.id)
        if group.kind not in GROUP_KINDS:
            raise TruthError(f"group {group.id}: kind must be one of {GROUP_KINDS}")
        if len(group.members) < 2:
            raise TruthError(f"group {group.id}: needs at least two members")
        if not set(group.best) <= set(group.members):
            raise TruthError(f"group {group.id}: 'best' must be members of the group")
        for member in group.members:
            if member in seen:
                raise TruthError(f"{member} is in groups {seen[member]} and {group.id}")
            seen[member] = group.id

    referenced = set(seen) | set(truth.flags) | set(truth.unsure) | set(truth.categories)
    referenced |= {p for q in truth.queries for p in q.relevant}
    missing = sorted(p for p in referenced if not (folder / p).is_file())
    if missing:
        raise TruthError(f"{len(missing)} labelled file(s) are missing, e.g. {missing[:3]}")
