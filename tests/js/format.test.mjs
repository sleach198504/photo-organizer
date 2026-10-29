// Pure formatting helpers used all over the UI. Run with: node --test tests/js
import test from "node:test";
import assert from "node:assert/strict";
import {
  bytes, count, plural, duration, eta, monthLabel, dateRange, dateShort, baseName, megapixels,
} from "../../app/web/static/js/lib/format.js";

test("bytes uses decimal units with sensible precision", () => {
  assert.equal(bytes(0), "0 B");
  assert.equal(bytes(999), "999 B");
  assert.equal(bytes(1500), "1.50 KB");
  assert.equal(bytes(12_300_000), "12.3 MB");
  assert.equal(bytes(2_590_000_000), "2.59 GB");
  assert.equal(bytes(null), "");
});

test("count and plural", () => {
  assert.equal(count(1234567), "1,234,567");
  assert.equal(plural(1, "photo"), "1 photo");
  assert.equal(plural(2, "photo"), "2 photos");
  assert.equal(plural(1, "copy", "copies"), "1 copy");
  assert.equal(plural(3, "copy", "copies"), "3 copies");
});

test("duration formats clips and hours", () => {
  assert.equal(duration(65), "1:05");
  assert.equal(duration(3725), "1:02:05");
  assert.equal(duration(null), "");
});

test("eta rounds the way a person would say it", () => {
  assert.equal(eta(20), "under a minute left");
  assert.equal(eta(150), "about 3 minutes left");
  assert.equal(eta(60), "about 1 minute left");
  assert.equal(eta(5400), "about 1.5 hours left");
});

test("dates are calendar days, not shifted by the time zone", () => {
  // "2025-06-21" parsed as UTC would read as June 20 in the Americas.
  assert.equal(dateShort("2025-06-21"), "Jun 21, 2025");
  assert.equal(dateRange("2025-03-09", "2025-03-13"), "Mar 9 – 13, 2025");
  assert.equal(dateRange("2024-12-28", "2025-01-03"), "Dec 28, 2024 – Jan 3, 2025");
  assert.equal(dateRange("2025-06-21", "2025-06-21"), "Jun 21, 2025");
});

test("month labels", () => {
  assert.equal(monthLabel("2025-03"), "March 2025");
  assert.equal(monthLabel(""), "Undated");
});

test("small helpers", () => {
  assert.equal(baseName("C:\\Photos\\Trips\\IMG_1.jpg"), "IMG_1.jpg");
  assert.equal(megapixels(4000, 3000), "12.0 MP");
  assert.equal(megapixels(null, null), "");
});
