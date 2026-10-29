// Small accessibility helpers, kept free of the page so they can be tested on their own.

const MARK_WORDS = { remove: "marked to remove", keep: "marked to keep" };

/** The name a screen reader gives a photo cell: what it is, then what has been decided. */
export function thumbLabel(item, mark, keeper = false) {
  const parts = [item.kind === "video" ? `${item.name}, video` : item.name];
  if (keeper) parts.push("suggested keep");
  if (mark && MARK_WORDS[mark]) parts.push(MARK_WORDS[mark]);
  return parts.join(", ");
}

/**
 * True when it is fine for the grid to move focus to its keyboard cursor: nothing is
 * focused, or focus is already somewhere in the page content or a photo cell. False
 * while the person is in a field or a dialog, so a re-render can never steal their typing.
 */
export function mayTakeFocus(active) {
  if (!active || active === document.body || active === document.documentElement) return true;
  const tag = active.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || active.isContentEditable) return false;
  if (active.closest?.('[role="dialog"], dialog')) return false;
  return Boolean(active.closest?.(".thumb, .content, #content"));
}

/** Which cell of a grid holds the Tab stop: the cursor, or the first cell if there is no cursor yet. */
export function isTabStop(index, cursorIndex) {
  return cursorIndex == null ? index === 0 : index === cursorIndex;
}

/**
 * Move focus to the start of the current page: its heading if it has one, else the page
 * area itself. Headings and the page area are made focusable (-1) on demand so they are
 * never in the Tab order.
 */
export function focusPageStart(main) {
  const target = main?.querySelector("h1") ?? main;
  if (!target) return;
  if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
  target.focus({ preventScroll: true });
}

let region = null;

/**
 * Say something to screen-reader users without moving focus or showing anything. Used for
 * changes that otherwise only show on screen, such as a photo being marked. Setting the
 * text after a beat means the same message twice in a row is still read twice.
 */
export function announce(text) {
  if (!region) {
    region = document.createElement("div");
    region.className = "sr-only";
    region.setAttribute("role", "status");
    region.setAttribute("aria-live", "polite");
    document.body.append(region);
  }
  region.textContent = "";
  setTimeout(() => {
    region.textContent = text;
  }, 60);
}

/** "IMG_1.jpg marked to remove", "3 items marked to keep", "IMG_1.jpg mark cleared". */
export function markMessage(names, mark) {
  const subject = names.length === 1 ? names[0] : `${names.length} items`;
  if (mark === "remove") return `${subject} marked to remove`;
  if (mark === "keep") return `${subject} marked to keep`;
  return names.length === 1 ? `${subject} mark cleared` : `${subject} marks cleared`;
}

/**
 * Where Tab should go next inside a modal. Returns the element to focus when Tab would
 * otherwise leave the modal (past the last control, or before the first), or null when the
 * browser's normal behaviour is fine.
 */
export function wrapTab(focusables, active, shift) {
  if (!focusables.length) return null;
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  const index = focusables.indexOf(active);
  if (index === -1) return shift ? last : first; // focus has strayed outside: bring it back
  if (shift && active === first) return last;
  if (!shift && active === last) return first;
  return null;
}
