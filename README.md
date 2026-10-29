# Photo Organizer

Find the photos worth keeping. Photo Organizer reads a large dump of iPhone photos and
videos, then lines up the duplicates, near-identical bursts, blurry shots, screenshots and
clutter so you can clear hundreds in minutes instead of scrolling through them by hand.

It runs entirely on your PC. Nothing is uploaded, nothing is deleted unless you say so, and
every removal can be undone.

## What it does

- **Finds clutter.** Exact duplicates, bursts and retakes (for photos and for videos), blurry
  photos, screenshots, photos of documents and receipts, whiteboards, food, memes and saved
  images, blank or accidental shots, long videos and screen recordings.
- **Makes decisions fast.** Mark photos to keep or remove with one key press. Nothing moves
  until you apply your decisions, and then it's a single step you can undo.
- **Explains its suggestions.** Every similar-photos set shows which shot it would keep and
  why ("Sharpest of the set", "Highest resolution"), and you can compare two shots side by
  side or at 100%.
- **Searches by meaning.** Type "birthday cake" or "dog in the snow" and find it, including
  the moment inside a video where it happens.
- **Finds your trips.** Uses the location saved in your photos to spot vacations and day
  trips, and gives each its own named folder.
- **Organizes what's left.** Files everything you kept into dated folders, with a preview
  that shows exactly what will happen first.

## Privacy

Nothing here ever leaves your PC.

- Scanning, hashing and scoring run locally on the files on disk.
- Recognition uses [CLIP](https://huggingface.co/openai/clip-vit-base-patch32), an open-source
  image model (about 580 MB) downloaded once by Setup into the app's own `models` folder. After
  that it is loaded with `local_files_only=True`, so recognition and search cannot make a
  network call, by construction.
- Place names for trips come from a bundled offline city database. No mapping service is used.
- The app is a local web server bound to `127.0.0.1` only. It isn't reachable from your
  network, and it shows up in a plain window with no address bar.
- The only time the app goes online is when you press **Check for updates** in Settings.
- Removing a photo only moves it to a review folder. Permanent deletion is a separate step
  that requires you to type `DELETE`, and it only ever deletes files inside that review folder.

## Install

1. Download `Install.bat` from the latest [release](https://github.com/sleach198504/photo-organizer/releases)
   and double-click it, or double-click `Setup.bat` in a downloaded copy of this folder.
2. A setup window explains what will be installed. Click **Confirm**. Setup installs Python
   if the PC doesn't have it, then the app and the recognition model. An NVIDIA GPU is optional:
   if one is found you can choose a faster GPU install.
3. Setup puts Photo Organizer in `%LocalAppData%\Programs\Photo Organizer` and adds shortcuts
   to your **Desktop** and **Start menu**. It also registers a normal uninstall entry in
   Windows Settings > Apps.

## Using it

Open Photo Organizer from its shortcut. The first time, choose the folder your photos are in
and click **Scan my photos**. A scan reads every file, checks sharpness, finds duplicates and
runs recognition. Later scans only look at new and changed files.

| Section | What it's for |
| --- | --- |
| **Home** | What to do next, what was found and how much space it could free |
| **Photos / Videos / Trips** | Browse your whole library. Photos has filters, sorting and a date scrubber; Videos groups clips by outing; Trips names your trips |
| **Review** | Go through what the scan flagged, one reason at a time |
| **Removed** | Photos you've removed. Restore them, or delete them for good |
| **Organize** | File what's left into dated folders |

### Reviewing

Flagged items come in two shapes. *Sets* (duplicates and similar shots) show the suggested
keeper first with the others beside it; **Keep suggested** decides a whole set at once and
**Accept all suggestions** decides the whole category. Other categories (blurry, screenshots,
documents...) are a grid you can mark one at a time or all at once.

A red slash on a photo means *remove*; a green outline means *keep*. Marks are drawn on the
photo itself and only change what's on disk when you click **Move to Removed** in the bar that
appears at the bottom of the window. You'll get an **Undo** right after.

| Key | Does |
| --- | --- |
| Arrow keys | Move between photos |
| `X` / `K` / `U` | Mark to remove / keep / clear the mark |
| `Space` or `Enter` | Open larger (then `←` `→` to step through, `Z` for 100%, `I` for details, `C` to compare with the keeper) |
| `Shift` + click | Select a range |
| `/` | Search |
| `?` | Show every shortcut |
| `G` then `H` `R` `P` `V` `T` `O` | Jump to Home, Review, Photos, Videos, Trips, Organize |

### Settings

Folders, how alike two photos must be to count as similar (Strict, Balanced or Loose), whether
exact duplicates move automatically during a scan, which videos to flag, search detail, and
the theme (match Windows, dark or light).

## Where things are stored

| What | Where |
| --- | --- |
| The app | `%LocalAppData%\Programs\Photo Organizer` |
| Settings | `config.yaml` in that folder (safe to hand-edit) |
| Library index and thumbnail cache | `data` in that folder |
| Log | `data\photo-organizer.log` |
| Removed photos | The review folder you chose (`Image Review` inside your photos folder by default) |

Closing the window shuts the app down within a few minutes, and **Exit** in the sidebar
does it immediately. Uninstalling removes the app, the index and the shortcuts, and never touches
your photos.

## Updating

Run `Install.bat` again, or press **Check for updates** in Settings to see whether a newer
release exists. Your settings and index are kept.

## For developers

The backend is FastAPI (`app/web`) serving a JSON API plus the single-page UI in
`app/web/static`. The UI is Preact, htm and signals loaded as native ES modules, so there is
no build step; the small set of third-party files it uses is committed and reproducible.

```
app/            Python package: indexing, scoring, duplicates, recognition, jobs, API
app/web/static  The UI: css/, js/lib (state, router, formatting), js/ui (components), js/views
dev/            Developer tools: demo and stress libraries, icon and vendor builders, contrast check
tests/          unittest suite (Python) and node:test files (JavaScript)
docs/           Design notes (OVERHAUL.md) and the pre-implementation research (RESEARCH.md)
```

Run the tests (they use a throwaway home folder and never touch real data):

```
venv\Scripts\python.exe -m unittest discover -s tests -t . -v
node --test "tests/js/*.test.mjs"
node dev/contrast.mjs
node dev/unused_imports.mjs
venv\Scripts\python.exe dev\unused_imports.py app tests dev
```

Try the UI against a synthetic library:

```
set PHOTO_ORGANIZER_HOME=C:\scratch\home
venv\Scripts\python.exe dev\make_demo_library.py C:\scratch\demo_lib
venv\Scripts\python.exe dev\run_scan_cli.py C:\scratch\demo_lib
venv\Scripts\python.exe -m uvicorn app.web.app:create_app --factory --port 8766
```

`dev/stress_library.py 20000` builds a large library and times the API over it. To refresh the
bundled UI libraries, fonts and icons run `npm install && node build.mjs` in `dev/vendor`;
`dev/make_icons.py` redraws the app icon.

Measure the engine against a dataset with known answers (see `docs/EVALUATION.md`):

```
venv\Scripts\python.exe -m dev.evalkit synth C:\scratch\ds --size small
venv\Scripts\python.exe -m dev.evalkit run C:\scratch\ds
```

To label a set of your own photos for realistic scores (`prepare`, `label`, `export`), see that document.

`launch.bat` with no arguments opens the app. With arguments it runs a command-line tool
(`index`, `analyze`, `review`).

Bundled third-party assets keep their licenses next to them: Preact and signals (MIT), htm
(Apache-2.0), Lucide icons (ISC) and the Figtree font (SIL Open Font License).

## Licence

Photo Organizer is free software, released under the GNU General Public License, version 3
(see `LICENSE`). You can use, study, change and share it under those terms. The open-source
components it is built on are listed in `THIRD_PARTY_NOTICES.md`.
