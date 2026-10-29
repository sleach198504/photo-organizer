from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    live_pair_path TEXT,
    size_bytes INTEGER NOT NULL,
    mtime REAL NOT NULL,
    sha256 TEXT NOT NULL,
    phash TEXT,
    width INTEGER,
    height INTEGER,
    taken_at TEXT,
    camera_model TEXT,
    gps_lat REAL,
    gps_lon REAL,
    blur_score REAL,
    content_tags TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    indexed_at TEXT NOT NULL,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_photos_sha256 ON photos(sha256);
CREATE INDEX IF NOT EXISTS idx_photos_phash ON photos(phash);
CREATE INDEX IF NOT EXISTS idx_photos_status ON photos(status);

CREATE TABLE IF NOT EXISTS dup_groups (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dup_group_members (
    group_id INTEGER NOT NULL REFERENCES dup_groups(id) ON DELETE CASCADE,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    is_keeper INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (group_id, photo_id)
);

CREATE INDEX IF NOT EXISTS idx_dup_members_photo ON dup_group_members(photo_id);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    confidence REAL,
    decision TEXT NOT NULL DEFAULT 'pending',
    decided_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_reco_photo ON recommendations(photo_id);
CREATE INDEX IF NOT EXISTS idx_reco_decision ON recommendations(decision);

CREATE TABLE IF NOT EXISTS trip_candidates (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,              -- 'vacation' or 'day_trip'
    start_date TEXT NOT NULL,        -- YYYY-MM-DD
    end_date TEXT NOT NULL,          -- YYYY-MM-DD
    suggested_name TEXT NOT NULL,
    custom_name TEXT,                -- NULL until the user overrides it
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending' or 'ignored'
    centroid_lat REAL,
    centroid_lon REAL,
    created_at TEXT NOT NULL,
    UNIQUE (kind, start_date, end_date)
);

CREATE TABLE IF NOT EXISTS trip_candidate_members (
    trip_id INTEGER NOT NULL REFERENCES trip_candidates(id) ON DELETE CASCADE,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    PRIMARY KEY (trip_id, photo_id)
);

CREATE INDEX IF NOT EXISTS idx_trip_members_photo ON trip_candidate_members(photo_id);

CREATE TABLE IF NOT EXISTS video_frame_embeddings (
    id INTEGER PRIMARY KEY,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    offset_seconds REAL NOT NULL,
    embedding BLOB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_video_frame_photo ON video_frame_embeddings(photo_id);

-- A decision the person has made but not yet applied. Marking is instant and
-- reversible; nothing moves on disk until "apply" turns 'remove' marks into moves
-- to the review folder. A photo has at most one mark.
CREATE TABLE IF NOT EXISTS marks (
    photo_id INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    mark TEXT NOT NULL CHECK (mark IN ('remove', 'keep')),
    marked_at TEXT NOT NULL
);

-- Plain-language history of what the app did, shown on Home.
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,          -- scan | removed | restored | purged | organized
    title TEXT NOT NULL,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# Bump when the indexer learns to read something it previously missed, so existing
# rows get their metadata refreshed on the next scan without re-hashing every file.
#   2: EXIF capture date read from the Exif sub-IFD (was NULL for every photo);
#      video creation time and GPS read from the MP4/MOV header.
CURRENT_META_VERSION = 2


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns to already-existing databases that predate them. SQLite has no
    'ADD COLUMN IF NOT EXISTS', so check pragma table_info first."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(photos)")}
    if "has_person" not in columns:
        # NULL = not yet run through content tagging; 0/1 = classified no/yes.
        conn.execute("ALTER TABLE photos ADD COLUMN has_person INTEGER")
    if "media_type" not in columns:
        # Existing rows all predate video support, so they're unambiguously photos.
        conn.execute("ALTER TABLE photos ADD COLUMN media_type TEXT NOT NULL DEFAULT 'photo'")
    if "duration_seconds" not in columns:
        conn.execute("ALTER TABLE photos ADD COLUMN duration_seconds REAL")
    if "is_screen_recording" not in columns:
        # NULL = not yet evaluated (or not a video); 0/1 = heuristic result.
        conn.execute("ALTER TABLE photos ADD COLUMN is_screen_recording INTEGER")
    if "clip_embedding" not in columns:
        # NULL until a content-tagging/embedding pass has run for this photo.
        conn.execute("ALTER TABLE photos ADD COLUMN clip_embedding BLOB")
    if "original_path" not in columns:
        # Where a removed photo lived before it was moved to the review folder, so
        # "restore" can put it back exactly where it came from.
        conn.execute("ALTER TABLE photos ADD COLUMN original_path TEXT")
    if "quarantined_at" not in columns:
        conn.execute("ALTER TABLE photos ADD COLUMN quarantined_at TEXT")
    if "detail_score" not in columns:
        # How much real structure a photo has (see quality.compute_sharpness). NULL also
        # marks rows scored by the older whole-image method, which are scored again.
        conn.execute("ALTER TABLE photos ADD COLUMN detail_score REAL")
    if "meta_version" not in columns:
        conn.execute("ALTER TABLE photos ADD COLUMN meta_version INTEGER NOT NULL DEFAULT 0")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_photos_media ON photos(media_type, status)")
    conn.commit()


_initialized: set[str] = set()
_init_lock = threading.Lock()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    is_memory = str(db_path) == ":memory:"
    if not is_memory:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: a request's connection is created by a dependency and
    # used by the endpoint, which FastAPI may run on different worker threads. Each
    # connection still only serves one request at a time, so this is safe.
    conn = sqlite3.connect(":memory:" if is_memory else str(db_path), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")

    key = ":memory:" if is_memory else str(db_path.resolve())
    # Schema + migrations only need to run once per process per database; doing it
    # on every request would add avoidable latency to every grid scroll.
    if is_memory or key not in _initialized:
        with _init_lock:
            if is_memory or key not in _initialized:
                if not is_memory:
                    # WAL lets the UI keep reading while a scan is writing.
                    conn.execute("PRAGMA journal_mode = WAL")
                    conn.execute("PRAGMA synchronous = NORMAL")
                conn.executescript(SCHEMA)
                _migrate(conn)
                if not is_memory:
                    _initialized.add(key)
    return conn


@contextmanager
def session(db_path: Path):
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def log_activity(conn: sqlite3.Connection, kind: str, title: str, detail: str | None = None) -> None:
    from datetime import datetime, timezone

    conn.execute(
        "INSERT INTO activity (ts, kind, title, detail) VALUES (?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), kind, title, detail),
    )
