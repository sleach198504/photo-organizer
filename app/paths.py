"""Where things live on disk.

CODE_ROOT is the install folder (holds app/ and the downloaded models/). APP_HOME is
where this user's own state lives - config.yaml, the index database, the thumbnail
cache. They are the same folder by default (so existing installs keep working with
no migration), but PHOTO_ORGANIZER_HOME can point APP_HOME somewhere else, which is
how tests and demos run against a scratch library without touching real data.
"""
from __future__ import annotations

import os
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parent.parent
APP_HOME = Path(os.environ.get("PHOTO_ORGANIZER_HOME") or CODE_ROOT).resolve()

CONFIG_PATH = APP_HOME / "config.yaml"
EXAMPLE_CONFIG_PATH = CODE_ROOT / "config.example.yaml"
DATA_DIR = APP_HOME / "data"
CACHE_DIR = DATA_DIR / "cache"
THUMB_DIR = CACHE_DIR / "thumbs"
MODELS_DIR = CODE_ROOT / "models"
STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"
