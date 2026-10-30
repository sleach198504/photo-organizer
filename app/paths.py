"""Where things live on disk.

CODE_ROOT is the install folder (holds app/ and the models/). APP_HOME is where this user's
own state lives - config.yaml, the index database, the thumbnail cache, the log.

A packaged build (the Microsoft Store package, or any installer that bundles everything) puts
CODE_ROOT somewhere read-only such as Program Files, and says so with app/package_info.json.
Then APP_HOME is a per-user folder under %LocalAppData%. Everywhere else (a development
checkout, or a copy installed by Setup.ps1) APP_HOME is CODE_ROOT, as it always was, so existing
installs keep working with no migration.

PHOTO_ORGANIZER_HOME overrides all of that, which is how tests and demos run against a scratch
library without touching real data.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

APP_FOLDER_NAME = "Photo Organizer"


def read_package_info(code_root: Path) -> dict:
    """What the build said about itself ({} when this is not a packaged build)."""
    try:
        info = json.loads((code_root / "app" / "package_info.json").read_text(encoding="utf-8"))
        return info if isinstance(info, dict) else {}
    except (OSError, ValueError):
        return {}


def user_data_folder(environ=os.environ) -> Path:
    base = environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / "AppData" / "Local") / APP_FOLDER_NAME


def resolve_home(code_root: Path, package_info: dict, environ=os.environ) -> Path:
    override = environ.get("PHOTO_ORGANIZER_HOME")
    if override:
        return Path(override).resolve()
    if package_info:
        return user_data_folder(environ).resolve()
    return code_root


CODE_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_INFO = read_package_info(CODE_ROOT)
CHANNEL = PACKAGE_INFO.get("channel")  # "store", "installer", or None when not packaged
APP_HOME = resolve_home(CODE_ROOT, PACKAGE_INFO)

CONFIG_PATH = APP_HOME / "config.yaml"
EXAMPLE_CONFIG_PATH = CODE_ROOT / "config.example.yaml"
DATA_DIR = APP_HOME / "data"
CACHE_DIR = DATA_DIR / "cache"
THUMB_DIR = CACHE_DIR / "thumbs"
MODELS_DIR = CODE_ROOT / "models"
STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"
