// Label bookkeeping, kept free of the page so it can be tested on its own.
// Every function returns a new labels object and never edits the one it was given.

export const CATEGORIES = ["other", "food", "screenshot", "document", "meme", "whiteboard", "blank"];
export const BLUR = ["sharp", "soft", "unsure"];

export function emptyLabels() {
  return { version: 1, done: [], photos: {}, groups: [], queries: [] };
}

const copy = (labels) => structuredClone(labels);
const entry = (labels, pid) => (labels.photos[pid] ??= { cat: "other", blur: null });

/** Takes photos out of whatever group they are in; a group left with one photo is dissolved. */
function detach(labels, pids) {
  const gone = new Set(pids.map(String));
  labels.groups = labels.groups
    .map((g) => ({
      ...g,
      members: g.members.filter((m) => !gone.has(String(m))),
      best: g.best.filter((m) => !gone.has(String(m))),
    }))
    .filter((g) => g.members.length >= 2);
}

export function groupOf(labels, pid) {
  return labels.groups.find((g) => g.members.map(String).includes(String(pid))) ?? null;
}

function newGroupId(labels) {
  let n = labels.groups.length + 1;
  const used = new Set(labels.groups.map((g) => g.id));
  while (used.has(`g${n}`)) n += 1;
  return `g${n}`;
}

/** Puts the photos in one new group. Fewer than two photos does nothing. */
export function group(labels, pids) {
  const ids = [...new Set(pids.map(String))];
  if (ids.length < 2) return labels;
  const next = copy(labels);
  detach(next, ids);
  next.groups.push({ id: newGroupId(next), members: ids, best: [] });
  return next;
}

export function ungroup(labels, pids) {
  const next = copy(labels);
  detach(next, pids);
  return next;
}

/** Marks photos as acceptable keepers of their group. If all are already, clears them. */
export function toggleBest(labels, pids) {
  const next = copy(labels);
  const targets = pids.map(String).filter((p) => groupOf(next, p));
  if (!targets.length) return labels;
  const allBest = targets.every((p) => groupOf(next, p).best.map(String).includes(p));
  for (const p of targets) {
    const g = groupOf(next, p);
    g.best = g.best.map(String).filter((b) => b !== p);
    if (!allBest) g.best.push(p);
  }
  return next;
}

export function setCategory(labels, pids, cat) {
  if (!CATEGORIES.includes(cat)) return labels;
  const next = copy(labels);
  for (const p of pids) entry(next, String(p)).cat = cat;
  return next;
}

export function setBlur(labels, pids, blur) {
  if (!BLUR.includes(blur)) return labels;
  const next = copy(labels);
  for (const p of pids) entry(next, String(p)).blur = blur;
  return next;
}

/** Finishing a set accepts the defaults for anything you did not touch: sharp, and no category. */
export function finish(labels, clump) {
  const next = copy(labels);
  for (const p of clump.ids) {
    const e = entry(next, String(p));
    e.blur ??= "sharp";
  }
  if (!next.done.includes(clump.id)) next.done.push(clump.id);
  return next;
}

export function reopen(labels, clump) {
  const next = copy(labels);
  next.done = next.done.filter((id) => id !== clump.id);
  return next;
}

export function groupsMissingBest(labels) {
  return labels.groups.filter((g) => g.best.length === 0).length;
}

export function toggleRelevant(labels, queryIndex, pid) {
  const next = copy(labels);
  const q = next.queries[queryIndex];
  if (!q) return labels;
  const id = String(pid);
  q.relevant = q.relevant.map(String);
  q.relevant = q.relevant.includes(id) ? q.relevant.filter((r) => r !== id) : [...q.relevant, id];
  return next;
}

export function addQuery(labels, text) {
  const t = text.trim();
  if (!t || labels.queries.some((q) => q.text.toLowerCase() === t.toLowerCase())) return labels;
  const next = copy(labels);
  next.queries.push({ text: t, relevant: [] });
  return next;
}

export function removeQuery(labels, index) {
  const next = copy(labels);
  next.queries.splice(index, 1);
  return next;
}

export function letter(index) {
  let n = index, out = "";
  do {
    out = String.fromCharCode(65 + (n % 26)) + out;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return out;
}
