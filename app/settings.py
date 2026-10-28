"""User settings, stored in config.yaml (so a technical user can still hand-edit it).

Validation lives here, once, instead of being scattered across routes: every way of
changing a setting - the Settings page, the first-run screen, starting a scan - goes
through `update_settings`.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .config import (
    PLACEHOLDER_MARKER,
    Config,
    ensure_config_exists,
    set_config_bool,
    set_config_int,
    set_config_value,
)
from .indexer import VIDEO_REVIEW_MODES
from .paths import CONFIG_PATH, EXAMPLE_CONFIG_PATH

REVIEW_SUBFOLDER_NAME = "Image Review"
VIDEO_SEARCH_DEPTHS = {"fast": 10.0, "thorough": 1.0}  # seconds between sampled frames

# Similarity presets shown to people instead of a raw hash distance.
SIMILARITY_PRESETS = {"strict": 4, "balanced": 6, "loose": 9}


class SettingsError(ValueError):
    """A setting was rejected; the message is written for the person using the app."""


def get_config() -> Config:
    ensure_config_exists(CONFIG_PATH, EXAMPLE_CONFIG_PATH)
    return Config.load(CONFIG_PATH)


def _raw() -> dict:
    ensure_config_exists(CONFIG_PATH, EXAMPLE_CONFIG_PATH)
    try:
        return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}


def _path_value(raw: dict, key: str) -> str:
    value = raw.get(key) or ""
    return "" if PLACEHOLDER_MARKER in str(value) else str(value)


def _similarity_name(distance: int) -> str:
    return min(SIMILARITY_PRESETS, key=lambda name: abs(SIMILARITY_PRESETS[name] - distance))


def read_settings() -> dict:
    raw = _raw()
    source = _path_value(raw, "source_dir")
    distance = int(raw.get("near_duplicate_hash_distance", 6))
    return {
        "source_dir": source,
        "quarantine_dir": _path_value(raw, "quarantine_dir"),
        "organize_dest_dir": _path_value(raw, "organize_dest_dir"),
        "auto_remove_exact_duplicates": bool(raw.get("auto_quarantine_exact_duplicates", False)),
        "similarity": _similarity_name(distance),
        "video_review_mode": raw.get("video_review_mode", "medium"),
        "video_search_depth": raw.get("video_search_depth", "fast"),
        "configured": bool(source and Path(source).is_dir()),
    }


def default_review_folder(source_dir: str) -> str:
    """The review folder lives inside the photos folder by default - the scanner
    skips it, and it travels with the photos if the folder is moved."""
    return str(Path(source_dir) / REVIEW_SUBFOLDER_NAME)


def update_settings(patch: dict) -> dict:
    """Validate and persist a partial settings update. Raises SettingsError with a
    message fit to show the person."""
    current = read_settings()

    source = patch.get("source_dir", current["source_dir"])
    quarantine = patch.get("quarantine_dir", current["quarantine_dir"])
    if "source_dir" in patch:
        source = str(source).strip()
        if not source or not Path(source).is_dir():
            raise SettingsError("That photos folder doesn't exist. Choose a folder that's on this computer.")
        if "quarantine_dir" not in patch and not current["quarantine_dir"]:
            quarantine = default_review_folder(source)
    if "quarantine_dir" in patch or "source_dir" in patch:
        quarantine = str(quarantine).strip()
        if quarantine and source:
            src, rev = Path(source).resolve(), Path(quarantine).resolve()
            if rev == src or src.is_relative_to(rev):
                raise SettingsError(
                    "The review folder can't be the same as, or contain, your photos folder."
                )

    if "video_review_mode" in patch and patch["video_review_mode"] not in VIDEO_REVIEW_MODES:
        raise SettingsError("Unknown video review setting.")
    if "video_search_depth" in patch and patch["video_search_depth"] not in VIDEO_SEARCH_DEPTHS:
        raise SettingsError("Unknown video search detail setting.")
    if "similarity" in patch and patch["similarity"] not in SIMILARITY_PRESETS:
        raise SettingsError("Unknown similarity setting.")

    # Validation passed - write everything.
    if "source_dir" in patch:
        set_config_value(CONFIG_PATH, "source_dir", source)
    if "quarantine_dir" in patch or "source_dir" in patch:
        if quarantine:
            try:
                Path(quarantine).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise SettingsError(f"Couldn't create the review folder: {exc}") from exc
            set_config_value(CONFIG_PATH, "quarantine_dir", quarantine)
    if "organize_dest_dir" in patch:
        set_config_value(CONFIG_PATH, "organize_dest_dir", str(patch["organize_dest_dir"]).strip())
    if "auto_remove_exact_duplicates" in patch:
        set_config_bool(CONFIG_PATH, "auto_quarantine_exact_duplicates", bool(patch["auto_remove_exact_duplicates"]))
    if "similarity" in patch:
        set_config_int(CONFIG_PATH, "near_duplicate_hash_distance", SIMILARITY_PRESETS[patch["similarity"]])
    if "video_review_mode" in patch:
        set_config_value(CONFIG_PATH, "video_review_mode", patch["video_review_mode"])
    if "video_search_depth" in patch:
        set_config_value(CONFIG_PATH, "video_search_depth", patch["video_search_depth"])

    return read_settings()
