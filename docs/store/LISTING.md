# Microsoft Store listing (draft)

Copy these into Partner Center. Words are written for someone who has never heard of the app.

## Name

Photo Organizer

## Short description (one line, under 100 characters)

Find duplicates, blurry shots and clutter in your phone photos. Private, on your PC.

## Description

Your phone photos pile up: bursts of near-identical shots, blurry ones, screenshots, receipts you
photographed once. Photo Organizer finds them so you can clear them out in minutes.

Point it at a folder, and it looks for:

- Exact duplicates and sets of near-identical photos, with a suggested best shot in each set
- Blurry and accidental photos
- Screenshots
- Similar videos

Then it helps you decide quickly. Press X to mark a photo to remove and K to keep it, or accept its
suggestions for a whole set at once. Nothing moves until you confirm, everything can be undone, and removed
photos wait in a review folder until you choose to delete them for good.

You can also:

- Search your photos by what is in them ("birthday cake", "beach")
- Browse by date, and see your trips on a timeline
- File photos into tidy year/month folders, with a preview first and an Undo afterwards

It works with photos from iPhone and Android, including HEIC, edited copies and Live Photos.

**Private by design.** Everything happens on your computer. Your photos are never uploaded, and the
Microsoft Store version makes no network requests. Photo Organizer is free, open-source software
(GNU General Public License, version 3).

## What's new in 2.0

A complete redesign built around your photos, with keyboard-first review, undo for everything, a much
more accurate blur and duplicate finder, search, and support for screen readers and keyboard-only use.

## Keywords (7 allowed)

photo organizer, duplicate photos, blurry photos, clean up photos, photo cleaner, screenshots, HEIC

## Category

Photo & video (choose "Utilities & tools" instead if no photo sub-category fits an organiser)

## System requirements

- Windows 10 version 1809 or later, 64-bit
- 8 GB of memory recommended
- About 1.2 GB of disk space, plus room for the preview cache
- Microsoft Edge (included with Windows)

## Notes for certification

- The app starts a local web server on 127.0.0.1 and shows its interface in a Microsoft Edge application
  window. It does not accept connections from other computers (it checks the Host and Origin of every
  request).
- Requires `runFullTrust` to read and move photos in folders chosen by the person anywhere on the PC.
- Makes no network requests. The recognition model is bundled in the package.
- Source code: <https://github.com/sleach198504/photo-organizer>

## Screenshots to capture (1366x768 or larger, at least 4)

1. Home: "what to do next" and the space that could be freed
2. Review: a set of similar photos with the suggested best shot
3. Photos: the library grid with the date scrubber, in dark mode
4. Search: results for a phrase such as "beach"
5. Organize: the preview of what will be filed where
6. Review in the light theme with the viewer open

Capture them from a library of non-personal photos (dev/make_demo_library.py builds one).

## Age rating answers

No violence, no sexual content, no user-generated content shared with others, no online interaction, no
purchases, no location sharing. (It reads GPS data already in a person's photos to name trips; nothing
leaves the computer.)

## Price

Free.
