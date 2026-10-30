"""Brings a library over from a copy of the app installed by Setup.ps1.

That copy keeps its settings and photo index inside its own install folder. A packaged build keeps
them in a per-user folder instead, so the first time it runs it copies them across. It only ever
copies: nothing in the earlier install is changed or deleted (SQLite may add its empty -wal/-shm
bookkeeping files beside the database while reading it), and it can be removed from Windows
Settings > Apps whenever the person likes. It happens once; if the person later clears their data it is not
brought back.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

MARKER_NAME = "imported_from_earlier_install.json"


def default_legacy_dir(environ=os.environ) -> Path | None:
    base = environ.get("LOCALAPPDATA")
    return Path(base) / "Programs" / "Photo Organizer" if base else None


def marker_path(home: Path) -> Path:
    return home / "data" / MARKER_NAME


def imported_from(home: Path) -> str | None:
    """The folder a library was brought over from, or None if nothing was."""
    try:
        return json.loads(marker_path(home).read_text(encoding="utf-8")).get("from")
    except (OSError, ValueError):
        return None


def import_earlier_install(home: Path, legacy: Path | None = None) -> dict | None:
    """Copies config.yaml and the photo index from `legacy` into `home`. Returns what was copied,
    or None when there was nothing to do (or nothing that could safely be copied)."""
    legacy = legacy if legacy is not None else default_legacy_dir()
    if legacy is None or not legacy.is_dir() or legacy.resolve() == home.resolve():
        return None
    if marker_path(home).exists() or (home / "config.yaml").exists() or (home / "data" / "index.db").exists():
        return None  # already set up here (or already imported once)

    old_config, old_db = legacy / "config.yaml", legacy / "data" / "index.db"
    if not old_config.is_file() and not old_db.is_file():
        return None

    copied = []
    try:
        (home / "data").mkdir(parents=True, exist_ok=True)
        if old_db.is_file():
            # The backup API reads a consistent snapshot even if the old app is open right now.
            tmp = home / "data" / "index.db.importing"
            tmp.unlink(missing_ok=True)
            source = sqlite3.connect(f"{old_db.resolve().as_uri()}?mode=ro", uri=True)
            target = sqlite3.connect(tmp)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            tmp.replace(home / "data" / "index.db")
            copied.append("photo index")
        if old_config.is_file():
            shutil.copyfile(old_config, home / "config.yaml")
            copied.append("settings")
        marker_path(home).write_text(
            json.dumps({"from": str(legacy), "at": datetime.now(timezone.utc).isoformat(), "copied": copied}),
            encoding="utf-8",
        )
    except (OSError, sqlite3.Error) as exc:
        log.warning("Could not bring over the earlier install's library: %s", exc)
        # Nothing existed here before (checked above), so anything found now is half of a failed import.
        for leftover in (home / "data" / "index.db.importing", home / "data" / "index.db", home / "config.yaml"):
            leftover.unlink(missing_ok=True)
        return None
    log.info("Brought over %s from %s", " and ".join(copied), legacy)
    return {"from": str(legacy), "copied": copied}
