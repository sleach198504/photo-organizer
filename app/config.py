from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

PLACEHOLDER_MARKER = "YourName"


def _parse_bool(value, default: bool) -> bool:
    """yaml.safe_load already turns an unquoted true/false into a real bool, but be
    defensive about a quoted "false" string too - Python's bool("false") is True,
    which would silently invert the setting."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


@dataclass
class Config:
    source_dir: Path
    quarantine_dir: Path
    db_path: Path
    auto_quarantine_exact_duplicates: bool
    near_duplicate_hash_distance: int

    @classmethod
    def load(cls, path: Path) -> "Config":
        if not path.exists():
            raise FileNotFoundError(
                f"Config file not found: {path}\n"
                "Copy config.example.yaml to config.yaml and edit it first."
            )
        raw = yaml.safe_load(path.read_text()) or {}
        base = path.parent

        db_path_raw = Path(raw.get("db_path", "data/index.db"))
        db_path = db_path_raw if db_path_raw.is_absolute() else (base / db_path_raw)

        return cls(
            source_dir=Path(raw["source_dir"]).expanduser(),
            quarantine_dir=Path(raw["quarantine_dir"]).expanduser(),
            db_path=db_path.resolve(),
            auto_quarantine_exact_duplicates=_parse_bool(raw.get("auto_quarantine_exact_duplicates"), False),
            near_duplicate_hash_distance=int(raw.get("near_duplicate_hash_distance", 6)),
        )


def ensure_config_exists(config_path: Path, example_path: Path) -> None:
    if not config_path.exists():
        config_path.write_text(example_path.read_text(encoding="utf-8"), encoding="utf-8")


def set_config_value(config_path: Path, key: str, value: str) -> None:
    """Rewrite a single top-level key in config.yaml, preserving the rest of the file
    (comments included) so the GUI can update folder paths without clobbering settings
    a technical user may have hand-tuned."""
    text = config_path.read_text(encoding="utf-8")
    normalized = value.replace("\\", "/")
    escaped = normalized.replace('"', '\\"')
    replacement = f'{key}: "{escaped}"'
    pattern = re.compile(rf"^{re.escape(key)}:.*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(replacement, text, count=1)
    else:
        text = text.rstrip("\n") + f"\n{replacement}\n"
    config_path.write_text(text, encoding="utf-8")


def set_config_bool(config_path: Path, key: str, value: bool) -> None:
    """Like set_config_value, but writes an unquoted true/false literal - reusing
    the string writer here would round-trip through Python's bool("false") == True
    footgun the next time the file is loaded."""
    text = config_path.read_text(encoding="utf-8")
    replacement = f"{key}: {'true' if value else 'false'}"
    pattern = re.compile(rf"^{re.escape(key)}:.*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(replacement, text, count=1)
    else:
        text = text.rstrip("\n") + f"\n{replacement}\n"
    config_path.write_text(text, encoding="utf-8")


def read_saved_bool(config_path: Path, key: str, default: bool = False) -> bool:
    if not config_path.exists():
        return default
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return default
    return _parse_bool(raw.get(key), default)


def read_saved_location(config_path: Path, key: str) -> str:
    """Best-effort read of a single path value for pre-filling the GUI. Returns ''
    if the file doesn't exist, the key is missing, or it's still the template placeholder."""
    if not config_path.exists():
        return ""
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return ""
    value = raw.get(key) or ""
    if PLACEHOLDER_MARKER in value:
        return ""
    return value
