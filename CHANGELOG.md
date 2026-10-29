# Changelog

## Unreleased

- **Safer.** The app now refuses requests that don't come from its own window, so a web page open in your browser can no longer talk to it.
- **Truer colours.** Thumbnails of iPhone and wide-gamut photos are converted to standard colour, so saturated shots no longer look washed out. Thumbnails are redrawn once after updating.
- **Repeatable installs.** Setup now installs the exact library versions the app was tested with.
- **Licence.** Photo Organizer is now released under the GNU General Public License, version 3, with a list of the components it uses.
- **Undo for Organize.** The last time you filed photos can now be undone from the Organize page: everything goes back to the folder it came from, and the dated folders that were created are removed if they end up empty. Photos you have moved or deleted since are left alone.
- **Fewer failed moves.** If another program is reading a photo at the moment it is moved, the app now waits a moment and retries instead of failing.
- **Smarter blur detection.** A portrait with a sharp subject and a soft background is no longer called blurry, and plain skies and walls are no longer flagged. Photos are scored again once on the next scan.
- **Better pick of which photo to keep.** A sharp, smaller copy now beats a soft, larger one. Between equally sharp shots, the bigger one is still chosen.
- **Fewer wrong matches.** Long chains of look-alike photos are cut into sets of genuinely similar ones, and plain skies and walls are no longer grouped together.
- **Fewer false screenshots.** A photo saved as a PNG is only called a screenshot if it is the shape of a screen.
- **iPhone edited copies.** An iPhone edit (`IMG_E1234`) is now grouped with its original (`IMG_1234`) even when the edit changed the picture too much to look alike, and the edited version is the one suggested to keep.
- **iPhone edit files travel with their photo.** The small `.AAE` file that holds an iPhone's edit instructions is now moved, restored, filed, put back and deleted together with its photo, instead of being left behind.
- **No surprise OneDrive downloads.** Photos and videos that are stored online only are now left out of a scan instead of being downloaded to read them, and the scan result says how many were skipped and how to include them.

## 2.0.0

A ground-up redesign of the whole app. Your existing library, settings and decisions carry over;
after updating, scan once more so older photos gain capture dates.

### New look and feel

- A new interface built around the photos themselves: neutral surfaces, dark or light (follows
  Windows by default), a bundled typeface and icon set, and an app icon.
- Sidebar navigation: **Home**, **Photos**, **Videos**, **Trips**, **Review**, **Removed**,
  **Organize**, with live counts.
- **Home** tells you what to do next and shows what was found and how much space it could free.
- A guided first-run screen, and a scan screen with real progress for every step, time remaining
  and a Stop button.

### Faster decisions

- **Mark first, apply once.** Press `X` to mark a photo to remove and `K` to keep it. A red slash or
  green outline is drawn on the photo. Nothing moves until you click **Move to Removed**, and an
  **Undo** appears straight away.
- **Keyboard culling** with arrow keys, plus shift-click ranges, select-all for a category and
  one-click **Accept all suggestions** for duplicate sets.
- Each similar-photos set says why a keeper was chosen, and the viewer can compare two shots side
  by side, in sync, at 100%.
- A full-window viewer with zoom, details, video playback and next/previous.
- Everything that can be undone has an Undo. Only permanent deletion asks you to confirm, by typing
  `DELETE`.

### Library

- **Photos** with filters, sorting, three thumbnail sizes and a year/month scrubber that stays fast
  with tens of thousands of photos.
- **Videos** grouped by when you filmed them. **Trips** you can rename or dismiss.
- **Search** by what's in a photo or video, from the search box or `/`.
- **Organize** with a live preview of exactly what will be filed where, before anything moves.

### Under the hood

- Capture dates are now read correctly from iPhone photos (they were being missed), and from videos.
- Thumbnails are cached on disk, so reopening a big library is instant.
- Recognition is several times faster thanks to batching.
- Scans can be stopped at any point and resume where they left off.
- Reopening the app while it's already running brings up the existing window instead of a second copy.
- A Start menu shortcut is added alongside the Desktop one.
- Tests: an end-to-end suite that drives scan, review, apply, restore, delete and organize, plus
  metadata, organizing and formatting tests.
