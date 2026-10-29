import test from "node:test";
import assert from "node:assert/strict";
import {
  emptyLabels, group, ungroup, toggleBest, setCategory, setBlur, finish, reopen,
  groupOf, groupsMissingBest, addQuery, toggleRelevant, letter,
} from "../../dev/evalkit/label_ui/state.js";

test("grouping needs two photos and never edits its input", () => {
  const start = emptyLabels();
  assert.equal(group(start, ["1"]), start);
  const grouped = group(start, ["1", "2", "3"]);
  assert.deepEqual(start.groups, []);
  assert.deepEqual(grouped.groups[0].members, ["1", "2", "3"]);
});

test("a photo can only be in one group; moving it dissolves a group left with one photo", () => {
  let labels = group(emptyLabels(), ["1", "2"]);
  labels = group(labels, ["2", "3"]);
  assert.equal(labels.groups.length, 1);
  assert.deepEqual(labels.groups[0].members, ["2", "3"]);
  assert.equal(groupOf(labels, "1"), null);
});

test("ungroup drops best marks along with the photo", () => {
  let labels = group(emptyLabels(), ["1", "2", "3"]);
  labels = toggleBest(labels, ["1", "2"]);
  labels = ungroup(labels, ["2"]);
  assert.deepEqual(labels.groups[0].members, ["1", "3"]);
  assert.deepEqual(labels.groups[0].best, ["1"]);
  labels = ungroup(labels, ["3"]);
  assert.deepEqual(labels.groups, []);
});

test("toggleBest sets then clears, and ignores ungrouped photos", () => {
  let labels = group(emptyLabels(), ["1", "2"]);
  assert.equal(toggleBest(labels, ["9"]), labels);
  labels = toggleBest(labels, ["1"]);
  assert.deepEqual(labels.groups[0].best, ["1"]);
  assert.equal(groupsMissingBest(labels), 0);
  labels = toggleBest(labels, ["1"]);
  assert.deepEqual(labels.groups[0].best, []);
  assert.equal(groupsMissingBest(labels), 1);
});

test("category and sharpness reject values the export would refuse", () => {
  const labels = emptyLabels();
  assert.equal(setCategory(labels, ["1"], "nonsense"), labels);
  assert.equal(setBlur(labels, ["1"], "maybe"), labels);
  assert.equal(setCategory(labels, ["1"], "food").photos["1"].cat, "food");
  assert.equal(setBlur(labels, ["1"], "soft").photos["1"].blur, "soft");
});

test("finishing accepts defaults for untouched photos and keeps explicit choices", () => {
  let labels = setBlur(emptyLabels(), ["2"], "soft");
  labels = finish(labels, { id: 7, ids: [1, 2] });
  assert.equal(labels.photos["1"].blur, "sharp");
  assert.equal(labels.photos["2"].blur, "soft");
  assert.deepEqual(labels.done, [7]);
  assert.deepEqual(finish(labels, { id: 7, ids: [1, 2] }).done, [7]);
  assert.deepEqual(reopen(labels, { id: 7, ids: [1, 2] }).done, []);
});

test("search queries are trimmed, de-duplicated and toggle relevance", () => {
  let labels = addQuery(emptyLabels(), "  birthday cake ");
  assert.equal(addQuery(labels, "Birthday Cake"), labels);
  assert.equal(addQuery(labels, "   "), labels);
  labels = toggleRelevant(labels, 0, 4);
  labels = toggleRelevant(labels, 0, 5);
  labels = toggleRelevant(labels, 0, 4);
  assert.deepEqual(labels.queries[0].relevant, ["5"]);
});

test("group letters run A..Z, AA..", () => {
  assert.deepEqual([0, 1, 25, 26, 27].map(letter), ["A", "B", "Z", "AA", "AB"]);
});
