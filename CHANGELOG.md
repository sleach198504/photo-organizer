# Changelog

## Unreleased

- **Safer.** The app now refuses requests that don't come from its own window, so a web page open in your browser can no longer talk to it.
- **Truer colours.** Thumbnails of iPhone and wide-gamut photos are converted to standard colour, so saturated shots no longer look washed out. Thumbnails are redrawn once after updating.
- **Repeatable installs.** Setup now installs the exact library versions the app was tested with.
- **Licence.** Photo Organizer is now released under the GNU General Public License, version 3, with a list of the components it uses.

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
