"""Turns public benchmark datasets into evaluation datasets (a `truth.json` beside the photos).

The photos are never copied or changed; `truth.json` is written into the folder you
extracted the dataset to, and paths in it are relative to that folder. These datasets
are for private testing only: keep them out of the repository (use `eval_data/`).
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from . import truth as truthmod

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


class ImportError_(ValueError):
    pass


def _images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


# ---------------------------------------------------------------------------
# CERTH Image Blur Dataset (Mavridaki and Mezaris, ICIP 2014)
# ---------------------------------------------------------------------------


def certh_kind(path: Path, root: Path) -> str | None:
    """'sharp', 'natural' (naturally blurred) or 'artificial' (digitally blurred), from the
    folder names above the file, or None if the folder gives no clue."""
    parts = [p.lower() for p in path.relative_to(root).parent.parts]
    text = " ".join(parts)
    if "undistorted" in text or re.search(r"\b(sharp|clear)\b", text):
        return "sharp"
    if "artificial" in text or "digital" in text:
        return "artificial"
    if "natural" in text or "blur" in text:
        return "natural"
    return None


def read_xlsx_labels(path: Path) -> dict[str, int]:
    """name -> number from the first sheet of a simple two-column .xlsx (name, label).
    Read with the standard library so no spreadsheet package is needed."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])) for si in root.findall("m:si", ns)]
        sheet = ElementTree.fromstring(z.read("xl/worksheets/sheet1.xml"))

    def cell_value(cell) -> str | None:
        v = cell.find("m:v", ns)
        if v is None or v.text is None:
            return None
        return shared[int(v.text)] if cell.get("t") == "s" else v.text

    labels: dict[str, int] = {}
    for row in sheet.iter("{%s}row" % ns["m"]):
        cells = {re.match(r"[A-Z]+", c.get("r")).group(): cell_value(c) for c in row.findall("m:c", ns)}
        name, value = cells.get("A"), cells.get("B")
        if name and value is not None:
            try:
                labels[name.strip()] = int(float(value))
            except ValueError:
                continue  # the header row
    return labels


def _label_files(images: list[Path]) -> dict[Path, dict[str, int]]:
    """Folders that have a sibling `<folder name>.xlsx` take their labels from it (the
    CERTH evaluation sets mix sharp and blurred images in one folder)."""
    found: dict[Path, dict[str, int]] = {}
    for folder in {p.parent for p in images}:
        sheet = folder.with_name(folder.name + ".xlsx")
        if sheet.is_file():
            found[folder] = {k.lower(): v for k, v in read_xlsx_labels(sheet).items()}
    return found


def import_certh(folder: Path, include: str = "natural") -> truthmod.Truth:
    """`include` is 'natural' (real photos only, the fair test), 'artificial' or 'all'.
    Images of the other kind are left out of the scores. Training folders are labelled by
    their names; evaluation folders by their spreadsheet (+1 blurred, -1 clear). Anything
    that cannot be classified is listed in the error rather than guessed."""
    if include not in ("natural", "artificial", "all"):
        raise ImportError_("include must be natural, artificial or all")
    images = _images(folder)
    if not images:
        raise ImportError_(f"No images found under {folder}")

    sheets = _label_files(images)
    kinds: dict[Path, str | None] = {}
    for path in images:
        labels = sheets.get(path.parent)
        if labels is None:
            kinds[path] = certh_kind(path, folder)
            continue
        value = labels.get(path.name.lower()) or labels.get(path.stem.lower())
        if value is None:
            kinds[path] = None
        elif value < 0:
            kinds[path] = "sharp"
        else:
            kinds[path] = "artificial" if "digital" in path.parent.name.lower() else "natural"
    unknown = sorted({p.relative_to(folder).parent.as_posix() for p, k in kinds.items() if k is None})
    if unknown:
        raise ImportError_(
            "Could not tell sharp from blurred for images in: " + ", ".join(unknown[:6]) +
            ". Expected folder names containing Undistorted, Naturally-Blurred or Artificially-Blurred, "
            "or a spreadsheet named after the folder.")

    t = truthmod.Truth(name=f"certh-{include}", source="CERTH Image Blur Dataset", tasks=["flags"])
    counts = {"sharp": 0, "natural": 0, "artificial": 0}
    for path, kind in kinds.items():
        rel = path.relative_to(folder).as_posix()
        counts[kind] += 1
        t.notes[rel] = {"sharp": "undistorted", "natural": "naturally blurred", "artificial": "artificially blurred"}[kind]
        wanted = kind == "sharp" or include == "all" or kind == include
        if not wanted:
            t.unsure[rel] = ["blurry"]          # left out of the scores
        elif kind != "sharp":
            t.flags[rel] = ["blurry"]
    if not t.flags:
        raise ImportError_("No blurred images matched; check the folder and the include option.")
    truthmod.save(t, folder)
    truthmod.load(folder)
    t.notes["_counts"] = ", ".join(f"{k}: {v}" for k, v in counts.items())
    return t


# ---------------------------------------------------------------------------
# INRIA Copydays (Douze et al., 2009): originals plus attacked copies
# ---------------------------------------------------------------------------

COPYDAYS_NAME = re.compile(r"^(\d{4})(\d{2})$")


def import_copydays(folder: Path) -> truthmod.Truth:
    """Groups each original with its attacked copies by the first four digits of the file
    name (the last two digits are the variant; 00 is the original). The original is the
    acceptable keeper. Run on the extracted `copydays_original` and `copydays_strong` folders."""
    blocks: dict[str, dict[str, list[str]]] = {}
    for path in _images(folder):
        match = COPYDAYS_NAME.match(path.stem)
        if not match:
            continue
        block, variant = match.groups()
        entry = blocks.setdefault(block, {"original": [], "copies": []})
        entry["original" if variant == "00" else "copies"].append(path.relative_to(folder).as_posix())
    if not blocks:
        raise ImportError_("No Copydays-style files (six digits, like 200400.jpg) found under " + str(folder))

    t = truthmod.Truth(name="copydays", source="INRIA Copydays", tasks=["near_duplicates", "keeper"])
    for n, (block, entry) in enumerate(sorted(blocks.items()), 1):
        if not entry["original"] or not entry["copies"]:
            continue  # a lone original is a distractor: it belongs to no group
        members = sorted(entry["original"] + entry["copies"])
        t.groups.append(truthmod.Group(
            id=f"copy{block}", kind="near", members=members, best=sorted(entry["original"]), tags=["copydays"]))
        for rel in entry["original"]:
            t.notes[rel] = "original"
        for rel in entry["copies"]:
            t.notes[rel] = "attacked copy"
    if not t.groups:
        raise ImportError_("Found originals but no attacked copies. Extract both copydays_original and copydays_strong "
                           "into the same folder.")
    truthmod.save(t, folder)
    truthmod.load(folder)
    return t
