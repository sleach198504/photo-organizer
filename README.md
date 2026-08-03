# Photo Organizer

A local, offline tool for trimming down a large iPhone photo and video dump:
finds exact and near-duplicates (for both photos and videos), flags blurry
shots and long/flagged videos, tags content like food/screenshots/documents,
lets you search your library by what's actually in a photo or video, and
lets you browse photos without a person in them - all so you can review and
delete with confidence instead of scrolling through 150GB by hand.

## Privacy

Nothing here ever leaves your PC. Fully self-contained - no external services,
no separate app to install, no background service running outside this app.

- All scanning, hashing, and scoring runs locally against files on disk.
- Content tagging uses [CLIP](https://huggingface.co/openai/clip-vit-base-patch32)
  (an open-source local image classifier, ~580MB), downloaded once by
  `Setup.bat` into this project's own `models/` folder. Every run after that
  uses `local_files_only=True` - it is not possible for content tagging to
  make a network call once setup has finished, guaranteed by the code, not
  just by disconnecting the network.
- Trip-name place lookups (e.g. turning GPS coordinates into "Orlando,
  Florida") use a bundled offline city database - no mapping/geocoding
  service is ever contacted.
- Content search reuses the same local CLIP model - a search box that finds
  "a birthday cake" in your library never sends that text, or any photo,
  anywhere. It's the same one-time-download-then-`local_files_only=True`
  guarantee as content tagging above.
- The whole app - folder selection, scanning, and review - is a local web
  server bound to `127.0.0.1` only; it is not reachable from your network or
  the internet, and opens in your regular browser as one page.
- Nothing is ever hard-deleted automatically. Flagged photos are moved to a
  quarantine folder for review; permanent deletion is a separate, explicit
  step you trigger yourself.

## Requirements

- Nothing to install yourself first - `Setup.bat` installs Python
  automatically if it isn't already on the PC (no manual download needed),
  along with everything else, including the content-tagging model (~600MB
  one-time download).
- An NVIDIA GPU is optional, not required - setup detects one automatically
  and offers a faster GPU-accelerated install; everything works fine without
  one too.

## Setup (first time on any PC)

1. Double-click `Setup.bat`. A window opens describing exactly what's about
   to be installed - read it and click **Confirm** to continue (or Cancel to
   stop here, nothing is installed yet at that point). No console window
   ever appears; this is all one small setup window with a progress bar.
2. If an NVIDIA GPU is detected, you'll be asked to choose between a faster
   GPU-accelerated install (~3.5GB download) or the smaller CPU one
   (~500MB) - pick either, this can be changed later by re-running Setup.
3. Setup installs Photo Organizer into your user Programs folder
   (`%LocalAppData%\Programs\Photo Organizer`) - not wherever you happened
   to download this from - and puts a **"Photo Organizer" shortcut on the
   Desktop**. It also registers a normal uninstall entry, so it shows up in
   Windows Settings > Apps like any other program. Takes a few minutes;
   only needs to be done once.
4. Double-click that Desktop shortcut. No file editing, no command line -
   it opens a browser tab asking which folders to use.

## Moving to a new PC / giving this to someone else

Copy the whole `photo-organizer` source folder (however you got it - the
`venv/` and `data/` folders inside it, if present, aren't needed and are
already excluded by `.gitignore` if you use git) to the new PC and double-
click `Setup.bat` there. It installs its own fresh copy into that PC's
Programs folder and creates a Desktop shortcut for that machine - if the
source folder you copied already had a `config.yaml`/`data/` from prior use,
those get carried over automatically as long as the new PC doesn't already
have its own Photo Organizer install.

## Usage

Double-click the **"Photo Organizer" Desktop shortcut** (or `launch.bat`
with no arguments, which does the same thing). It opens one plain window -
just the app, no address bar or browser tabs - everything happens there.

**Scan page** (the page you land on): pick your photos folder and a review
folder using the "Browse..." buttons (real Windows folder dialogs - nothing
to type). Both fields are pre-filled with whatever was used last time, so
after the first run it's just "click Start Scanning." Clicking it runs the
whole analysis pipeline, with live progress in the page:

1. **Scan** - indexes any new or changed photos (EXIF, hashes, Live Photo
   pairing) and standalone videos (not Live Photo pairs) - duration, a
   representative-frame hash, and a best-effort check for whether it looks
   like a phone screen recording rather than a real video.
2. **Blur check** - scores every photo and flags the blurry ones (videos aren't scored for blur)
3. **Duplicate check** - finds byte-identical duplicates and clusters of
   near-identical/burst shots for photos, and separately for videos (matched
   off each video's representative frame), picking a suggested "keeper" for
   each group
4. **Content check** - flags food photos, screenshots, documents/receipts,
   memes/social media images, whiteboards/notes, and blank/accidental shots.
   Also tags whether each photo has a person in it, for the browse page
   below, and builds the search index used by the Search page. This is the
   slow step (roughly a quarter-second per photo) - skipped automatically if
   the content-tagging model hasn't been downloaded yet.

There's a checkbox on the scan page - **"Automatically move byte-identical
duplicate copies to the review folder"** - for skipping manual review on
just exact duplicates specifically (byte-for-byte identical files are the
one category safe enough to not need a second look). Off by default;
everything else always waits for you regardless of this setting.

Two more dropdowns control video handling:

- **"Flag videos for review"** - Off / All videos / Medium length or longer
  (1 min+) / Long only (5 min+). Defaults to Medium. This is separate from
  duplicate/screen-recording detection, which always run regardless.
- **"Video search detail"** - Fast (checks every 10 seconds of each video) or
  Thorough (every 1 second). Fast is the default and is enough to find the
  right video for a search; Thorough is more precise but can take much
  longer to scan on a CPU-only PC, with a warning shown when you pick it.

It's safe to re-run any time - already-indexed photos and already-decided
recommendations aren't redone. Note: this analysis considers every photo
this install has ever indexed, not just whatever folder you scanned most
recently - so if you point it at a new, unrelated folder later, photos from
both will be compared against each other. Fine for one growing photo
library; worth knowing if you use the same install for separate one-off jobs.

Nothing is moved based on these results until you say so - click **"Review
Flagged Photos"** once scanning finishes to switch to the review page in
that same window. It shows each flagged photo or video grouped by why it
was flagged (Exact Duplicates, Similar/Burst Photos and Similar Videos with
the suggested "keeper" shown side-by-side, Blurry Photos, Possible Screen
Recordings, Videos, and a section per content category that actually found
something - empty categories don't clutter the page). For each item:

- **"Move to Review Folder"** - moves that photo or video (and its Live
  Photo video, if it has one) out of your photos folder into the review
  folder. Not deleted - you can move it back yourself anytime from the
  review folder.
- **"Keep This Photo"** - dismisses the suggestion; it stays put and won't
  be flagged again by future scans.

Exact duplicates have a "Move All to Review Folder" bulk button too, since
byte-identical copies are the lowest-risk call to make in bulk.

Click any photo to open it larger, with **Single**, **Side by Side**, and
**Slider** (drag to compare before/after) view modes - the compare modes
only show up for photos that have something to compare against. Videos play
inline in their card instead, with normal playback controls.

**Search Photos** (linked from the review page): a search box over what's
actually in your photos and videos - try "birthday cake" or "dog at the
beach". Videos are matched against frames sampled throughout the clip (see
"Video search detail" above), not just one thumbnail, and results jump
straight to the matching moment when you press play. This is a browsing
view like "Browse Photos Without a Person" below - select what you want
gone and move it to the review folder yourself; nothing is flagged
automatically here. Needs the content-tagging model to be downloaded.

**Browse Photos Without a Person**: content tagging also checks whether each
photo has a person in it - this page (linked from the review page) lets you
browse everything that doesn't, grouped by month since this category is
usually huge (most receipts, screenshots, and landscape shots end up here
too). Check the ones you want gone and click "Move Selected to Review
Folder" - unlike the auto-flagged categories, nothing here is pre-selected
for you, it's a manual browse-and-pick view. Same rule as everywhere else:
this only moves photos, never deletes them.

**Browse Videos by Session** (linked from the review page): groups your
videos by when they were recorded, so a batch from the same event (a
birthday, a game) can be reviewed and selected together instead of one at a
time. Same manual browse-and-pick pattern as above - nothing is flagged
automatically.

**Emptying the review folder**: the review page shows how many photos (and
how much space) are sitting in the review folder, with a **"Permanently
Delete"** button. This is the one truly irreversible action in the whole
app - it asks for confirmation with the exact count and size first.

**Organize page**: once you're done reviewing, click "Organize Remaining
Photos" to move everything left into dated folders for long-term storage -
`<folder you pick>/<batch name>/<year>/<month>/`, based on when each photo
was taken (falling back to the file's modified date if that's missing). The
batch name defaults to today's date but you can type anything. This moves
photos out of your photos folder - it's meant to be the last step once
you're happy with what survived review.

**Detect Vacations & Day Trips** (linked from the Organize page): uses each
photo's GPS location and date to figure out where "home" is (the most common
location among your photos - no manual setup) and groups everything taken
more than 20 miles from home into trips. A run of several consecutive days
away becomes a "Vacation"; a single day away becomes a "Day Trip", but only
if there are enough photos that day to be a real trip rather than a one-off
errand. Each trip gets a suggested name ("2026 Orlando, Florida") built from
an offline place-name lookup (no network call) - edit the name field and
click "Save Name" to use something more memorable, and it becomes that
trip's own subfolder (`Trips/<name>/` or `Day Trips/<name>/`) instead of the
usual year/month one when you organize. If a batch of photos from friends or
family living far away gets misidentified as a trip, click "Ignore This
Trip" - its photos fall back to the normal year/month folders, and the
dismissal sticks even if you re-run detection later.

Click **"Quit Photo Organizer"** (top of either page) when you're done -
this shuts down the background process cleanly - and so does just closing
the window with the X button, or any other normal way of closing it. There's
no separate "quit" step you have to remember.

Power users can still call `launch.bat <command>` for CLI-only commands
(`index`, `analyze`, `review`).

## Status

This project is under active development. Current state:

- [x] Phase 1: Indexer (EXIF, SHA-256, perceptual hash, Live Photo pairing)
- [x] Phase 2-3: Duplicate clustering (exact + near-duplicate/burst) + blur scoring
- [x] Phase 4: Local content tagging (CLIP - food/screenshot/document/meme/
      whiteboard/blank + person detection), fully self-contained
- [x] Phase 5: Review web UI (single/side-by-side/slider photo viewer)
- [x] Phase 6: Permanently emptying the review folder
- [x] Organize: move surviving photos into dated folders for long-term storage
- [x] Browse Photos Without a Person: month-by-month browse view with batch select
- [x] Trip detection: GPS/date-based vacation and day-trip grouping, with
      editable names and an "Ignore This Trip" dismissal
- [x] Video support: indexing (duration, representative-frame hash,
      screen-recording heuristic), exact/near-duplicate detection, a
      length-based review filter, and a "browse by session" view
- [x] Content search: free-text search over photos and videos using the same
      local CLIP model, with per-frame video sampling so a short relevant
      moment in a longer clip isn't missed
