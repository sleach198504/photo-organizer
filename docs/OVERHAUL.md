# Photo Organizer 2.0 - overhaul plan

Working branch: `redesign`. Goal: turn a working utility into a product that looks
and behaves like professional photo software, without losing the guarantees that
made it trustworthy (offline, nothing deleted without an explicit step).

**Status:** every phase below is implemented for 2.0.0 (see `CHANGELOG.md`). What was
verified: an end-to-end test that drives the whole lifecycle over HTTP, a 20,000-photo stress
run (every API call under ~160 ms), WCAG AA contrast for both themes (`dev/contrast.mjs`),
a v1 database opening cleanly under the new code, and the real Edge app window launching with a
single-instance check.

## What research told us (applied below)

- **Neutral surroundings for photos.** Lightroom, Capture One, Photoshop and DaVinci
  all offer neutral gray surrounds because a colored UI shifts perceived color. The
  chrome stays achromatic; the user's photos are the only color on screen.
- **Mark first, commit once.** Culling tools flag (pick/reject) freely and apply
  later (Lightroom P/X/U with auto-advance). Duplicate finders pre-select and make
  the user confirm, and explain *why* a photo was auto-picked (score/reason).
- **Undo over confirmation.** For reversible actions, do it instantly and offer an
  undo toast; reserve confirmation dialogs for the one irreversible step (permanent
  delete). Dialog fatigue trains people to click through warnings.
- **Grid + loupe + compare.** Adjustable thumbnail size, a single-image loupe with
  Escape to close and prev/next (arrows + keyboard), preload the neighbor, 100%
  zoom for judging sharpness, side-by-side compare for similar shots.
- **Scale.** Large libraries need virtualized grids (Flickr pruned the DOM; Google
  Photos / Immich virtualize and offer a scrubbable timeline). Thumbnails must be
  cached on disk, not re-rendered per request.
- **Navigation.** Persistent sidebar with 3-5 groups, max two levels, tonal
  background instead of heavy borders, clear active state; the layout serves the
  information architecture, not the reverse.
- **Windows 11 type ramp** (Segoe UI Variable): 12/16, 14/20, 20/28, 28/36, 40/52;
  Semibold (not Bold) for emphasis.

## Product structure (information architecture)

```
Home            what's in your library, what to do next, recent activity
Library
  Photos        everything, filterable, searchable, virtual grid
  Videos        same grid, videos only, grouped by session
  Trips         detected vacations and day trips
Cleanup
  Review        duplicates, similar, blurry, screenshots, documents, ...
  Removed       what was moved to the review folder; restore or delete forever
Organize        file survivors into dated folders (with preview)
-----
Scan status, Settings, Shortcuts, Exit
```

## Signature design idea (the one bold thing)

Photo culling started on **contact sheets**: you cross out rejected frames with a
red grease pencil and circle the picks. Decision marks in the UI are drawn that way
(a red slash across a rejected frame, a ring on a keeper), and burst groups are
laid out as a **contact strip**. Everything else is deliberately quiet.

## Design tokens

- Surfaces (dark, default follows OS): canvas `#151618`, sidebar `#1b1c1f`,
  panel `#212327`, raised `#2a2c31`, hairline `#33363c`.
- Text: `#ebecee` / `#a6aab1` / `#70757d`. Light theme mirrors with true neutrals.
- Accent "cyanotype" blue (photographic heritage): `#6ea8e6` on dark, `#1f5fa8` on
  light. Semantic: keep `#6cc08a`, remove (grease-pencil red) `#e5483b`.
- Type: Figtree variable (UI + numerals, tabular where it matters). Scale 12/13/14/
  16/20/28/40. Sentence case labels, no all-caps eyebrows.
- Radius hierarchy: 4 thumbs/chips, 6 controls, 10 panels, 14 dialogs. Elevation by
  tone first, shadow only for floating layers.

## Architecture

- Backend: FastAPI JSON API under `/api`, media under `/media`, static SPA shell.
  Pipeline reports real stage progress and supports cancel. Marks, activity log and
  original paths persisted in SQLite (migrated in place; old databases keep working).
- Frontend: no build step. Preact + htm + signals, vendored in `static/js/vendor`,
  native ES modules with an import map. Lucide icons (ISC) as an SVG sprite. Fonts
  bundled (OFL). Everything works fully offline.
- Lifecycle: the page heartbeats; the server exits shortly after the window closes
  (replaces the fragile `pagehide` beacon that broke on reload).
- Safety invariants (unchanged): nothing is deleted except by the typed
  confirmation in Removed; removal means "move to the review folder"; every move is
  restorable (original path recorded).

## Bugs found during the audit (fixed in this overhaul)

- `taken_at` was NULL for every photo: EXIF `DateTimeOriginal` lives in the Exif
  sub-IFD, which the indexer never read. Organize/trips fell back to file dates.
- Videos never had a capture date or GPS (now read from the MP4/MOV header).
- Thumbnails were regenerated on every request (now cached on disk).
- Closing/reloading the window could leave or kill the server unpredictably.

## Phases

A. Foundations: paths/home override, DB migrations, EXIF fix + backfill, pipeline
   progress/cancel, thumbnail cache, JSON API, tests, demo-library generator.
B. Design system, app shell, router, Home, Settings, first-run, Scan experience.
C. Review (groups + flat categories, marks, tray, apply/undo, keyboard), Lightbox +
   Compare, Removed.
D. Library (virtual grid, filters, search, timeline jump), Videos, Trips.
E. Organize (preview, templates, exclusions), accessibility pass, empty/error
   states, shortcuts overlay, app icon + installer, README, version 2.0, release.
