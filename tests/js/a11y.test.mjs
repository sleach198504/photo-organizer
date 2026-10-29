import test from "node:test";
import assert from "node:assert/strict";
import { thumbLabel, isTabStop, mayTakeFocus, markMessage, focusPageStart } from "../../app/web/static/js/lib/a11y.js";

const body = { tagName: "BODY" };
globalThis.document = { body, documentElement: { tagName: "HTML" } };

/** A stand-in element: `inside` lists the selectors its closest() should match. */
function el(tagName, inside = []) {
  return { tagName, isContentEditable: false, closest: (sel) => (inside.some((s) => sel.includes(s)) ? {} : null) };
}

test("a photo is named by its file, then what has been decided", () => {
  assert.equal(thumbLabel({ name: "IMG_1.jpg", kind: "photo" }, null), "IMG_1.jpg");
  assert.equal(thumbLabel({ name: "IMG_1.jpg", kind: "photo" }, "remove"), "IMG_1.jpg, marked to remove");
  assert.equal(thumbLabel({ name: "IMG_1.jpg", kind: "photo" }, "keep", true), "IMG_1.jpg, suggested keep, marked to keep");
  assert.equal(thumbLabel({ name: "MOV_2.mp4", kind: "video" }, null), "MOV_2.mp4, video");
});

test("only the cursor cell, or the first cell before there is a cursor, is a Tab stop", () => {
  assert.equal(isTabStop(0, null), true);
  assert.equal(isTabStop(3, null), false);
  assert.equal(isTabStop(3, 3), true);
  assert.equal(isTabStop(0, 3), false);
});

test("the grid may take focus from nothing, the page or a photo, but never from a field or dialog", () => {
  assert.equal(mayTakeFocus(null), true);
  assert.equal(mayTakeFocus(body), true);
  assert.equal(mayTakeFocus(el("BUTTON", [".thumb"])), true);
  assert.equal(mayTakeFocus(el("A", ["#content"])), true);
  assert.equal(mayTakeFocus(el("INPUT", [".content"])), false);
  assert.equal(mayTakeFocus(el("TEXTAREA")), false);
  assert.equal(mayTakeFocus(el("SELECT", [".content"])), false);
  assert.equal(mayTakeFocus({ ...el("BUTTON", [".content", '[role="dialog"]']) }), false);
  assert.equal(mayTakeFocus(el("BUTTON", [])), false, "somewhere outside the page content, such as the sidebar");
});

test("mark messages read naturally for one photo and for several", () => {
  assert.equal(markMessage(["a.jpg"], "remove"), "a.jpg marked to remove");
  assert.equal(markMessage(["a.jpg"], "keep"), "a.jpg marked to keep");
  assert.equal(markMessage(["a.jpg"], null), "a.jpg mark cleared");
  assert.equal(markMessage(["a", "b", "c"], "remove"), "3 items marked to remove");
  assert.equal(markMessage(["a", "b"], null), "2 items marks cleared");
});

test("moving to a new page focuses its heading, or the page area, and never leaves it in the Tab order", () => {
  const calls = [];
  const make = (name) => ({
    attrs: {}, name,
    hasAttribute(k) { return k in this.attrs; },
    setAttribute(k, v) { this.attrs[k] = v; },
    focus(opts) { calls.push([name, opts]); },
  });
  const heading = make("h1");
  const main = { ...make("main"), querySelector: (s) => (s === "h1" ? heading : null) };
  focusPageStart(main);
  assert.deepEqual(calls, [["h1", { preventScroll: true }]]);
  assert.equal(heading.attrs.tabindex, "-1");

  calls.length = 0;
  const bare = { ...make("main"), querySelector: () => null };
  focusPageStart(bare);
  assert.equal(calls[0][0], "main");
  focusPageStart(null);
  assert.equal(calls.length, 1);
});

import { wrapTab } from "../../app/web/static/js/lib/a11y.js";

test("Tab wraps inside a modal at both ends and otherwise does nothing", () => {
  const [a, b, c] = ["a", "b", "c"];
  assert.equal(wrapTab([a, b, c], c, false), a);
  assert.equal(wrapTab([a, b, c], a, true), c);
  assert.equal(wrapTab([a, b, c], b, false), null);
  assert.equal(wrapTab([a, b, c], b, true), null);
  assert.equal(wrapTab([a, b, c], "outside", false), a);
  assert.equal(wrapTab([a, b, c], "outside", true), c);
  assert.equal(wrapTab([], a, false), null);
});
