# Accessibility

Goal: Photo Organizer works with a keyboard alone, with a screen reader, in Windows High Contrast, and at
larger text sizes, meeting WCAG 2.2 level AA. This records what was checked, what changed, and what has
**not** been checked.

## What was audited (2026-10-29)

Method: axe-core 4.10.2 (rules for WCAG 2.0, 2.1, 2.2 A and AA plus best practice) over every page in
light and dark themes, on a scratch library; then hands-on keyboard checks in the browser; then a check of
the dialogs and the photo viewer while open. `dev/a11y/sweep.js` repeats the automated part.

Starting point: six kinds of problem on 133 flagged elements (counted across both themes):

| Problem | Where | Fix |
| --- | --- | --- |
| Buttons nested inside a button-role cell, and unnamed select checks (72 + 50 elements) | every photo grid | Rebuilt the photo cell: a named group holding one real "open" button, with the select check and Keep/Remove buttons beside it, all named after the photo |
| Count badge too faint (4.35:1) | sidebar, review list | Solid accent badge; review counts one step darker |
| Year buttons too small (22 px) | Photos timeline | At least 24 px |
| Heading jumped from h1 to h3 | Trips | Trip names are h2 |
| Links in text told apart by colour alone (2.1:1) | notices, paragraphs | Underlined |

Found while checking by hand, then fixed:

- The arrow keys moved a drawn cursor but not real focus, so a screen reader never learned where you were.
  Now the cursor cell takes focus, and a grid is one Tab stop (Tab enters and leaves it; arrows move within).
  Previously each photo added three Tab stops.
- Space and Enter on a control (select check, Keep, Remove) were taken by the grid to open the photo.
- Marking a photo with `X`/`K` was silent. It is now announced ("IMG_1.jpg marked to remove"), as is
  stepping through photos in the viewer ("IMG_2.jpg, 2 of 40").
- Dialogs and the viewer did not make the rest of the app unreachable, and the viewer did not take focus or
  return it. All modal windows now take focus, keep Tab inside, hide the app behind them (`inert`) and put
  focus back on close.
- Moving to another page left focus on the link you pressed, and there was no skip link. There is now a
  "Skip to content" link, and a new page moves focus to its heading.
- Scan and Organize progress bars had no name or value for a screen reader.
- The horizontally scrolling set strips on Review could not be reached by keyboard.
- Windows High Contrast: marks rely on shape (a slash to remove, a ring to keep) as well as colour, and now
  use system colours when the system overrides ours.

Result after the changes: axe finds nothing on Home, Photos, Videos, Trips, Review (each category), Removed,
Organize, Settings, Search and Scan in both themes, in the open photo viewer, in the shortcuts dialog, and on
the first-run screen. The last fixes (review counts, set strips) were re-checked only on the pages they affect.
No page scrolls sideways at about 640 px wide.

## Not checked (be honest about these)

- **No real screen reader.** NVDA, JAWS and Narrator were not run. Names, roles and announcements were
  inspected in the page, not heard. Run Narrator (Win+Ctrl+Enter) through Review before calling this done.
- **High Contrast mode** rules were written to the spec but not seen in a real High Contrast theme.
- **200% and 400% zoom and text-spacing overrides** were only checked for sideways scrolling at 640 px.
- **Automated checks find roughly a third of real problems.** Focus order, wording and whether a task is
  understandable still need a person.
- **The review-category and timeline controls** use the app's own key handling; they were checked with
  axe and by hand in Review, not in every view.

## Rules for new interface

- A control is a real `button` or `a` with a name. Never put a button inside another control.
- A repeated group of photos is one Tab stop; arrows move inside it, and the arrowed-to item takes focus.
- Anything that changes only on screen (a mark, a count, a page change) is also said, with `announce()`.
- Modal windows use `useModal` (`js/ui/modal.js`).
- Meaning is never colour alone: pair it with a shape, text or an icon.
- Text 4.5:1 against its background (3:1 for large text and component edges), targets at least 24 px.
