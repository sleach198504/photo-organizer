from __future__ import annotations

import sqlite3
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
"""


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
    conn.commit()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


@contextmanager
def session(db_path: Path):
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
