from __future__ import annotations

import io
import json
import logging
import mimetypes
import os
import threading
import time
from datetime import datetime
from html import escape
from pathlib import Path

import pillow_heif
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from PIL import Image, ImageOps

from .. import content_tagging, video_frames
from ..actions import (
    decide,
    execute_approved_recommendations,
    get_quarantine_stats,
    purge_quarantined,
    quarantine_photos_batch,
)
from ..config import Config, ensure_config_exists, read_saved_location, set_config_bool, set_config_value
from ..db import session
from ..dedupe import run_dedupe
from ..indexer import VIDEO_REVIEW_MODES, flag_screen_recordings, flag_videos_for_review, run_index
from ..organize import get_folder_preview, run_organize
from ..quality import flag_blurry_photos, run_quality_scoring
from ..review import (
    bucket_items,
    get_no_person_months,
    get_no_person_photos_for_month,
    get_pending_duplicate_groups,
    get_pending_review_items,
    get_video_sessions,
)
from ..search import search_library
from ..trips import AWAY_DISTANCE_MILES, get_trip_candidates, ignore_trip, run_trip_detection, set_trip_name

pillow_heif.register_heif_opener()

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "config.yaml"
EXAMPLE_PATH = ROOT / "config.example.yaml"
REVIEW_SUBFOLDER_NAME = "Image Review"
SERVER_PORT = 8765
HEALTH_SENTINEL = "photo-organizer-review-server"

THUMB_MAX_DIMENSION = 480
FULL_MAX_DIMENSION = 1600

SECTION_TITLES = {
    "exact_duplicate": "Exact Duplicates",
    "near_duplicate": "Similar / Burst Photos",
    "video_near_duplicate": "Similar Videos",
    "blurry": "Blurry Photos",
    "screen_recording": "Possible Screen Recordings",
    "video": "Videos",
    "food": "Food",
    "screenshot": "Screenshots",
    "document": "Documents / Receipts",
    "meme": "Memes / Social Media Images",
    "whiteboard": "Whiteboards / Notes",
    "blank": "Blank / Accidental Shots",
}
REASON_LABELS = {
    "exact_duplicate": "Exact duplicate",
    "near_duplicate": "Similar to another photo",
    "video_near_duplicate": "Similar to another video",
    "blurry": "Blurry",
    "screen_recording": "Possible screen recording",
    "video": "Video",
    "food": "Food",
    "screenshot": "Screenshot",
    "document": "Document/Receipt",
    "meme": "Meme/Social media",
    "whiteboard": "Whiteboard/Notes",
    "blank": "Blank/Accidental",
}
REVIEW_SECTION_ORDER = (
    "exact_duplicate", "near_duplicate", "video_near_duplicate", "blurry",
    "screen_recording", "video",
    "food", "screenshot", "document", "meme", "whiteboard", "blank",
)

PAGE_STYLE = """
:root {
  --ink: #2a2622;
  --ink-soft: #6b6259;
  --paper: #f6f3ee;
  --surface: #fffdf9;
  --line: #e4ddd1;
  --accent: #2f6e71;
  --accent-soft: #e4eeed;
  --accent-ink: #1d4547;
  --flag: #c4633f;
  --flag-soft: #f6e5dd;
  --keep: #6b8f71;
  --keep-soft: #e9f0e7;
  --danger: #9c3b2e;
  --shadow: 0 1px 2px rgba(42,38,34,0.06), 0 4px 14px rgba(42,38,34,0.07);
}
* { box-sizing: border-box; }
body { font-family: 'Segoe UI', Arial, sans-serif; background: var(--paper); color: var(--ink); margin: 0; padding: 24px; line-height: 1.5; }
h1 { margin-bottom: 4px; font-size: 26px; font-weight: 700; letter-spacing: -0.01em; }
.intro { color: var(--ink-soft); max-width: 700px; margin: 0 auto 24px; font-size: 14px; }
h2 { margin-top: 40px; font-size: 18px; font-weight: 600; border-bottom: 1px solid var(--line); padding-bottom: 8px; }
details.section { margin-top: 40px; }
details.section summary { display: flex; align-items: center; gap: 8px; font-size: 18px; font-weight: 600;
  border-bottom: 1px solid var(--line); padding-bottom: 10px; cursor: pointer; list-style: none; user-select: none; }
details.section summary::-webkit-details-marker { display: none; }
details.section summary::before { content: '▸'; display: inline-block; width: 14px; color: var(--ink-soft);
  transition: color 0.12s ease; }
details.section[open] summary::before { content: '▾'; }
details.section summary:hover::before, details.section summary:hover .section-label { color: var(--accent); }
.section-label { transition: color 0.12s ease; }
.count-pill { font-size: 12px; font-weight: 700; background: var(--accent-soft); color: var(--accent-ink);
  border-radius: 999px; padding: 2px 10px; margin-left: auto; font-variant-numeric: tabular-nums; }
.empty { color: var(--ink-soft); font-style: italic; font-size: 14px; }
.all-caught-up { text-align: center; padding: 48px 20px; background: var(--accent-soft); border-radius: 12px;
  max-width: 460px; margin: 24px 0; }
.all-caught-up .check { width: 44px; height: 44px; border-radius: 50%; background: var(--accent); color: var(--surface);
  display: flex; align-items: center; justify-content: center; margin: 0 auto 14px; font-size: 22px; }
.all-caught-up .headline { font-weight: 700; font-size: 17px; margin-bottom: 6px; }
.all-caught-up .sub { font-size: 13.5px; color: var(--ink-soft); }
.bulk-form { margin: 10px 0 20px; }
.cards { display: flex; flex-wrap: wrap; gap: 16px; }
.card { background: var(--surface); border-radius: 10px; box-shadow: var(--shadow); padding: 14px; width: 300px; }
.card-wide { width: 520px; }
.compare { display: flex; gap: 12px; margin-bottom: 8px; }
.compare figure { margin: 0; flex: 1; text-align: center; }
.compare img, .compare video { max-width: 100%; max-height: 260px; border-radius: 6px; object-fit: contain; background: var(--line); }
.compare figcaption { font-size: 12px; color: var(--ink-soft); margin-top: 4px; }
.single img, .single video { max-width: 100%; max-height: 220px; border-radius: 6px; display: block; margin: 0 auto 8px; background: var(--line); }
.dup-group-card { width: 100%; max-width: 760px; }
.dup-group-grid { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 12px; }
.dup-member { width: 150px; background: var(--paper); border-radius: 8px; padding: 8px; border: 1.5px solid transparent; }
.dup-member-keeper { border-color: var(--keep); }
.dup-member img, .dup-member video { width: 100%; height: 130px; object-fit: cover; border-radius: 5px; background: var(--line); display: block; }
.dup-member-check { display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--ink-soft); margin-bottom: 6px; cursor: pointer; }
.dup-member-check input { cursor: pointer; accent-color: var(--flag); }
.dup-keeper-note { font-size: 11px; font-weight: 700; color: var(--keep); margin-top: 6px; }
.video-thumb-wrap { position: relative; display: block; }
.video-expand-btn { position: absolute; top: 6px; right: 6px; width: 26px; height: 26px; border-radius: 6px;
  background: rgba(20,18,15,0.55); color: white; border: none; display: flex; align-items: center;
  justify-content: center; cursor: pointer; padding: 0; transition: background 0.12s ease; }
.video-expand-btn:hover { background: rgba(20,18,15,0.8); }
.clickable { cursor: zoom-in; }
.badges { margin-bottom: 10px; display: flex; flex-wrap: wrap; gap: 6px; }
.badge { display: inline-block; font-size: 11px; font-weight: 600; letter-spacing: 0.01em; background: var(--accent-soft);
  color: var(--accent-ink); border-radius: 5px; padding: 3px 8px; }
.filename { font-size: 12.5px; color: var(--ink-soft); word-break: break-all; margin-bottom: 8px; font-variant-numeric: tabular-nums; }
.actions { display: flex; gap: 8px; }
.actions button { flex: 1; padding: 9px; border-radius: 7px; cursor: pointer; font-size: 13px; font-weight: 600;
  font-family: inherit; transition: filter 0.12s ease, background 0.12s ease; }
.btn-approve { background: var(--flag); color: white; border: 1.5px solid var(--flag); }
.btn-approve:hover { filter: brightness(1.06); }
.btn-reject { background: transparent; color: var(--keep); border: 1.5px solid var(--keep); }
.btn-reject:hover { background: var(--keep-soft); }
.btn-bulk { background: var(--flag); color: white; padding: 9px 16px; border: none; border-radius: 7px;
  cursor: pointer; font-weight: 600; font-family: inherit; }
.btn-bulk:hover { filter: brightness(1.06); }
.top-bar { display: flex; justify-content: space-between; align-items: center; max-width: 700px; margin: 0 auto; }
.quit-link { color: var(--ink-soft); font-size: 12px; text-decoration: none; }
.quit-link:hover { color: var(--flag); }
.back-link { display: inline-block; margin: 10px 0 20px; padding: 7px 16px; border: 1.5px solid var(--accent);
  border-radius: 20px; background: transparent; color: var(--accent); text-decoration: none; font-size: 14px;
  font-weight: 600; transition: background 0.12s ease, color 0.12s ease; }
.back-link:hover { background: var(--accent); color: var(--surface); }
.month-nav { display: flex; align-items: center; gap: 10px; margin: 16px 0; }
.month-nav select { padding: 6px 10px; border: 1px solid var(--line); border-radius: 4px; font-size: 14px;
  background: var(--surface); color: var(--ink); }
.month-nav button { padding: 6px 12px; border: 1px solid var(--line); border-radius: 4px; background: var(--surface);
  color: var(--ink); cursor: pointer; }
.month-nav button:disabled { color: var(--line); cursor: default; }
.batch-bar { display: flex; align-items: center; gap: 10px; margin: 10px 0 16px; padding: 10px 14px;
  background: var(--surface); border-radius: 8px; box-shadow: var(--shadow); }
.batch-bar button { padding: 8px 14px; border: 1px solid var(--line); border-radius: 6px; background: var(--paper);
  color: var(--ink); cursor: pointer; font-family: inherit; }
.batch-bar .btn-move-selected { background: var(--flag); color: white; border-color: var(--flag); font-weight: 600; }
.batch-bar .btn-move-selected:hover { filter: brightness(1.06); }
.batch-bar .spacer { flex: 1; }
.thumb-grid { display: flex; flex-wrap: wrap; gap: 10px; }
.thumb-item { position: relative; width: 150px; }
.thumb-item img, .thumb-item video { width: 150px; height: 150px; object-fit: cover; border-radius: 7px; cursor: zoom-in;
  background: var(--line); display: block; border: 3px solid transparent; }
.thumb-item.selected img, .thumb-item.selected video { border-color: var(--flag); }
.thumb-item input[type=checkbox] { position: absolute; top: 6px; left: 6px; width: 20px; height: 20px; cursor: pointer; }
.folder-row { display: flex; align-items: center; gap: 8px; margin: 0 auto 10px; max-width: 700px; }
.folder-row label { width: 180px; flex-shrink: 0; font-size: 14px; }
.folder-row input[type=text] { flex: 1; padding: 6px; border: 1px solid var(--line); border-radius: 4px;
  background: var(--surface); color: var(--ink); }
.folder-row button { padding: 6px 12px; border: 1px solid var(--line); border-radius: 4px; background: var(--surface);
  color: var(--ink); cursor: pointer; }
.checkbox-row { max-width: 700px; margin: 4px auto 10px; font-size: 13px; color: var(--ink-soft); }
.checkbox-row label { display: flex; align-items: flex-start; gap: 8px; cursor: pointer; }
.checkbox-row input { margin-top: 2px; flex-shrink: 0; cursor: pointer; }

.setup-card { background: var(--surface); border-radius: 14px; box-shadow: var(--shadow); padding: 28px;
  max-width: 700px; margin: 0 auto 20px; }
.card-divider { height: 1px; background: var(--line); margin: 22px 0; }
.field-group { margin-bottom: 18px; }
.field-group:last-child { margin-bottom: 0; }
.field-label { display: block; font-size: 12px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
  color: var(--ink-soft); margin-bottom: 7px; }
.field-hint { color: var(--ink-soft); font-size: 12.5px; margin: 8px 2px 0; }
.path-field { display: flex; align-items: center; gap: 8px; background: var(--paper); border: 1.5px solid var(--line);
  border-radius: 10px; padding: 3px 3px 3px 12px; transition: border-color 0.12s ease; }
.path-field:focus-within { border-color: var(--accent); }
.path-icon { flex-shrink: 0; color: var(--ink-soft); display: flex; }
.path-field input[type=text] { flex: 1; min-width: 0; border: none; background: transparent; padding: 9px 4px;
  font-size: 13.5px; color: var(--ink); font-family: Consolas, monospace; }
.path-field input[type=text]:focus { outline: none; }
.path-browse { flex-shrink: 0; padding: 9px 16px; border: none; border-radius: 8px; background: var(--accent-soft);
  color: var(--accent-ink); font-weight: 600; font-size: 13px; cursor: pointer; font-family: inherit;
  transition: background 0.12s ease, color 0.12s ease; }
.path-browse:hover { background: var(--accent); color: white; }

.toggle-row { display: flex; align-items: flex-start; gap: 10px; cursor: pointer; font-size: 13.5px;
  color: var(--ink-soft); line-height: 1.45; }
.toggle-row input { margin-top: 3px; flex-shrink: 0; cursor: pointer; width: 16px; height: 16px; accent-color: var(--accent); }

.select-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.select-field { appearance: none; -webkit-appearance: none; width: 100%; padding: 10px 34px 10px 12px;
  font-size: 13.5px; border: 1.5px solid var(--line); border-radius: 8px; background-color: var(--paper);
  color: var(--ink); cursor: pointer; font-family: inherit;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12'%3E%3Cpath d='M2.5 4.5L6 8L9.5 4.5' stroke='%236b6259' stroke-width='1.4' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat; background-position: right 12px center; background-size: 11px;
  transition: border-color 0.12s ease; }
.select-field:hover, .select-field:focus { border-color: var(--accent); outline: none; }

.warning-banner { margin-top: 10px; padding: 10px 14px; background: var(--flag-soft); color: var(--danger);
  border-radius: 8px; font-size: 12.5px; border-left: 3px solid var(--danger); }

.progress-card { display: none; max-width: 700px; background: var(--surface); border-radius: 14px;
  box-shadow: var(--shadow); margin: 18px auto 0; overflow: hidden; }
.progress-card-header { padding: 12px 18px; display: flex; align-items: center; gap: 10px; font-size: 12px;
  font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--ink-soft);
  border-bottom: 1px solid var(--line); }
.progress-card-header .pulse-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--keep);
  flex-shrink: 0; animation: pulse-dot 1.4s ease-in-out infinite; }
@keyframes pulse-dot { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
.big-button { display: block; width: 100%; max-width: 700px; padding: 12px; margin: 14px auto 0; border: 1.5px solid var(--accent);
  border-radius: 8px; background: var(--accent); color: white; font-size: 15px; font-weight: 600; cursor: pointer;
  font-family: inherit; transition: filter 0.12s ease, background 0.12s ease, color 0.12s ease; }
.big-button:hover { filter: brightness(1.06); }
.big-button:disabled { background: var(--line); border-color: var(--line); color: var(--ink-soft); cursor: default; filter: none; }
.review-button { background: transparent; color: var(--accent); }
.review-button:hover { background: var(--accent-soft); filter: none; }
.btn-danger { background: var(--danger); border-color: var(--danger); }
.btn-danger:hover { filter: brightness(1.1); }
.log-area { background: var(--surface); color: var(--ink-soft); font-family: Consolas, monospace;
  font-size: 12.5px; padding: 14px 18px; height: 210px; overflow-y: auto; white-space: pre-wrap; line-height: 1.6; }

.toast-container { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); z-index: 200;
  display: flex; flex-direction: column; gap: 8px; align-items: center; pointer-events: none; }
.toast { background: var(--ink); color: var(--paper); border-radius: 9px; padding: 12px 18px; font-size: 13.5px;
  box-shadow: var(--shadow); display: flex; align-items: center; gap: 10px; opacity: 0; transform: translateY(8px);
  transition: opacity 0.2s ease, transform 0.2s ease; }
.toast.toast-visible { opacity: 1; transform: translateY(0); }
.toast-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--keep); flex-shrink: 0; }

.viewer-modal { display: none; position: fixed; inset: 0; background: rgba(20,18,15,0.85); z-index: 100;
  align-items: center; justify-content: center; }
.viewer-content { background: #201d19; border-radius: 10px; padding: 16px; width: 92vw; height: 88vh;
  display: flex; flex-direction: column; }
.viewer-toolbar { display: flex; gap: 8px; margin-bottom: 12px; }
.viewer-toolbar button { padding: 8px 14px; border: 1px solid #4a443c; border-radius: 6px; background: #332f29;
  color: #eee; cursor: pointer; font-size: 13px; font-family: inherit; }
.viewer-toolbar button.active { background: var(--accent); border-color: var(--accent); }
.viewer-toolbar .spacer { flex: 1; }
.viewer-toolbar .close-btn { background: var(--danger); border-color: var(--danger); }
.viewer-pane { flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; }
.viewer-pane img { max-width: 100%; max-height: 100%; object-fit: contain; }
.viewer-media-wrap { display: flex; flex-direction: column; align-items: center; justify-content: center;
  width: 100%; height: 100%; min-height: 0; min-width: 0; }
.viewer-media-wrap > img, .viewer-media-wrap > video { flex: 1; min-height: 0; max-width: 100%; object-fit: contain; }
.viewer-filename { flex-shrink: 0; color: #ccc; font-size: 13px; margin-top: 10px; text-align: center;
  word-break: break-all; max-width: 100%; }
#viewer-sbs { gap: 12px; }
.viewer-sbs-item { flex: 1; height: 100%; display: flex; flex-direction: column; align-items: center;
  justify-content: center; min-width: 0; }
.viewer-sbs-item img { flex: 1; min-height: 0; }
.viewer-sbs-caption { color: #ccc; font-size: 12px; margin-top: 6px; text-align: center; }
.viewer-sbs-caption .viewer-filename-inline { display: block; color: #999; margin-top: 2px; word-break: break-all; }
.slider-container { position: relative; overflow: hidden; user-select: none; flex-shrink: 0; }
.slider-container img { display: block; width: 100%; height: 100%; object-fit: contain; }
.slider-fg { position: absolute; top: 0; left: 0; clip-path: inset(0 50% 0 0); }
.slider-handle { position: absolute; top: 0; bottom: 0; left: 50%; width: 3px; margin-left: -1.5px;
  background: white; cursor: ew-resize; box-shadow: 0 0 6px rgba(0,0,0,0.6); }
.slider-handle::after { content: '\\2194'; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
  background: white; color: #333; width: 26px; height: 26px; border-radius: 50%; display: flex;
  align-items: center; justify-content: center; font-size: 14px; }
.review-folder-box { background: var(--surface); border-radius: 10px; box-shadow: var(--shadow);
  padding: 16px 20px; max-width: 700px; margin: 24px auto 0; }
.review-folder-box h2 { margin: 0 0 10px; border-bottom: none; padding-bottom: 0; font-size: 17px; }
.organize-hint { color: var(--ink-soft); font-size: 13px; max-width: 700px; margin: 24px auto 4px; }

.folder-tree, .folder-tree-children { list-style: none; margin: 0; padding: 0; max-height: 260px; overflow-y: auto; }
.folder-tree-children { padding-left: 22px; max-height: none; overflow: visible; }
.folder-tree li { margin: 2px 0; }
.folder-tree-row { display: flex; align-items: center; gap: 8px; cursor: pointer; padding: 3px 4px;
  border-radius: 6px; font-size: 13.5px; }
.folder-tree-row:hover { background: var(--paper); }
.folder-tree-row input[type=checkbox] { flex-shrink: 0; cursor: pointer; width: 15px; height: 15px;
  accent-color: var(--accent); }
.folder-tree-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.folder-tree-count { color: var(--ink-soft); font-size: 12px; flex-shrink: 0; font-variant-numeric: tabular-nums; }
.exclude-mode-row { border-top: 1px solid var(--line); margin-top: 14px; padding-top: 12px; }
"""

FOLDER_ICON_SVG = (
    '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M1.5 3.5C1.5 2.94772 1.94772 2.5 2.5 2.5H6L7.5 4H13.5C14.0523 4 14.5 4.44772 14.5 5V12.5'
    'C14.5 13.0523 14.0523 13.5 13.5 13.5H2.5C1.94772 13.5 1.5 13.0523 1.5 12.5V3.5Z" '
    'stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>'
)

# Diagonal-arrows "expand" icon for the video-thumbnail overlay button. Kept
# separate from the video's own onclick (native <video controls> already owns
# clicks for play/pause/seek) so opening the larger view is its own,
# unambiguous target rather than fighting with normal playback.
EXPAND_ICON_SVG = (
    '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M6.5 2H2V6.5M9.5 14H14V9.5M2 10V14H6.5M14 6.5V2H9.5" '
    'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


def _video_thumb_html(photo_id: int, offset_seconds: float | None = None, style: str = "") -> str:
    """A <video> thumbnail with its own native inline controls plus a small
    overlay button that opens the larger video viewer - used everywhere a
    video appears (single flagged videos, duplicate groups, video sessions,
    search results, trips), so preview and "view larger" both work the same
    way, everywhere, instead of some places having full controls, others
    nothing, and nowhere having a larger view at all."""
    offset_attr = f' onloadedmetadata="this.currentTime={offset_seconds}"' if offset_seconds else ""
    offset_arg = offset_seconds if offset_seconds else 0
    style_attr = f' style="{style}"' if style else ""
    return f"""<div class="video-thumb-wrap"{style_attr}>
      <video controls preload="none" poster="/thumb/{photo_id}" src="/videofile/{photo_id}"{offset_attr}></video>
      <button type="button" class="video-expand-btn" title="Open larger view"
        onclick="event.stopPropagation(); openVideoViewer({photo_id}, {offset_arg})">{EXPAND_ICON_SVG}</button>
    </div>"""


class ScanState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.running = False
        self.done = False
        self.error: str | None = None
        self.log: list[str] = []

    def start(self) -> None:
        with self._lock:
            self.running = True
            self.done = False
            self.error = None
            self.log = []

    def append(self, line: str) -> None:
        with self._lock:
            self.log.append(line)

    def finish(self, error: str | None) -> None:
        with self._lock:
            self.running = False
            self.done = True
            self.error = error

    def snapshot(self) -> dict:
        with self._lock:
            return {"running": self.running, "done": self.done, "error": self.error, "log": list(self.log)}


class ScanStateLogHandler(logging.Handler):
    def __init__(self, state: ScanState) -> None:
        super().__init__()
        self.state = state

    def emit(self, record: logging.LogRecord) -> None:
        self.state.append(self.format(record))


def _get_config() -> Config:
    ensure_config_exists(CONFIG_PATH, EXAMPLE_PATH)
    return Config.load(CONFIG_PATH)


_clip_backend_cache: dict[str, content_tagging.ClipBackend] = {}


def _get_clip_backend() -> content_tagging.ClipBackend:
    """Loading the model takes a few seconds - cached per-process so repeated
    searches in the same session don't pay that cost every time."""
    if "backend" not in _clip_backend_cache:
        _clip_backend_cache["backend"] = content_tagging.ClipBackend()
    return _clip_backend_cache["backend"]


def _run_pipeline(source: Path, quarantine: Path, scan_state: ScanState) -> None:
    try:
        scan_state.append(f"Photos folder: {source}")
        scan_state.append(f"Review folder: {quarantine}")
        scan_state.append("")

        config = _get_config()  # reload: reflects the source/quarantine just written to disk
        with session(config.db_path) as conn:
            index_stats = run_index(conn, source, exclude_dir=quarantine)
            scan_state.append(
                f"Scanned {index_stats['scanned']}, indexed/updated {index_stats['indexed']}, "
                f"unchanged {index_stats['skipped']}, had trouble reading {index_stats['errors']}."
            )

            video_review_mode = read_saved_location(CONFIG_PATH, "video_review_mode") or "medium"
            video_flagged = flag_videos_for_review(conn, video_review_mode)
            screen_rec_flagged = flag_screen_recordings(conn)
            if video_flagged or screen_rec_flagged:
                scan_state.append(
                    f"Flagged {video_flagged} video(s) for review and "
                    f"{screen_rec_flagged} possible screen recording(s)."
                )

            scan_state.append("Checking photos for blurriness...")
            quality_stats = run_quality_scoring(conn)
            blurry_count = flag_blurry_photos(conn)
            scan_state.append(f"Scored {quality_stats['scored']} photos, flagged {blurry_count} as blurry.")

            scan_state.append("Looking for duplicate and similar photos...")
            dedupe_stats = run_dedupe(
                conn, config.near_duplicate_hash_distance, config.auto_quarantine_exact_duplicates
            )
            scan_state.append(
                f"Found {dedupe_stats['exact_groups']} exact-duplicate group(s), "
                f"{dedupe_stats['near_groups']} group(s) of similar/burst photos, and "
                f"{dedupe_stats['video_near_groups']} group(s) of similar videos."
            )

            if content_tagging.models_downloaded():
                scan_state.append("Checking photo content (food/screenshots/documents/etc - this is the slow part)...")
                backend = content_tagging.ClipBackend()
                tag_stats = content_tagging.run_content_tagging(conn, backend)
                scan_state.append(
                    f"Checked {tag_stats['tagged']} photos, flagged {tag_stats['flagged']} "
                    f"({tag_stats['errors']} could not be checked)."
                )

                video_search_depth = read_saved_location(CONFIG_PATH, "video_search_depth") or "fast"
                interval_seconds = VIDEO_SEARCH_DEPTH_SECONDS.get(video_search_depth, 10.0)
                scan_state.append(f"Indexing video content for search ({video_search_depth})...")
                video_embed_stats = content_tagging.run_video_frame_embedding(conn, backend, interval_seconds)
                scan_state.append(
                    f"Indexed {video_embed_stats['videos']} video(s) "
                    f"({video_embed_stats['frames']} frame(s) total) for search."
                )
            else:
                scan_state.append(
                    "Skipping content tagging - models not downloaded yet. Run Setup.bat again to enable it."
                )

            auto_moved = execute_approved_recommendations(conn, config)
            if auto_moved:
                scan_state.append(f"Auto-moved {auto_moved} exact duplicate(s) to the review folder.")

        scan_state.append("")
        scan_state.append("All done!")
        scan_state.finish(None)
    except Exception as exc:  # noqa: BLE001 - shown to a non-technical user, must not crash silently
        logging.getLogger(__name__).exception("Pipeline failed")
        scan_state.finish(str(exc))


def _run_organize_job(
    dest_root: Path, excluded_folders: set[str], exclude_mode: str, organize_state: ScanState
) -> None:
    try:
        organize_state.append(f"Organizing into: {dest_root}")
        if excluded_folders:
            how = "left in place" if exclude_mode == "skip" else "moved as-is"
            organize_state.append(f"Excluding {len(excluded_folders)} folder(s) ({how}): " + ", ".join(sorted(excluded_folders)))
        organize_state.append("")
        config = _get_config()
        with session(config.db_path) as conn:
            stats = run_organize(conn, dest_root, config.source_dir, excluded_folders, exclude_mode)
        organize_state.append(f"Moved {stats['moved']} photo(s) into year/month folders.")
        if stats.get("skipped"):
            organize_state.append(f"Left {stats['skipped']} photo(s) untouched in excluded folders.")
        if stats["errors"]:
            organize_state.append(f"{stats['errors']} photo(s) could not be moved - see details in the log.")
        organize_state.append("")
        organize_state.append("All done!")
        organize_state.finish(None)
    except Exception as exc:  # noqa: BLE001 - shown to a non-technical user, must not crash silently
        logging.getLogger(__name__).exception("Organize failed")
        organize_state.finish(str(exc))


def _resized_jpeg_bytes(path: Path, max_dimension: int, quality: int) -> bytes:
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        if max(img.size) > max_dimension:
            scale = max_dimension / max(img.size)
            new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            img = img.resize(new_size)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()


def _video_frame_jpeg_bytes(path: Path, max_dimension: int, quality: int) -> bytes:
    cap = video_frames.open_capture(path)
    try:
        img = video_frames.grab_middle_frame(cap)
    finally:
        cap.release()
    if img is None:
        raise RuntimeError("could not read a frame from this video")
    img = img.convert("RGB")
    if max(img.size) > max_dimension:
        scale = max_dimension / max(img.size)
        new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
        img = img.resize(new_size)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _thumbnail_bytes(path: Path, media_type: str = "photo") -> bytes:
    if media_type == "video":
        return _video_frame_jpeg_bytes(path, THUMB_MAX_DIMENSION, quality=85)
    return _resized_jpeg_bytes(path, THUMB_MAX_DIMENSION, quality=85)


def _full_bytes(path: Path, media_type: str = "photo") -> bytes:
    if media_type == "video":
        return _video_frame_jpeg_bytes(path, FULL_MAX_DIMENSION, quality=90)
    return _resized_jpeg_bytes(path, FULL_MAX_DIMENSION, quality=90)


def _format_duration(seconds) -> str:
    if not seconds:
        return ""
    total = int(round(seconds))
    m, s = divmod(total, 60)
    return f"{m}:{s:02d}"


def _photo_card(item: dict) -> str:
    photo = item["photo"]
    photo_id = photo["id"]
    is_video = photo["media_type"] == "video"
    filename = escape(Path(photo["path"]).name)
    badges = "".join(
        f'<span class="badge">{escape(REASON_LABELS.get(r, r))}</span>' for r in item["reasons"]
    )
    duration_line = (
        f"<div class='filename'>Length: {_format_duration(photo['duration_seconds'])}</div>"
        if is_video and photo["duration_seconds"]
        else ""
    )

    # Every item _photo_card renders is a single, standalone flag (blurry,
    # screen recording, a flagged video, a content-tag category) - the
    # exact/near/video-near-duplicate groups that used to attach a "keeper"
    # here for a two-way compare now render as their own grouped card
    # instead (see _duplicate_group_card), so there's nothing left to
    # compare against in this function.
    if is_video:
        media = f'<div class="single">{_video_thumb_html(photo_id)}</div>'
    else:
        media = f"""<div class="single"><img src="/thumb/{photo_id}" alt="photo" class="clickable"
          onclick="openViewer({photo_id}, null, null)"></div>"""

    return f"""
    <div class="card">
      {media}
      <div class="badges">{badges}</div>
      <div class="filename">{filename}</div>
      {duration_line}
      <form class="actions" method="post" action="/decide/{photo_id}" onsubmit="markNavigating()">
        <button class="btn-approve" name="decision" value="approved">Move to Review Folder</button>
        <button class="btn-reject" name="decision" value="rejected">Keep This Photo</button>
      </form>
    </div>
    """


def _duplicate_group_card(group: dict) -> str:
    """One card per dup_group, every member (keeper included) individually
    checkable - unlike _photo_card's fixed keeper-vs-one-candidate layout, this
    lets a burst of any size be resolved as "keep none/some/all of these" in one
    action, since the members that actually compete with each other are the whole
    group, not just each one against the keeper."""
    members = group["members"]
    is_video = members[0]["photo"]["media_type"] == "video"

    thumbs = []
    for m in members:
        photo = m["photo"]
        pid = photo["id"]
        filename = escape(Path(photo["path"]).name)
        checked = "" if m["is_keeper"] else "checked"
        keeper_note = '<div class="dup-keeper-note">Suggested keep</div>' if m["is_keeper"] else ""
        if is_video:
            media = _video_thumb_html(pid)
        else:
            media = f'<img src="/thumb/{pid}" class="clickable" onclick="openViewer({pid}, null, null)">'
        member_class = "dup-member dup-member-keeper" if m["is_keeper"] else "dup-member"
        thumbs.append(f"""
        <div class="{member_class}">
          <label class="dup-member-check">
            <input type="checkbox" class="dup-checkbox" value="{pid}" {checked}>
            <span>Move to review</span>
          </label>
          {media}
          {keeper_note}
          <div class="filename">{filename}</div>
        </div>
        """)

    return f"""
    <div class="card card-wide dup-group-card">
      <div class="dup-group-grid">{"".join(thumbs)}</div>
      <form class="actions" method="post" action="/decide-group" onsubmit="submitDupGroup(this); markNavigating()">
        <input type="hidden" name="discard_ids" class="dup-discard-ids">
        <input type="hidden" name="keep_ids" class="dup-keep-ids">
        <button class="btn-approve" type="submit">Apply</button>
      </form>
    </div>
    """


def _section(key: str, items: list[dict], groups: list[dict] | None = None) -> str:
    title = SECTION_TITLES[key]
    count = len(groups) if groups is not None else len(items)
    if count == 0:
        return f"""<details class="section" open>
          <summary><span class="section-label">{title}</span><span class="count-pill">0</span></summary>
          <p class='empty'>Nothing flagged here right now.</p>
        </details>"""

    bulk = ""
    if key == "exact_duplicate" and items:
        ids = ",".join(str(item["photo"]["id"]) for item in items)
        bulk = f"""
        <form class="bulk-form" method="post" action="/decide-bulk" onsubmit="markNavigating()">
          <input type="hidden" name="photo_ids" value="{ids}">
          <input type="hidden" name="decision" value="approved">
          <button class="btn-bulk" type="submit">Move All {len(items)} Exact Duplicates to Review Folder</button>
        </form>
        """

    if groups is not None:
        cards = "".join(_duplicate_group_card(g) for g in groups)
    else:
        cards = "".join(_photo_card(item) for item in items)

    return f"""<details class="section" open>
      <summary><span class="section-label">{title}</span><span class="count-pill">{count}</span></summary>
      {bulk}<div class='cards'>{cards}</div>
    </details>"""


def _top_bar(title: str) -> str:
    return f"""
    <div class="top-bar">
      <h1>{title}</h1>
      <a class="quit-link" href="#" onclick="quitApp(); return false;">Quit Photo Organizer</a>
    </div>
    """


QUIT_SCRIPT = """
window.__navigatingAway = false;

function showToast(message) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = '<span class="toast-dot"></span>' + message;
  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('toast-visible'));
  setTimeout(() => {
    toast.classList.remove('toast-visible');
    setTimeout(() => toast.remove(), 250);
  }, 2600);
}

async function quitApp() {
  if (!confirm('Quit Photo Organizer? Any scan in progress will be stopped.')) return;
  window.__navigatingAway = true;
  try { await fetch('/shutdown', {method: 'POST'}); } catch (e) {}
  document.body.innerHTML = '<h2>Photo Organizer has closed.</h2><p>You can close this tab now.</p>';
}

function goTo(url) {
  window.__navigatingAway = true;
  window.location.href = url;
}

function markNavigating() {
  window.__navigatingAway = true;
}

// Closing the window fires the same event as navigating to another page within
// this app, so every internal link/button/form marks __navigatingAway first (via
// goTo()/markNavigating() above) - if it's still false here, this really is the
// window closing, so tell the server to shut down. sendBeacon (not fetch) is used
// because it's guaranteed to actually go out even as the page is torn down.
window.addEventListener('pagehide', function () {
  if (!window.__navigatingAway) {
    navigator.sendBeacon('/shutdown');
  }
});
"""


VIEWER_HTML = """
<div id="viewer-modal" class="viewer-modal" onclick="if(event.target===this) closeViewer()">
  <div class="viewer-content">
    <div class="viewer-toolbar">
      <button id="viewer-btn-single" onclick="setViewerMode('single')">Single</button>
      <button id="viewer-btn-sbs" onclick="setViewerMode('sbs')">Side by Side</button>
      <button id="viewer-btn-slider" onclick="setViewerMode('slider')">Slider</button>
      <div class="spacer"></div>
      <button class="close-btn" onclick="closeViewer()">Close</button>
    </div>
    <div id="viewer-single" class="viewer-pane">
      <div class="viewer-media-wrap">
        <img id="viewer-single-img">
        <div id="viewer-single-name" class="viewer-filename"></div>
      </div>
    </div>
    <div id="viewer-sbs" class="viewer-pane" style="display:none;">
      <div class="viewer-sbs-item"><img id="viewer-sbs-keeper">
        <div class="viewer-sbs-caption">Suggested to keep
          <span id="viewer-sbs-keeper-name" class="viewer-filename-inline"></span></div></div>
      <div class="viewer-sbs-item"><img id="viewer-sbs-candidate">
        <div class="viewer-sbs-caption">Suggested to remove
          <span id="viewer-sbs-candidate-name" class="viewer-filename-inline"></span></div></div>
    </div>
    <div id="viewer-slider" class="viewer-pane" style="display:none;">
      <div class="viewer-media-wrap">
        <div id="viewer-slider-box" class="slider-container">
          <img id="viewer-slider-bg" onload="fitSliderBox()">
          <img id="viewer-slider-fg" class="slider-fg">
          <div id="viewer-slider-handle" class="slider-handle"></div>
        </div>
        <div id="viewer-slider-name" class="viewer-filename"></div>
      </div>
    </div>
  </div>
</div>
"""

VIEWER_SCRIPT = """
let viewerSingleId = null;
let viewerKeeperId = null;
let viewerCandidateId = null;
let sliderDragging = false;

function photoName(id) {
  return (typeof PHOTO_NAMES !== 'undefined' && PHOTO_NAMES[id]) || '';
}

function openViewer(singleId, keeperId, candidateId) {
  viewerSingleId = singleId;
  viewerKeeperId = keeperId;
  viewerCandidateId = candidateId;
  const hasCompare = !!(keeperId && candidateId);
  document.getElementById('viewer-btn-sbs').style.display = hasCompare ? 'inline-block' : 'none';
  document.getElementById('viewer-btn-slider').style.display = hasCompare ? 'inline-block' : 'none';
  setViewerMode('single');
  document.getElementById('viewer-modal').style.display = 'flex';
}

function closeViewer() {
  document.getElementById('viewer-modal').style.display = 'none';
}

function setViewerMode(mode) {
  document.getElementById('viewer-single').style.display = mode === 'single' ? 'flex' : 'none';
  document.getElementById('viewer-sbs').style.display = mode === 'sbs' ? 'flex' : 'none';
  document.getElementById('viewer-slider').style.display = mode === 'slider' ? 'flex' : 'none';
  ['single', 'sbs', 'slider'].forEach(function (m) {
    document.getElementById('viewer-btn-' + m).classList.toggle('active', m === mode);
  });

  if (mode === 'single') {
    document.getElementById('viewer-single-img').src = '/full/' + viewerSingleId;
    document.getElementById('viewer-single-name').textContent = photoName(viewerSingleId);
  } else if (mode === 'sbs') {
    document.getElementById('viewer-sbs-keeper').src = '/full/' + viewerKeeperId;
    document.getElementById('viewer-sbs-candidate').src = '/full/' + viewerCandidateId;
    document.getElementById('viewer-sbs-keeper-name').textContent = photoName(viewerKeeperId);
    document.getElementById('viewer-sbs-candidate-name').textContent = photoName(viewerCandidateId);
  } else if (mode === 'slider') {
    document.getElementById('viewer-slider-bg').src = '/full/' + viewerKeeperId;
    document.getElementById('viewer-slider-fg').src = '/full/' + viewerCandidateId;
    document.getElementById('viewer-slider-name').textContent =
      photoName(viewerCandidateId) + '  (compared to ' + photoName(viewerKeeperId) + ')';
    setSliderPct(50);
  }
}

// The slider box is sized in JS (not plain CSS) to exactly match the photo's
// rendered dimensions, not the full modal width - otherwise on a photo narrower
// than the modal, dragging past the actual image edge would still move the
// handle through "dead" letterboxed space with nothing to compare there.
function fitSliderBox() {
  const pane = document.getElementById('viewer-slider');
  const box = document.getElementById('viewer-slider-box');
  const bg = document.getElementById('viewer-slider-bg');
  if (!bg.naturalWidth || !bg.naturalHeight) return;
  const availW = pane.clientWidth;
  const availH = pane.clientHeight - 30; // leave room for the filename caption below
  const scale = Math.min(availW / bg.naturalWidth, availH / bg.naturalHeight);
  box.style.width = Math.round(bg.naturalWidth * scale) + 'px';
  box.style.height = Math.round(bg.naturalHeight * scale) + 'px';
}

function setSliderPct(pct) {
  pct = Math.max(0, Math.min(100, pct));
  document.getElementById('viewer-slider-fg').style.clipPath = 'inset(0 ' + (100 - pct) + '% 0 0)';
  document.getElementById('viewer-slider-handle').style.left = pct + '%';
}

function sliderMove(e) {
  const box = document.getElementById('viewer-slider-box');
  const rect = box.getBoundingClientRect();
  const clientX = e.touches ? e.touches[0].clientX : e.clientX;
  setSliderPct(((clientX - rect.left) / rect.width) * 100);
}

document.addEventListener('DOMContentLoaded', function () {
  const box = document.getElementById('viewer-slider-box');
  if (!box) return;
  box.addEventListener('mousedown', function (e) { sliderDragging = true; sliderMove(e); });
  box.addEventListener('touchstart', function (e) { sliderDragging = true; sliderMove(e); });
  window.addEventListener('mousemove', function (e) { if (sliderDragging) sliderMove(e); });
  window.addEventListener('touchmove', function (e) { if (sliderDragging) sliderMove(e); });
  window.addEventListener('mouseup', function () { sliderDragging = false; });
  window.addEventListener('touchend', function () { sliderDragging = false; });
  window.addEventListener('resize', function () { if (document.getElementById('viewer-slider').style.display !== 'none') fitSliderBox(); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeViewer();
  });
});
"""

# Deliberately a separate modal from VIEWER_HTML/VIEWER_SCRIPT above, rather
# than teaching openViewer() to also handle video - a video only ever needs a
# single enlarged player (its own inline thumbnail already lets you compare
# it against siblings in a group), so there's no Side-by-Side/Slider mode to
# wire up, and keeping it separate avoids complicating the already-nuanced
# photo compare-mode logic with an unrelated media type.
VIDEO_VIEWER_HTML = """
<div id="video-viewer-modal" class="viewer-modal" onclick="if(event.target===this) closeVideoViewer()">
  <div class="viewer-content">
    <div class="viewer-toolbar">
      <div class="spacer"></div>
      <button class="close-btn" onclick="closeVideoViewer()">Close</button>
    </div>
    <div class="viewer-pane">
      <div class="viewer-media-wrap">
        <video id="video-viewer-player" controls autoplay></video>
        <div id="video-viewer-name" class="viewer-filename"></div>
      </div>
    </div>
  </div>
</div>
"""

VIDEO_VIEWER_SCRIPT = """
function openVideoViewer(id, offsetSeconds) {
  const player = document.getElementById('video-viewer-player');
  player.src = '/videofile/' + id;
  if (offsetSeconds) {
    player.addEventListener('loadedmetadata', function once() {
      player.currentTime = offsetSeconds;
      player.removeEventListener('loadedmetadata', once);
    });
  }
  // Self-contained rather than reusing VIEWER_SCRIPT's photoName() - this
  // modal also needs to work on pages (like Video Sessions) that never
  // include the photo viewer at all.
  const nameEl = document.getElementById('video-viewer-name');
  if (nameEl) nameEl.textContent = (typeof PHOTO_NAMES !== 'undefined' && PHOTO_NAMES[id]) || '';
  document.getElementById('video-viewer-modal').style.display = 'flex';
}

function closeVideoViewer() {
  const player = document.getElementById('video-viewer-player');
  player.pause();
  player.removeAttribute('src');
  player.load();
  document.getElementById('video-viewer-modal').style.display = 'none';
}

document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') closeVideoViewer();
});
"""


DUP_GROUP_SCRIPT = """
function submitDupGroup(form) {
  const card = form.closest('.dup-group-card');
  const discard = [];
  const keep = [];
  card.querySelectorAll('.dup-checkbox').forEach(function (cb) {
    (cb.checked ? discard : keep).push(cb.value);
  });
  form.querySelector('.dup-discard-ids').value = discard.join(',');
  form.querySelector('.dup-keep-ids').value = keep.join(',');
}
"""


def _format_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _render_purge_box(stats: dict) -> str:
    count = stats["count"]
    size_str = _format_bytes(stats["total_bytes"])
    if count == 0:
        body = "<p class='empty'>Nothing in the review folder right now.</p>"
    else:
        body = f"""
        <p>{count} photo(s) waiting there, using about {size_str}.</p>
        <button class="big-button btn-danger" style="max-width:420px;"
                onclick="purgeReviewFolder({count}, '{escape(size_str)}')">
          Permanently Delete These {count} Photos
        </button>
        """
    return f"""
    <div class="review-folder-box">
      <h2>Review Folder</h2>
      {body}
    </div>
    """


PURGE_SCRIPT = """
async function purgeReviewFolder(count, sizeStr) {
  if (!confirm('Permanently delete ' + count + ' photo(s) (' + sizeStr + ') from the review folder?\\n\\n' +
               'This CANNOT be undone - there is no going back after this.')) return;
  const resp = await fetch('/purge', {method: 'POST'});
  const data = await resp.json();
  let msg = 'Deleted ' + data.deleted + ' photo(s).';
  if (data.errors) msg += ' ' + data.errors + ' could not be deleted (see log).';
  showToast(msg);
  markNavigating();
  setTimeout(() => window.location.reload(), 1400);
}
"""


def _photo_names_json(items: list[dict]) -> str:
    names: dict[int, str] = {}
    for item in items:
        names[item["photo"]["id"]] = Path(item["photo"]["path"]).name
        if item["keeper"]:
            names[item["keeper"]["id"]] = Path(item["keeper"]["path"]).name
    return json.dumps(names)


def _render_review_page(items: list[dict], quarantine_stats: dict, duplicate_groups: dict) -> str:
    buckets = bucket_items(items)
    total = len(items)
    if total == 0:
        # Nothing flagged at all - one reassuring state beats several empty
        # sections stacked on top of each other.
        sections = """
        <div class="all-caught-up">
          <div class="check">&#10003;</div>
          <div class="headline">Nothing needs review</div>
          <div class="sub">New flags will show up here after your next scan.</div>
        </div>
        """
    else:
        # The three original sections always show (even empty); the six content-tag
        # categories only show up once they have something, so a mostly-empty content
        # scan doesn't turn the page into six empty sections in a row.
        always_shown = ("exact_duplicate", "near_duplicate", "blurry")
        section_keys = [k for k in REVIEW_SECTION_ORDER if k in always_shown or buckets[k]]
        sections = "".join(
            _section(key, buckets[key], duplicate_groups.get(key)) if key in duplicate_groups
            else _section(key, buckets[key])
            for key in section_keys
        )
    photo_names_json = _photo_names_json(items)

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Photo Organizer - Review</title>
<style>{PAGE_STYLE}</style>
</head>
<body>
  {_top_bar("Photo Organizer - Review")}
  <p class="intro">
    {total} photo(s) flagged for review. "Move to Review Folder" moves a photo out of
    your photos folder into the review folder - it is NOT deleted, and you can move it
    back yourself anytime. "Keep This Photo" dismisses the suggestion and leaves it alone.
    Click any photo to view it larger.
  </p>
  <a class="back-link" href="/" onclick="markNavigating()">&laquo; Back to Scan</a>
  {sections}
  {_render_purge_box(quarantine_stats)}
  <p class="organize-hint">Looking for something specific? Search your photos by what's in them.</p>
  <button class="big-button review-button" onclick="goTo('/search')">Search Photos</button>
  <p class="organize-hint">Want to browse instead of relying on automatic flags? See everything without a person in it, month by month.</p>
  <button class="big-button review-button" onclick="goTo('/no-person')">Browse Photos Without a Person</button>
  <p class="organize-hint">Videos grouped by when they were recorded, so a batch from the same event can be reviewed together.</p>
  <button class="big-button review-button" onclick="goTo('/video-sessions')">Browse Videos by Session</button>
  <p class="organize-hint">Done reviewing? Move everything that's left into dated folders for long-term storage.</p>
  <button class="big-button review-button" onclick="goTo('/organize')">Organize Remaining Photos</button>
  {VIEWER_HTML}
  {VIDEO_VIEWER_HTML}
  <script>
    const PHOTO_NAMES = {photo_names_json};
    {QUIT_SCRIPT}{PURGE_SCRIPT}{VIEWER_SCRIPT}{VIDEO_VIEWER_SCRIPT}{DUP_GROUP_SCRIPT}
  </script>
</body>
</html>"""


VIDEO_REVIEW_MODE_LABELS = {
    "off": "Don't flag videos",
    "all": "All videos",
    "medium": "Medium length or longer (1 min+)",
    "long": "Long only (5 min+)",
}

VIDEO_SEARCH_DEPTH_SECONDS = {"fast": 10.0, "thorough": 1.0}
VIDEO_SEARCH_DEPTH_LABELS = {
    "fast": "Fast (check every 10 seconds of video)",
    "thorough": "Thorough (check every 1 second - much slower on this PC's CPU)",
}


def _render_home_page(
    source_dir: str,
    quarantine_dir: str,
    pending_count: int,
    auto_quarantine: bool,
    video_review_mode: str,
    video_search_depth: str,
    gpu_mode: bool,
) -> str:
    review_display = "block" if pending_count else "none"
    video_mode_options = "".join(
        f'<option value="{key}" {"selected" if key == video_review_mode else ""}>{escape(label)}</option>'
        for key, label in VIDEO_REVIEW_MODE_LABELS.items()
    )
    video_depth_options = "".join(
        f'<option value="{key}" {"selected" if key == video_search_depth else ""}>{escape(label)}</option>'
        for key, label in VIDEO_SEARCH_DEPTH_LABELS.items()
    )
    thorough_warning_display = "block" if video_search_depth == "thorough" else "none"
    gpu_badge = (
        '<span class="badge" style="background:var(--keep-soft);color:var(--keep);">Running in GPU mode</span>'
        if gpu_mode
        else '<span class="badge">Running in CPU mode</span>'
    )
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Photo Organizer</title>
<style>{PAGE_STYLE}</style>
</head>
<body>
  {_top_bar("Photo Organizer")}
  <p style="margin:-8px 0 16px;">{gpu_badge}</p>
  <p class="intro">
    Choose the folder with your photos, and a folder where flagged photos will be
    moved for you to look over. This scans for duplicate, similar, and blurry photos -
    nothing is ever deleted automatically, you always get to review first.
  </p>

  <div class="setup-card">
    <div class="field-group">
      <label class="field-label" for="source_dir">Photos folder</label>
      <div class="path-field">
        <span class="path-icon">{FOLDER_ICON_SVG}</span>
        <input type="text" id="source_dir" value="{escape(source_dir)}">
        <button class="path-browse" onclick="pickFolder('source')">Browse&hellip;</button>
      </div>
    </div>
    <div class="field-group">
      <label class="field-label" for="quarantine_dir">Review folder</label>
      <div class="path-field">
        <span class="path-icon">{FOLDER_ICON_SVG}</span>
        <input type="text" id="quarantine_dir" value="{escape(quarantine_dir)}">
        <button class="path-browse" onclick="pickFolder('quarantine')">Browse&hellip;</button>
      </div>
      <p class="field-hint">
        An "{REVIEW_SUBFOLDER_NAME}" folder is created inside whatever you pick for the review folder.
      </p>
    </div>

    <div class="card-divider"></div>

    <div class="field-group">
      <label class="toggle-row">
        <input type="checkbox" id="auto_quarantine" {"checked" if auto_quarantine else ""}>
        <span>Automatically move byte-identical duplicate copies to the review folder
        <em>(skips manual review just for exact duplicates - everything else still waits for you)</em></span>
      </label>
    </div>

    <div class="select-grid">
      <div class="field-group">
        <label class="field-label" for="video_review_mode">Flag videos for review</label>
        <select class="select-field" id="video_review_mode">{video_mode_options}</select>
      </div>
      <div class="field-group">
        <label class="field-label" for="video_search_depth">Video search detail</label>
        <select class="select-field" id="video_search_depth" onchange="toggleThoroughWarning()">{video_depth_options}</select>
      </div>
    </div>
    <p id="thorough-warning" class="warning-banner" style="display:{thorough_warning_display};">
      Thorough checks every second of every video for search - this can take much
      longer on this PC's CPU than the Fast setting.
    </p>

    <button id="start-btn" class="big-button" style="margin-top:22px;" onclick="startScan()">Start Scanning</button>
  </div>

  <div id="log-card" class="progress-card">
    <div class="progress-card-header"><span class="pulse-dot" id="pulse-dot"></span>Scan Progress</div>
    <div id="log-area" class="log-area"></div>
  </div>

  <button id="review-btn" class="big-button review-button" style="display:{review_display}"
          onclick="goTo('/review')">Review Flagged Photos</button>

  <button class="big-button review-button" onclick="goTo('/organize')">Organize Remaining Photos</button>

  <script>
    async function pickFolder(field) {{
      const resp = await fetch('/pick-folder', {{method: 'POST', body: new URLSearchParams({{field}})}});
      const data = await resp.json();
      if (!data.path) return;
      if (field === 'source') {{
        document.getElementById('source_dir').value = data.path;
        const q = document.getElementById('quarantine_dir');
        if (!q.value) q.value = data.path + '/{REVIEW_SUBFOLDER_NAME}';
      }} else {{
        document.getElementById('quarantine_dir').value = data.path;
      }}
    }}

    function toggleThoroughWarning() {{
      const sel = document.getElementById('video_search_depth').value;
      document.getElementById('thorough-warning').style.display = sel === 'thorough' ? 'block' : 'none';
    }}

    async function startScan() {{
      const source_dir = document.getElementById('source_dir').value;
      const quarantine_dir = document.getElementById('quarantine_dir').value;
      const auto_quarantine = document.getElementById('auto_quarantine').checked ? 'true' : 'false';
      const video_review_mode = document.getElementById('video_review_mode').value;
      const video_search_depth = document.getElementById('video_search_depth').value;
      const btn = document.getElementById('start-btn');
      const logArea = document.getElementById('log-area');
      btn.disabled = true;
      btn.textContent = 'Working...';
      document.getElementById('log-card').style.display = 'block';
      document.getElementById('pulse-dot').style.display = 'block';
      logArea.textContent = '';

      const resp = await fetch('/start-scan', {{method: 'POST', body: new URLSearchParams({{source_dir, quarantine_dir, auto_quarantine, video_review_mode, video_search_depth}})}});
      const data = await resp.json();
      if (!resp.ok) {{
        alert(data.error || 'Something went wrong.');
        btn.disabled = false;
        btn.textContent = 'Start Scanning';
        return;
      }}
      pollStatus();
    }}

    function pollStatus() {{
      const interval = setInterval(async () => {{
        const resp = await fetch('/scan-status');
        const status = await resp.json();
        const logArea = document.getElementById('log-area');
        logArea.textContent = status.log.join('\\n');
        logArea.scrollTop = logArea.scrollHeight;
        if (!status.running) {{
          clearInterval(interval);
          const btn = document.getElementById('start-btn');
          btn.disabled = false;
          btn.textContent = 'Start Scanning';
          document.getElementById('pulse-dot').style.display = 'none';
          if (status.error) {{
            alert('Something went wrong: ' + status.error);
          }} else {{
            document.getElementById('review-btn').style.display = 'block';
          }}
        }}
      }}, 1000);
    }}

    {QUIT_SCRIPT}
  </script>
</body>
</html>"""


def _build_folder_tree(folder_preview: list[dict]) -> dict:
    """Turns the flat [{folder: 'Trips/2024', count: n}, ...] list into a nested
    tree keyed by path segment, so the Organize page can render real folder
    nesting with cascading checkboxes instead of one flat list. A node's own
    "label" is only set when that exact path is itself one of folder_preview's
    entries (i.e. photos sit directly in it) - a pure grouping segment (e.g.
    "Trips" when only "Trips/2024" has photos) has children but label=None,
    since unchecking it has nothing of its own to exclude, only descendants."""

    def new_node(name: str) -> dict:
        return {"name": name, "children": {}, "own_count": 0, "total": 0, "label": None}

    root = new_node("")
    for item in folder_preview:
        label = item["folder"]
        count = item["count"]
        parts = [label]  # "(top-level folder)" and named folders are both single segments here...
        if label != "(top-level folder)":
            parts = label.split("/")  # ...unless it's a nested path, then split on it
        node = root
        node["total"] += count
        for part in parts:
            node = node["children"].setdefault(part, new_node(part))
            node["total"] += count
        node["own_count"] = count
        node["label"] = label
    return root


def _render_folder_tree_children(node: dict) -> str:
    if not node["children"]:
        return ""
    items = sorted(node["children"].values(), key=lambda n: -n["total"])
    rows = []
    for child in items:
        label_attr = f' data-label="{escape(child["label"])}"' if child["label"] is not None else ""
        children_html = _render_folder_tree_children(child)
        nested = f'<ul class="folder-tree-children">{children_html}</ul>' if children_html else ""
        rows.append(f"""<li>
          <label class="folder-tree-row">
            <input type="checkbox" class="folder-tree-checkbox" checked{label_attr} onchange="onFolderTreeChange(this)">
            <span class="folder-tree-name">{escape(child['name'])}</span>
            <span class="folder-tree-count">{child['total']} photo(s)</span>
          </label>
          {nested}
        </li>""")
    return "".join(rows)


def _render_organize_folder_preview(folder_preview: list[dict]) -> str:
    if not folder_preview:
        return ""
    tree = _build_folder_tree(folder_preview)
    tree_html = _render_folder_tree_children(tree)
    return f"""
    <div class="review-folder-box">
      <h2>Where Your Photos Are Right Now</h2>
      <p style="color:var(--ink-soft);font-size:13px;margin-top:0;">
        Organizing moves every checked folder below out of here and into Year/Month
        folders instead (or a Trip folder, if detected). Uncheck a folder to leave
        it out of this run - unchecking a folder also unchecks everything inside it.
      </p>
      <ul id="folder-tree-root" class="folder-tree">{tree_html}</ul>
      <div class="exclude-mode-row" id="exclude-mode-row" style="display:none;">
        <p class="field-label" style="margin:14px 0 8px;">For folders you've unchecked</p>
        <label class="toggle-row" style="margin-bottom:6px;">
          <input type="radio" name="exclude_mode" value="skip" checked>
          <span>Leave them exactly where they are - skip entirely this run</span>
        </label>
        <label class="toggle-row">
          <input type="radio" name="exclude_mode" value="move_as_is">
          <span>Move them as-is into the destination, keeping their current folder name/structure</span>
        </label>
      </div>
    </div>
    """


def _render_organize_page(
    active_count: int, dest_dir: str, default_head_folder: str, folder_preview: list[dict]
) -> str:
    folder_count = len(folder_preview)
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Photo Organizer - Organize</title>
<style>{PAGE_STYLE}</style>
</head>
<body>
  {_top_bar("Photo Organizer - Organize")}
  <a class="back-link" href="/review" onclick="markNavigating()">&laquo; Back to Review</a>
  <p class="intro">
    {active_count} photo(s) remain after review. This moves them into dated folders
    (Year/Month, based on when each was taken - or the file's modified date if that's
    not available) inside a folder you choose below, ready for long-term storage. This
    MOVES your photos out of the photos folder; nothing is deleted. Photos that are
    part of a detected vacation or day trip go into their own named folder instead
    of the plain Year/Month bucket.
  </p>

  <div class="folder-row">
    <label>Organize into:</label>
    <input type="text" id="organize_dest" value="{escape(dest_dir)}">
    <button onclick="pickOrganizeFolder()">Browse...</button>
  </div>
  <div class="folder-row">
    <label>Folder name:</label>
    <input type="text" id="organize_head" value="{escape(default_head_folder)}">
  </div>
  <p style="max-width:700px;margin:0 auto;color:var(--ink-soft);font-size:12px;">
    Photos will end up in "&lt;organize into&gt;/&lt;folder name&gt;/&lt;year&gt;/&lt;month&gt;/"
    (or .../Trips/&lt;name&gt;/ and .../Day Trips/&lt;name&gt;/ for detected trips).
    Change the folder name above if you'd rather use something more memorable than today's date.
  </p>

  {_render_organize_folder_preview(folder_preview)}

  <button class="big-button review-button" onclick="goTo('/trips')">Detect Vacations &amp; Day Trips</button>

  <button id="organize-btn" class="big-button" onclick="startOrganize({folder_count})">Organize {active_count} Photos</button>
  <div id="organize-log-area" class="log-area"></div>

  <script>
    async function pickOrganizeFolder() {{
      const resp = await fetch('/pick-folder', {{method: 'POST', body: new URLSearchParams({{field: 'organize_dest'}})}});
      const data = await resp.json();
      if (data.path) document.getElementById('organize_dest').value = data.path;
    }}

    function onFolderTreeChange(el) {{
      const li = el.closest('li');
      li.querySelectorAll('input[type=checkbox]').forEach(function (cb) {{
        cb.checked = el.checked;
        cb.indeterminate = false;
      }});
      const root = document.getElementById('folder-tree-root');
      Array.from(root.children).forEach(recomputeFolderNode);
      updateExcludeModeVisibility();
    }}

    function recomputeFolderNode(li) {{
      const childUl = li.querySelector(':scope > ul.folder-tree-children');
      if (!childUl) return;
      Array.from(childUl.children).forEach(recomputeFolderNode);

      const ownCb = li.querySelector(':scope > label.folder-tree-row > input[type=checkbox]');
      const childCbs = Array.from(childUl.children).map(
        function (cli) {{ return cli.querySelector(':scope > label.folder-tree-row > input[type=checkbox]'); }}
      );
      const allChecked = childCbs.every(function (cb) {{ return cb.checked && !cb.indeterminate; }});
      const noneChecked = childCbs.every(function (cb) {{ return !cb.checked && !cb.indeterminate; }});

      if (ownCb.hasAttribute('data-label')) {{
        // This folder has photos of its own, separate from its subfolders - its
        // own checked state is independent (only the user or a direct click
        // changes it), children just control whether it LOOKS indeterminate.
        ownCb.indeterminate = !((allChecked && ownCb.checked) || (noneChecked && !ownCb.checked));
      }} else if (allChecked) {{
        ownCb.checked = true; ownCb.indeterminate = false;
      }} else if (noneChecked) {{
        ownCb.checked = false; ownCb.indeterminate = false;
      }} else {{
        ownCb.checked = true; ownCb.indeterminate = true;
      }}
    }}

    function updateExcludeModeVisibility() {{
      const anyUnchecked = Array.from(document.querySelectorAll('#folder-tree-root input[data-label]'))
        .some(function (cb) {{ return !cb.checked; }});
      const row = document.getElementById('exclude-mode-row');
      if (row) row.style.display = anyUnchecked ? 'block' : 'none';
    }}

    function collectExcludedFolders() {{
      return Array.from(document.querySelectorAll('#folder-tree-root input[data-label]'))
        .filter(function (cb) {{ return !cb.checked; }})
        .map(function (cb) {{ return cb.dataset.label; }});
    }}

    async function startOrganize(folderCount) {{
      const dest_dir = document.getElementById('organize_dest').value;
      const head_folder = document.getElementById('organize_head').value;
      const excluded = collectExcludedFolders();
      const excludeModeEl = document.querySelector('input[name=exclude_mode]:checked');
      const exclude_mode = excludeModeEl ? excludeModeEl.value : 'skip';
      const includedCount = folderCount - excluded.length;

      let msg = 'Move {active_count} photo(s) into dated folders under \\'' + dest_dir + '/' + head_folder + '\\'?';
      if (excluded.length > 0) {{
        const how = exclude_mode === 'skip'
          ? 'left exactly where they are'
          : 'moved as-is (keeping their current folder name) into the destination';
        msg = 'This will organize photos from ' + includedCount + ' of ' + folderCount + ' existing folder(s) ' +
          'into dated Year/Month folders under \\'' + dest_dir + '/' + head_folder + '\\'.\\n\\n' +
          excluded.length + ' folder(s) you unchecked will be ' + how + ':\\n' + excluded.join('\\n') + '\\n\\n' +
          'Continue?';
      }} else if (folderCount > 0) {{
        msg = 'This will move {active_count} photo(s) out of ' + folderCount + ' existing folder(s) ' +
          '(shown above) into dated Year/Month folders under \\'' + dest_dir + '/' + head_folder + '\\'.\\n\\n' +
          'Those existing folder names will no longer be used. Continue?';
      }}
      if (!confirm(msg)) return;

      const btn = document.getElementById('organize-btn');
      const logArea = document.getElementById('organize-log-area');
      btn.disabled = true;
      btn.textContent = 'Working...';
      logArea.style.display = 'block';
      logArea.textContent = '';

      const resp = await fetch('/start-organize', {{method: 'POST', body: new URLSearchParams({{
        dest_dir, head_folder, excluded_folders: excluded.join('\\u0001'), exclude_mode
      }})}});
      const data = await resp.json();
      if (!resp.ok) {{
        alert(data.error || 'Something went wrong.');
        btn.disabled = false;
        btn.textContent = 'Organize {active_count} Photos';
        return;
      }}
      pollOrganizeStatus();
    }}

    function pollOrganizeStatus() {{
      const interval = setInterval(async () => {{
        const resp = await fetch('/organize-status');
        const status = await resp.json();
        const logArea = document.getElementById('organize-log-area');
        logArea.textContent = status.log.join('\\n');
        logArea.scrollTop = logArea.scrollHeight;
        if (!status.running) {{
          clearInterval(interval);
          const btn = document.getElementById('organize-btn');
          btn.disabled = false;
          btn.textContent = 'Organize {active_count} Photos';
          if (status.error) alert('Something went wrong: ' + status.error);
        }}
      }}, 1000);
    }}

    {QUIT_SCRIPT}
  </script>
</body>
</html>"""


def _format_year_month(year_month: str) -> str:
    try:
        dt = datetime.strptime(year_month, "%Y-%m")
        return dt.strftime("%B %Y")
    except ValueError:
        return year_month


NO_PERSON_SCRIPT = """
function updateSelectedCount() {
  const n = document.querySelectorAll('.thumb-item input[type=checkbox]:checked').length;
  document.getElementById('selected-count').textContent = n + ' selected';
}

function toggleThumb(cb) {
  cb.closest('.thumb-item').classList.toggle('selected', cb.checked);
  updateSelectedCount();
}

function selectAllThumbs() {
  document.querySelectorAll('.thumb-item input[type=checkbox]').forEach(function (cb) {
    cb.checked = true;
    cb.closest('.thumb-item').classList.add('selected');
  });
  updateSelectedCount();
}

function selectNoneThumbs() {
  document.querySelectorAll('.thumb-item input[type=checkbox]').forEach(function (cb) {
    cb.checked = false;
    cb.closest('.thumb-item').classList.remove('selected');
  });
  updateSelectedCount();
}

async function batchMoveSelected() {
  const ids = Array.from(document.querySelectorAll('.thumb-item input[type=checkbox]:checked')).map(cb => cb.value);
  if (ids.length === 0) {
    alert('Select at least one photo first.');
    return;
  }
  if (!confirm('Move ' + ids.length + ' photo(s) to the review folder? They will not be deleted, just moved out of your photos folder.')) return;
  markNavigating();
  const resp = await fetch('/no-person/batch', {method: 'POST', body: new URLSearchParams({photo_ids: ids.join(',')})});
  const data = await resp.json();
  showToast('Moved ' + data.moved + ' photo(s) to the review folder');
  setTimeout(() => window.location.reload(), 1400);
}

function goToMonth(value) {
  markNavigating();
  window.location.href = '/no-person?month=' + value;
}
"""


def _render_no_person_page(months: list[dict], current_month: str | None, photos: list[dict]) -> str:
    if not months:
        body = "<p class='empty'>No photos without a person have been found yet - run a scan first.</p>"
        return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>Photo Organizer - Without a Person</title><style>{PAGE_STYLE}</style></head>
<body>
  {_top_bar("Photo Organizer - Without a Person")}
  <a class="back-link" href="/review" onclick="markNavigating()">&laquo; Back to Review</a>
  {body}
  <script>{QUIT_SCRIPT}</script>
</body></html>"""

    month_values = [m["year_month"] for m in months]
    if current_month not in month_values:
        current_month = month_values[0]
    idx = month_values.index(current_month)
    prev_month = month_values[idx + 1] if idx + 1 < len(month_values) else None  # older
    next_month = month_values[idx - 1] if idx > 0 else None  # newer

    options = "".join(
        f'<option value="{m["year_month"]}" {"selected" if m["year_month"] == current_month else ""}>'
        f'{_format_year_month(m["year_month"])} ({m["count"]})</option>'
        for m in months
    )

    thumbs = "".join(
        f"""<div class="thumb-item">
          <input type="checkbox" value="{photo['id']}" onclick="toggleThumb(this)">
          <img src="/thumb/{photo['id']}" onclick="openViewer({photo['id']}, null, null)">
        </div>"""
        for photo in photos
    )

    photo_names_json = json.dumps({p["id"]: Path(p["path"]).name for p in photos})

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Photo Organizer - Without a Person</title>
<style>{PAGE_STYLE}</style>
</head>
<body>
  {_top_bar("Photo Organizer - Without a Person")}
  <p class="intro">
    Photos where no person was detected, grouped by month so a large library stays
    manageable. This is just a browsing view - nothing is flagged automatically here.
    Check the ones you want gone and move them to the review folder yourself.
  </p>
  <a class="back-link" href="/review" onclick="markNavigating()">&laquo; Back to Review</a>

  <div class="month-nav">
    <button onclick="goToMonth('{prev_month}')" {"disabled" if not prev_month else ""}>&laquo; Older</button>
    <select onchange="goToMonth(this.value)">{options}</select>
    <button onclick="goToMonth('{next_month}')" {"disabled" if not next_month else ""}>Newer &raquo;</button>
  </div>

  <div class="batch-bar">
    <button onclick="selectAllThumbs()">Select All</button>
    <button onclick="selectNoneThumbs()">Select None</button>
    <span id="selected-count">0 selected</span>
    <div class="spacer"></div>
    <button class="btn-move-selected" onclick="batchMoveSelected()">Move Selected to Review Folder</button>
  </div>

  <div class="thumb-grid">{thumbs}</div>

  {VIEWER_HTML}
  {VIDEO_VIEWER_HTML}
  <script>
    const PHOTO_NAMES = {photo_names_json};
    {QUIT_SCRIPT}{VIEWER_SCRIPT}{VIDEO_VIEWER_SCRIPT}{NO_PERSON_SCRIPT}
  </script>
</body>
</html>"""


TRIPS_SCRIPT = """
async function renameTrip(tripId) {
  const input = document.getElementById('trip-name-' + tripId);
  await fetch('/trips/rename', {method: 'POST', body: new URLSearchParams({trip_id: tripId, name: input.value})});
  const btn = document.getElementById('trip-save-' + tripId);
  const original = btn.textContent;
  btn.textContent = 'Saved';
  setTimeout(() => { btn.textContent = original; }, 1200);
}

async function ignoreTrip(tripId) {
  if (!confirm('Ignore this trip? Its photos will be organized by Year/Month instead.')) return;
  await fetch('/trips/ignore', {method: 'POST', body: new URLSearchParams({trip_id: tripId})});
  document.getElementById('trip-card-' + tripId).remove();
}
"""


def _render_trip_card(trip: dict) -> str:
    name = trip["custom_name"] or trip["suggested_name"]
    if trip["start_date"] == trip["end_date"]:
        date_range = trip["start_date"]
    else:
        date_range = f"{trip['start_date']} to {trip['end_date']}"
    thumb_style = "width:70px;height:70px;object-fit:cover;border-radius:4px;margin-right:6px;"
    thumbs = "".join(
        _video_thumb_html(s["id"], style=thumb_style) if s["media_type"] == "video"
        else f'<img src="/thumb/{s["id"]}" class="clickable" onclick="openViewer({s["id"]}, null, null)" style="{thumb_style}">'
        for s in trip["sample_photos"]
    )
    return f"""
    <div class="card" id="trip-card-{trip['id']}">
      <div style="display:flex;gap:4px;margin-bottom:8px;">{thumbs}</div>
      <div class="filename">{escape(date_range)} &middot; {trip['photo_count']} photo(s)</div>
      <div class="folder-row" style="max-width:none;">
        <input type="text" id="trip-name-{trip['id']}" value="{escape(name)}" style="flex:1;padding:6px;border:1px solid var(--line);border-radius:4px;background:var(--surface);color:var(--ink);">
      </div>
      <div class="actions">
        <button id="trip-save-{trip['id']}" class="btn-reject" onclick="renameTrip({trip['id']})">Save Name</button>
        <button class="btn-approve" onclick="ignoreTrip({trip['id']})">Ignore This Trip</button>
      </div>
    </div>
    """


def _render_trips_page(candidates: list[dict]) -> str:
    vacations = [c for c in candidates if c["kind"] == "vacation"]
    day_trips = [c for c in candidates if c["kind"] == "day_trip"]

    vacations_html = (
        "".join(_render_trip_card(c) for c in vacations)
        if vacations
        else "<p class='empty'>No vacations detected yet.</p>"
    )
    day_trips_html = (
        "".join(_render_trip_card(c) for c in day_trips)
        if day_trips
        else "<p class='empty'>No day trips detected yet.</p>"
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Photo Organizer - Trips</title>
<style>{PAGE_STYLE}</style>
</head>
<body>
  {_top_bar("Photo Organizer - Trips")}
  <p class="intro">
    Detected using GPS and date metadata: photos taken more than {int(AWAY_DISTANCE_MILES)} miles
    from your detected home location. Multi-day stretches away are "Vacations"; single days away with
    enough photos are "Day Trips". Edit the name below and it'll be used as the folder name when you
    Organize. If a batch of photos was sent to you by friends or family and doesn't represent a real
    trip, use "Ignore This Trip" and it'll be organized by Year/Month instead.
  </p>
  <a class="back-link" href="/organize" onclick="markNavigating()">&laquo; Back to Organize</a>

  <h2>Vacations</h2>
  <div class="cards">{vacations_html}</div>

  <h2>Day Trips</h2>
  <div class="cards">{day_trips_html}</div>

  {VIEWER_HTML}
  {VIDEO_VIEWER_HTML}
  <script>
    {QUIT_SCRIPT}{VIEWER_SCRIPT}{VIDEO_VIEWER_SCRIPT}{TRIPS_SCRIPT}
  </script>
</body>
</html>"""


def _format_session_range(start_iso: str, end_iso: str) -> str:
    # "%-d" (no leading zero) is a glibc strftime extension not supported on
    # Windows - build the day number separately instead.
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    start_date = f"{start.strftime('%B')} {start.day}, {start.year}"
    end_date = f"{end.strftime('%B')} {end.day}, {end.year}"
    start_time = start.strftime("%I:%M %p").lstrip("0")
    end_time = end.strftime("%I:%M %p").lstrip("0")
    if start.date() == end.date():
        return f"{start_date}, {start_time} - {end_time}"
    return f"{start_date} {start_time} - {end_date} {end_time}"


VIDEO_SESSIONS_SCRIPT = """
function updateSessionCount(containerId) {
  const n = document.querySelectorAll('#' + containerId + ' .thumb-item input[type=checkbox]:checked').length;
  document.getElementById(containerId + '-count').textContent = n + ' selected';
}

function toggleSessionThumb(cb, containerId) {
  cb.closest('.thumb-item').classList.toggle('selected', cb.checked);
  updateSessionCount(containerId);
}

function selectAllInSession(containerId) {
  document.querySelectorAll('#' + containerId + ' .thumb-item input[type=checkbox]').forEach(function (cb) {
    cb.checked = true;
    cb.closest('.thumb-item').classList.add('selected');
  });
  updateSessionCount(containerId);
}

function selectNoneInSession(containerId) {
  document.querySelectorAll('#' + containerId + ' .thumb-item input[type=checkbox]').forEach(function (cb) {
    cb.checked = false;
    cb.closest('.thumb-item').classList.remove('selected');
  });
  updateSessionCount(containerId);
}

async function batchMoveSession(containerId) {
  const ids = Array.from(document.querySelectorAll('#' + containerId + ' .thumb-item input[type=checkbox]:checked')).map(cb => cb.value);
  if (ids.length === 0) {
    alert('Select at least one video first.');
    return;
  }
  if (!confirm('Move ' + ids.length + ' video(s) to the review folder? They will not be deleted, just moved out of your photos folder.')) return;
  markNavigating();
  const resp = await fetch('/video-sessions/batch', {method: 'POST', body: new URLSearchParams({photo_ids: ids.join(',')})});
  const data = await resp.json();
  showToast('Moved ' + data.moved + ' video(s) to the review folder');
  setTimeout(() => window.location.reload(), 1400);
}
"""


def _render_video_session(index: int, sess: dict) -> str:
    container_id = f"session-{index}"
    time_range = _format_session_range(sess["start"], sess["end"])
    thumbs = "".join(
        f"""<div class="thumb-item">
          <input type="checkbox" value="{v['id']}" onclick="toggleSessionThumb(this, '{container_id}')">
          {_video_thumb_html(v['id'])}
        </div>"""
        for v in sess["videos"]
    )
    return f"""
    <div class="card card-wide" id="{container_id}" style="width:auto;max-width:900px;">
      <h3 style="margin-top:0;">{escape(time_range)} &middot; {sess['count']} video(s)</h3>
      <div class="batch-bar">
        <button onclick="selectAllInSession('{container_id}')">Select All</button>
        <button onclick="selectNoneInSession('{container_id}')">Select None</button>
        <span id="{container_id}-count">0 selected</span>
        <div class="spacer"></div>
        <button class="btn-move-selected" onclick="batchMoveSession('{container_id}')">Move Selected to Review Folder</button>
      </div>
      <div class="thumb-grid">{thumbs}</div>
    </div>
    """


def _render_video_sessions_page(sessions: list[dict]) -> str:
    if not sessions:
        body = "<p class='empty'>No videos found yet - run a scan first.</p>"
    else:
        body = "".join(_render_video_session(i, s) for i, s in enumerate(sessions))

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Photo Organizer - Video Sessions</title>
<style>{PAGE_STYLE}</style>
</head>
<body>
  {_top_bar("Photo Organizer - Video Sessions")}
  <p class="intro">
    Videos grouped by when they were recorded, so a batch from the same event (a
    birthday, a game, a trip) can be reviewed together instead of one at a time.
    This is just a browsing view - nothing is flagged automatically here.
  </p>
  <a class="back-link" href="/review" onclick="markNavigating()">&laquo; Back to Review</a>
  {body}
  {VIDEO_VIEWER_HTML}
  <script>
    {QUIT_SCRIPT}{VIDEO_SESSIONS_SCRIPT}{VIDEO_VIEWER_SCRIPT}
  </script>
</body>
</html>"""


SEARCH_SCRIPT = """
function updateSelectedCount() {
  const n = document.querySelectorAll('.thumb-item input[type=checkbox]:checked').length;
  document.getElementById('selected-count').textContent = n + ' selected';
}

function toggleThumb(cb) {
  cb.closest('.thumb-item').classList.toggle('selected', cb.checked);
  updateSelectedCount();
}

function selectAllThumbs() {
  document.querySelectorAll('.thumb-item input[type=checkbox]').forEach(function (cb) {
    cb.checked = true;
    cb.closest('.thumb-item').classList.add('selected');
  });
  updateSelectedCount();
}

function selectNoneThumbs() {
  document.querySelectorAll('.thumb-item input[type=checkbox]').forEach(function (cb) {
    cb.checked = false;
    cb.closest('.thumb-item').classList.remove('selected');
  });
  updateSelectedCount();
}

async function batchMoveSelected() {
  const ids = Array.from(document.querySelectorAll('.thumb-item input[type=checkbox]:checked')).map(cb => cb.value);
  if (ids.length === 0) {
    alert('Select at least one item first.');
    return;
  }
  if (!confirm('Move ' + ids.length + ' item(s) to the review folder? They will not be deleted, just moved out of your photos folder.')) return;
  markNavigating();
  const resp = await fetch('/search/batch', {method: 'POST', body: new URLSearchParams({photo_ids: ids.join(',')})});
  const data = await resp.json();
  showToast('Moved ' + data.moved + ' item(s) to the review folder');
  setTimeout(() => window.location.reload(), 1400);
}

function runSearch() {
  const q = document.getElementById('search_query').value;
  markNavigating();
  window.location.href = '/search?q=' + encodeURIComponent(q);
}
"""


def _render_search_page(query: str, results: list[dict], models_ready: bool) -> str:
    if not models_ready:
        body = (
            "<p class='empty'>Search needs the content-tagging model, which hasn't been "
            "downloaded yet. Run Setup.bat again to enable it.</p>"
        )
    elif not query:
        body = '<p class="empty">Type something above and press Search - e.g. "birthday cake" or "dog at the beach".</p>'
    elif not results:
        body = "<p class='empty'>No matches found.</p>"
    else:
        cards = []
        for r in results:
            if r["media_type"] == "video":
                offset = r.get("best_offset_seconds") or 0
                cards.append(f"""<div class="thumb-item">
                  <input type="checkbox" value="{r['id']}" onclick="toggleThumb(this)">
                  {_video_thumb_html(r['id'], offset_seconds=offset)}
                </div>""")
            else:
                cards.append(f"""<div class="thumb-item">
                  <input type="checkbox" value="{r['id']}" onclick="toggleThumb(this)">
                  <img src="/thumb/{r['id']}" onclick="openViewer({r['id']}, null, null)">
                </div>""")
        thumbs = "".join(cards)
        body = f"""
        <div class="batch-bar">
          <button onclick="selectAllThumbs()">Select All</button>
          <button onclick="selectNoneThumbs()">Select None</button>
          <span id="selected-count">0 selected</span>
          <div class="spacer"></div>
          <button class="btn-move-selected" onclick="batchMoveSelected()">Move Selected to Review Folder</button>
        </div>
        <div class="thumb-grid">{thumbs}</div>
        """

    photo_names_json = json.dumps({r["id"]: Path(r["path"]).name for r in results})

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Photo Organizer - Search</title>
<style>{PAGE_STYLE}</style>
</head>
<body>
  {_top_bar("Photo Organizer - Search")}
  <p class="intro">
    Search your photos by what's in them - e.g. "birthday cake" or "dog at the beach".
    This is a browsing view - nothing is flagged automatically. Select the ones you
    want gone and move them to the review folder yourself.
  </p>
  <a class="back-link" href="/review" onclick="markNavigating()">&laquo; Back to Review</a>

  <div class="folder-row">
    <label>Search:</label>
    <input type="text" id="search_query" value="{escape(query)}" onkeydown="if(event.key==='Enter') runSearch()">
    <button onclick="runSearch()">Search</button>
  </div>

  {body}
  {VIEWER_HTML}
  {VIDEO_VIEWER_HTML}
  <script>
    const PHOTO_NAMES = {photo_names_json};
    {QUIT_SCRIPT}{VIEWER_SCRIPT}{VIDEO_VIEWER_SCRIPT}{SEARCH_SCRIPT}
  </script>
</body>
</html>"""


_pick_folder_lock = threading.Lock()


def create_app() -> FastAPI:
    app = FastAPI()
    scan_state = ScanState()
    organize_state = ScanState()

    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.INFO)
    handler = ScanStateLogHandler(scan_state)
    handler.setFormatter(logging.Formatter("%(message)s"))
    app_logger.addHandler(handler)

    @app.get("/healthz", response_class=Response)
    def healthz() -> Response:
        # Distinguishes "our server is actually answering" from "something is
        # listening on this port" - a raw TCP connect can't tell those apart, and a
        # stray unrelated process on the same port would otherwise look ready.
        return Response(content=HEALTH_SENTINEL, media_type="text/plain")

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        config = _get_config()
        source = read_saved_location(CONFIG_PATH, "source_dir")
        quarantine = read_saved_location(CONFIG_PATH, "quarantine_dir")
        video_review_mode = read_saved_location(CONFIG_PATH, "video_review_mode") or "medium"
        video_search_depth = read_saved_location(CONFIG_PATH, "video_search_depth") or "fast"
        with session(config.db_path) as conn:
            pending = conn.execute(
                "SELECT COUNT(DISTINCT photo_id) c FROM recommendations WHERE decision = 'pending'"
            ).fetchone()["c"]
        return _render_home_page(
            source, quarantine, pending, config.auto_quarantine_exact_duplicates,
            video_review_mode, video_search_depth, content_tagging.gpu_available(),
        )

    @app.post("/pick-folder")
    def pick_folder(field: str = Form(...)) -> JSONResponse:
        import tkinter as tk
        from tkinter import filedialog

        with _pick_folder_lock:  # Tcl isn't safe for concurrent use across threads
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            try:
                if field == "source":
                    chosen = filedialog.askdirectory(title="Select your photos folder")
                elif field == "organize_dest":
                    chosen = filedialog.askdirectory(title="Select where to organize your photos into")
                else:
                    chosen = filedialog.askdirectory(title="Select a folder to hold the review folder")
            finally:
                root.destroy()

        if not chosen:
            return JSONResponse({"path": ""})
        if field == "quarantine":
            chosen = str(Path(chosen) / REVIEW_SUBFOLDER_NAME)
        return JSONResponse({"path": chosen})

    @app.post("/start-scan")
    def start_scan(
        source_dir: str = Form(""), quarantine_dir: str = Form(""), auto_quarantine: str = Form("false"),
        video_review_mode: str = Form("medium"), video_search_depth: str = Form("fast"),
    ) -> JSONResponse:
        if scan_state.snapshot()["running"]:
            return JSONResponse({"error": "A scan is already running."}, status_code=409)

        source_dir = source_dir.strip()
        quarantine_dir = quarantine_dir.strip()
        source = Path(source_dir)
        if not source_dir or not source.is_dir():
            return JSONResponse({"error": "Please choose a photos folder that exists."}, status_code=400)
        if not quarantine_dir:
            return JSONResponse({"error": "Please choose a review folder."}, status_code=400)

        quarantine = Path(quarantine_dir)
        source_resolved = source.resolve()
        quarantine_resolved = quarantine.resolve()
        if quarantine_resolved == source_resolved or source_resolved.is_relative_to(quarantine_resolved):
            return JSONResponse(
                {"error": "The review folder can't be the same as, or contain, the photos folder."},
                status_code=400,
            )

        try:
            quarantine.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return JSONResponse({"error": f"Couldn't create the review folder: {exc}"}, status_code=400)

        if video_review_mode not in VIDEO_REVIEW_MODES:
            return JSONResponse({"error": "Invalid video review mode."}, status_code=400)
        if video_search_depth not in VIDEO_SEARCH_DEPTH_SECONDS:
            return JSONResponse({"error": "Invalid video search depth."}, status_code=400)

        set_config_value(CONFIG_PATH, "source_dir", str(source))
        set_config_value(CONFIG_PATH, "quarantine_dir", str(quarantine))
        set_config_bool(CONFIG_PATH, "auto_quarantine_exact_duplicates", auto_quarantine == "true")
        set_config_value(CONFIG_PATH, "video_review_mode", video_review_mode)
        set_config_value(CONFIG_PATH, "video_search_depth", video_search_depth)

        scan_state.start()
        threading.Thread(target=_run_pipeline, args=(source, quarantine, scan_state), daemon=True).start()
        return JSONResponse({"ok": True})

    @app.get("/scan-status")
    def scan_status() -> JSONResponse:
        return JSONResponse(scan_state.snapshot())

    @app.post("/shutdown")
    def shutdown() -> HTMLResponse:
        def delayed_exit() -> None:
            time.sleep(0.5)
            os._exit(0)

        threading.Thread(target=delayed_exit, daemon=True).start()
        return HTMLResponse("<html><body><h2>Shutting down...</h2></body></html>")

    @app.get("/review", response_class=HTMLResponse)
    def review() -> str:
        config = _get_config()
        with session(config.db_path) as conn:
            items = get_pending_review_items(conn)
            duplicate_groups = get_pending_duplicate_groups(conn)
            quarantine_stats = get_quarantine_stats(conn)
        return _render_review_page(items, quarantine_stats, duplicate_groups)

    @app.post("/purge")
    def purge() -> JSONResponse:
        config = _get_config()
        with session(config.db_path) as conn:
            result = purge_quarantined(conn, config)
        return JSONResponse(result)

    @app.get("/organize", response_class=HTMLResponse)
    def organize_page() -> str:
        config = _get_config()
        with session(config.db_path) as conn:
            active_count = conn.execute("SELECT COUNT(*) c FROM photos WHERE status = 'active'").fetchone()["c"]
            folder_preview = get_folder_preview(conn, config.source_dir)
        dest_dir = read_saved_location(CONFIG_PATH, "organize_dest_dir")
        default_head_folder = datetime.now().strftime("%Y-%m-%d")
        return _render_organize_page(active_count, dest_dir, default_head_folder, folder_preview)

    @app.post("/start-organize")
    def start_organize(
        dest_dir: str = Form(""),
        head_folder: str = Form(""),
        excluded_folders: str = Form(""),
        exclude_mode: str = Form("skip"),
    ) -> JSONResponse:
        if organize_state.snapshot()["running"]:
            return JSONResponse({"error": "Organizing is already running."}, status_code=409)

        dest_dir = dest_dir.strip()
        head_folder = head_folder.strip()
        if not dest_dir:
            return JSONResponse({"error": "Please choose a folder to organize into."}, status_code=400)
        if not head_folder:
            return JSONResponse({"error": "Please enter a folder name."}, status_code=400)
        if any(c in head_folder for c in '<>:"/\\|?*'):
            return JSONResponse({"error": "Folder name can't contain \\ / : * ? \" < > |"}, status_code=400)
        if exclude_mode not in ("skip", "move_as_is"):
            return JSONResponse({"error": "Invalid exclude mode."}, status_code=400)

        excluded_set = {label for label in excluded_folders.split("") if label}

        set_config_value(CONFIG_PATH, "organize_dest_dir", dest_dir)

        dest_root = Path(dest_dir) / head_folder
        organize_state.start()
        threading.Thread(
            target=_run_organize_job,
            args=(dest_root, excluded_set, exclude_mode, organize_state),
            daemon=True,
        ).start()
        return JSONResponse({"ok": True})

    @app.get("/organize-status")
    def organize_status() -> JSONResponse:
        return JSONResponse(organize_state.snapshot())

    @app.get("/no-person", response_class=HTMLResponse)
    def no_person(month: str | None = None) -> str:
        config = _get_config()
        with session(config.db_path) as conn:
            months = get_no_person_months(conn)
            valid_months = [m["year_month"] for m in months]
            actual_month = month if month in valid_months else (valid_months[0] if valid_months else None)
            photos = get_no_person_photos_for_month(conn, actual_month) if actual_month else []
        return _render_no_person_page(months, actual_month, photos)

    @app.post("/no-person/batch")
    def no_person_batch(photo_ids: str = Form(...)) -> JSONResponse:
        config = _get_config()
        ids = [int(x) for x in photo_ids.split(",") if x.strip()]
        with session(config.db_path) as conn:
            result = quarantine_photos_batch(conn, config, ids)
        return JSONResponse(result)

    @app.get("/search", response_class=HTMLResponse)
    def search_page(q: str = "") -> str:
        config = _get_config()
        query = q.strip()
        models_ready = content_tagging.models_downloaded()
        results: list[dict] = []
        if query and models_ready:
            with session(config.db_path) as conn:
                backend = _get_clip_backend()
                ranked = search_library(conn, backend, query)
                id_order = [r["id"] for r in ranked]
                if id_order:
                    placeholders = ",".join("?" * len(id_order))
                    rows_by_id = {
                        row["id"]: dict(row)
                        for row in conn.execute(f"SELECT * FROM photos WHERE id IN ({placeholders})", id_order)
                    }
                    for r in ranked:
                        row = rows_by_id.get(r["id"])
                        if row is None:
                            continue
                        row["best_offset_seconds"] = r["offset_seconds"]
                        results.append(row)
        return _render_search_page(query, results, models_ready)

    @app.post("/search/batch")
    def search_batch(photo_ids: str = Form(...)) -> JSONResponse:
        config = _get_config()
        ids = [int(x) for x in photo_ids.split(",") if x.strip()]
        with session(config.db_path) as conn:
            result = quarantine_photos_batch(conn, config, ids)
        return JSONResponse(result)

    @app.get("/video-sessions", response_class=HTMLResponse)
    def video_sessions_page() -> str:
        config = _get_config()
        with session(config.db_path) as conn:
            sessions = get_video_sessions(conn)
        return _render_video_sessions_page(sessions)

    @app.post("/video-sessions/batch")
    def video_sessions_batch(photo_ids: str = Form(...)) -> JSONResponse:
        config = _get_config()
        ids = [int(x) for x in photo_ids.split(",") if x.strip()]
        with session(config.db_path) as conn:
            result = quarantine_photos_batch(conn, config, ids)
        return JSONResponse(result)

    @app.get("/trips", response_class=HTMLResponse)
    def trips_page() -> str:
        config = _get_config()
        with session(config.db_path) as conn:
            run_trip_detection(conn)
            candidates = get_trip_candidates(conn)
        return _render_trips_page(candidates)

    @app.post("/trips/rename")
    def trips_rename(trip_id: int = Form(...), name: str = Form(...)) -> JSONResponse:
        config = _get_config()
        with session(config.db_path) as conn:
            set_trip_name(conn, trip_id, name)
        return JSONResponse({"ok": True})

    @app.post("/trips/ignore")
    def trips_ignore(trip_id: int = Form(...)) -> JSONResponse:
        config = _get_config()
        with session(config.db_path) as conn:
            ignore_trip(conn, trip_id)
        return JSONResponse({"ok": True})

    @app.get("/thumb/{photo_id}")
    def thumb(photo_id: int) -> Response:
        config = _get_config()
        with session(config.db_path) as conn:
            row = conn.execute("SELECT path, media_type FROM photos WHERE id = ?", (photo_id,)).fetchone()
        if row is None or not Path(row["path"]).exists():
            raise HTTPException(status_code=404, detail="photo not found")
        try:
            data = _thumbnail_bytes(Path(row["path"]), row["media_type"])
        except Exception:
            log.exception("Failed to render thumbnail for photo %s", photo_id)
            raise HTTPException(status_code=500, detail="could not render thumbnail")
        return Response(content=data, media_type="image/jpeg")

    @app.get("/full/{photo_id}")
    def full(photo_id: int) -> Response:
        config = _get_config()
        with session(config.db_path) as conn:
            row = conn.execute("SELECT path, media_type FROM photos WHERE id = ?", (photo_id,)).fetchone()
        if row is None or not Path(row["path"]).exists():
            raise HTTPException(status_code=404, detail="photo not found")
        try:
            data = _full_bytes(Path(row["path"]), row["media_type"])
        except Exception:
            log.exception("Failed to render full image for photo %s", photo_id)
            raise HTTPException(status_code=500, detail="could not render image")
        return Response(content=data, media_type="image/jpeg")

    @app.get("/videofile/{photo_id}")
    def videofile(photo_id: int) -> FileResponse:
        config = _get_config()
        with session(config.db_path) as conn:
            row = conn.execute("SELECT path, media_type FROM photos WHERE id = ?", (photo_id,)).fetchone()
        if row is None or row["media_type"] != "video" or not Path(row["path"]).exists():
            raise HTTPException(status_code=404, detail="video not found")
        media_type = mimetypes.guess_type(row["path"])[0] or "video/mp4"
        return FileResponse(row["path"], media_type=media_type)

    @app.post("/decide/{photo_id}")
    def decide_one(photo_id: int, decision: str = Form(...)) -> RedirectResponse:
        config = _get_config()
        with session(config.db_path) as conn:
            decide(conn, config, photo_id, decision)
        return RedirectResponse(url="/review", status_code=303)

    @app.post("/decide-bulk")
    def decide_bulk(photo_ids: str = Form(...), decision: str = Form(...)) -> RedirectResponse:
        config = _get_config()
        ids = [int(x) for x in photo_ids.split(",") if x.strip()]
        with session(config.db_path) as conn:
            for photo_id in ids:
                decide(conn, config, photo_id, decision)
        return RedirectResponse(url="/review", status_code=303)

    @app.post("/decide-group")
    def decide_group(discard_ids: str = Form(""), keep_ids: str = Form("")) -> RedirectResponse:
        """Resolves a whole duplicate group in one submission - each checked member
        (which may or may not include the suggested keeper) gets moved to the review
        folder, everything left unchecked gets kept - reusing decide() exactly as
        the single-photo and bulk routes above do, so this needs no new logic
        beyond composing calls to it."""
        config = _get_config()
        discard = [int(x) for x in discard_ids.split(",") if x.strip()]
        keep = [int(x) for x in keep_ids.split(",") if x.strip()]
        with session(config.db_path) as conn:
            for photo_id in discard:
                decide(conn, config, photo_id, "approved")
            for photo_id in keep:
                decide(conn, config, photo_id, "rejected")
        return RedirectResponse(url="/review", status_code=303)

    return app
