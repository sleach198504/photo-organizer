"""How iPhone libraries name things.

* An edited photo is saved beside its original as `IMG_E1234` (the original stays
  `IMG_1234`, often as HEIC while the edit is a JPEG). They are the same moment, but
  the edit can change the picture enough that look-alike matching misses them.
* An edited original also gets a small `IMG_1234.AAE` file holding the edit
  instructions, which belongs with the photo and should travel with it.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

_EDITED = re.compile(r"^IMG_E(\d+)$", re.IGNORECASE)
_ORIGINAL = re.compile(r"^IMG_(\d+)$", re.IGNORECASE)

SIDECAR_EXTENSIONS = (".AAE", ".aae")


def _key(path: Path) -> tuple[str, int, bool] | None:
    """(folder, picture number, is_edited) for an iPhone-style name, else None."""
    edited = _EDITED.match(path.stem)
    original = None if edited else _ORIGINAL.match(path.stem)
    match = edited or original
    if not match:
        return None
    return str(path.parent).lower(), int(match.group(1)), bool(edited)


def is_edit_of(edited_name: str, original_name: str) -> bool:
    """True when `edited_name` (IMG_E1234.JPG) is the edited copy of `original_name` (IMG_1234.HEIC)."""
    a, b = _key(Path(edited_name)), _key(Path(original_name))
    return bool(a and b and a[2] and not b[2] and a[1] == b[1])


def edited_pairs(items: Iterable[tuple[int, Path]]) -> list[tuple[int, int]]:
    """(edited_id, original_id) for every edited copy whose original is in the same folder."""
    originals: dict[tuple[str, int], list[int]] = {}
    edits: list[tuple[int, tuple[str, int]]] = []
    for item_id, path in items:
        key = _key(path)
        if key is None:
            continue
        folder, number, is_edited = key
        if is_edited:
            edits.append((item_id, (folder, number)))
        else:
            originals.setdefault((folder, number), []).append(item_id)
    return [(e, o) for e, key in edits for o in originals.get(key, [])]


def is_edited_name(name: str) -> bool:
    key = _key(Path(name))
    return bool(key and key[2])
