// App-wide state. Server data lives here as signals so any component that reads
// `summary.value` re-renders when it changes; views fetch their own lists.
import { batch, signal, computed } from "./html.js";
import { api } from "./api.js";
import { plural, bytes } from "./format.js";
import { toast } from "../ui/toast.js";
import { route, go } from "./router.js";

export const summary = signal(null);
export const settings = signal(null);
export const system = signal(null);
export const booted = signal(false);
export const bootError = signal(null);

// Jobs: latest server snapshot per task. `idle` until something runs.
export const jobs = { scan: signal(null), apply: signal(null), organize: signal(null), undo_organize: signal(null) };

export const anyJobRunning = computed(() => Object.values(jobs).some((j) => j.value?.state === "running"));

// Marks pending application: totals from the server, plus a local overlay so a click
// shows instantly (the PUT confirms it a moment later).
export const marks = signal({ remove: 0, keep: 0, remove_bytes: 0 });
export const markOverlay = signal(new Map());
// Bumped whenever marks change in bulk or apply finishes, so open lists refetch.
export const dataVersion = signal(0);

export function markOf(item) {
  const overlay = markOverlay.value;
  return overlay.has(item.id) ? overlay.get(item.id) : item.mark;
}

// ---- loading ---------------------------------------------------------------

export async function refreshSummary() {
  const s = await api.get("/api/summary");
  batch(() => {
    summary.value = s;
    marks.value = s.marks;
  });
  return s;
}

export async function refreshSettings() {
  settings.value = await api.get("/api/settings");
  return settings.value;
}

export async function boot() {
  try {
    const [, , sys] = await Promise.all([refreshSettings(), refreshSummary(), api.get("/api/system")]);
    system.value = sys;
    await Promise.all(Object.keys(jobs).map((name) => pollJob(name, { once: true })));
    for (const [name, sig] of Object.entries(jobs)) {
      if (sig.value?.state === "running") watchJob(name);
    }
    bootError.value = null;
  } catch (error) {
    bootError.value = error.message;
  } finally {
    booted.value = true;
  }
}

// ---- jobs --------------------------------------------------------------------

const watchers = new Set();

async function pollJob(name, { once = false } = {}) {
  const snapshot = await api.get(`/api/jobs/${name}`);
  jobs[name].value = snapshot;
  return snapshot;
}

/** Poll a job until it stops, then refresh everything it may have changed. */
export function watchJob(name) {
  if (watchers.has(name)) return;
  watchers.add(name);
  const tick = async () => {
    let snapshot;
    try {
      snapshot = await pollJob(name);
    } catch {
      setTimeout(tick, 2000);
      return;
    }
    if (snapshot.state === "running") {
      setTimeout(tick, 600);
      return;
    }
    watchers.delete(name);
    await jobFinished(name, snapshot);
  };
  tick();
}

async function jobFinished(name, snapshot) {
  markOverlay.value = new Map();
  dataVersion.value += 1;
  try {
    await Promise.all([refreshSummary(), refreshSettings()]);
  } catch {
    /* the next navigation will retry */
  }
  if (name === "scan" && snapshot.state === "done" && route.value.path !== "/scan") {
    const flagged = snapshot.summary?.flagged ?? 0;
    toast(flagged ? `Scan complete. ${plural(flagged, "item")} to review.` : "Scan complete. Nothing needs review.", {
      kind: "success",
      action: flagged ? { label: "Review", run: () => go("/review") } : null,
      timeout: 10000,
    });
  }
  if (name === "undo_organize" && snapshot.state === "done") {
    const r = snapshot.summary ?? {};
    toast(`Put ${plural(r.restored ?? 0, "item")} back where ${r.restored === 1 ? "it was" : "they were"}`, { kind: "success" });
  }
  if (name === "apply" && snapshot.state === "done") {
    const r = snapshot.summary ?? {};
    toast(
      `Moved ${plural(r.moved ?? 0, "item")} to Removed${r.moved_bytes ? ` (${bytes(r.moved_bytes)})` : ""}`,
      {
        kind: "success",
        action: r.moved_ids?.length ? { label: "Undo", run: () => undoApply(r.moved_ids) } : null,
        timeout: 12000,
      }
    );
    if (r.failed) toast(`${plural(r.failed, "item")} couldn't be moved. They're still in your library.`, { kind: "error" });
  }
}

export async function undoApply(ids) {
  try {
    const r = await api.post("/api/removed/restore", { ids });
    toast(`Restored ${plural(r.restored, "item")} to your library`, { kind: "success" });
    dataVersion.value += 1;
    await refreshSummary();
  } catch (error) {
    toast(error.message, { kind: "error" });
  }
}

export async function startJob(name, url, body = {}) {
  await api.post(url, body);
  jobs[name].value = { ...(jobs[name].value ?? {}), state: "running", stages: jobs[name].value?.stages ?? [], elapsed: 0 };
  watchJob(name);
}

export async function cancelJob(name) {
  await api.post(`/api/jobs/${name}/cancel`);
  jobs[name].value = { ...jobs[name].value, cancelling: true };
}

// ---- marks ---------------------------------------------------------------------

let summaryTimer = 0;
// Category counts on Home/Review shift as marks change; refresh them, but not per click.
function refreshSummarySoon() {
  clearTimeout(summaryTimer);
  summaryTimer = setTimeout(() => refreshSummary().catch(() => {}), 700);
}

function overlay(ids, valueOf) {
  const next = new Map(markOverlay.value);
  for (const id of ids) next.set(id, valueOf(id));
  markOverlay.value = next;
}

/**
 * Mark photos remove / keep / clear. `changes` is [{ ids, mark }]. The grid updates
 * instantly (optimistic overlay); the server answers with each photo's previous mark, which
 * is what makes Undo exact - even for "mark all 800 blurry photos".
 */
export async function setMarksMulti(changes, { label, undoable = true } = {}) {
  const all = changes.flatMap((c) => c.ids);
  if (!all.length) return;
  const wanted = new Map();
  for (const c of changes) for (const id of c.ids) wanted.set(id, c.mark);
  const before = new Map(markOverlay.value);
  overlay(all, (id) => wanted.get(id));

  const previous = new Map();
  try {
    for (const c of changes) {
      const result = await api.put("/api/marks", { ids: c.ids, mark: c.mark });
      marks.value = { remove: result.remove, keep: result.keep, remove_bytes: result.remove_bytes };
      for (const [id, mark] of Object.entries(result.previous)) previous.set(Number(id), mark);
    }
  } catch (error) {
    markOverlay.value = before;
    toast(error.message, { kind: "error" });
    return;
  }
  refreshSummarySoon();
  if (undoable) {
    toast(label ?? `Updated ${plural(all.length, "item")}`, { action: { label: "Undo", run: () => undoMarks(previous) } });
  }
}

async function undoMarks(previous) {
  const groups = new Map();
  for (const [id, mark] of previous) {
    const key = mark ?? "";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(id);
  }
  overlay(previous.keys(), (id) => previous.get(id) ?? null);
  try {
    for (const [key, ids] of groups) {
      const result = await api.put("/api/marks", { ids, mark: key || null });
      marks.value = { remove: result.remove, keep: result.keep, remove_bytes: result.remove_bytes };
    }
    refreshSummarySoon();
  } catch (error) {
    toast(error.message, { kind: "error" });
  }
}

/** Single-photo convenience: toggles off if the photo already has that mark. */
export function setMarks(items, mark, { undoable = items.length > 1 } = {}) {
  const verb = mark === "remove" ? "to remove" : mark === "keep" ? "to keep" : "cleared";
  return setMarksMulti([{ ids: items.map((i) => i.id), mark }], {
    undoable,
    label: mark ? `Marked ${plural(items.length, "item")} ${verb}` : `Cleared ${plural(items.length, "mark")}`,
  });
}

export async function suggestMarks(kinds) {
  const result = await api.post("/api/marks/suggest", { kinds });
  marks.value = { remove: result.remove, keep: result.keep, remove_bytes: result.remove_bytes };
  const next = new Map(markOverlay.value);
  for (const id of result.remove_ids) next.set(id, "remove");
  for (const id of result.keep_ids) next.set(id, "keep");
  markOverlay.value = next;
  refreshSummarySoon();
  const ids = [...result.remove_ids, ...result.keep_ids];
  toast(
    result.remove_ids.length
      ? `Marked ${plural(result.remove_ids.length, "item")} to remove and kept the best of each set`
      : "Everything here was already decided",
    { kind: "success", action: ids.length ? { label: "Undo", run: () => setMarksMulti([{ ids, mark: null }], { undoable: false }) } : null }
  );
  return result;
}

export async function clearAllMarks() {
  marks.value = await api.post("/api/marks/clear");
  markOverlay.value = new Map();
  dataVersion.value += 1;
  refreshSummarySoon();
}

export async function applyMarks() {
  await startJob("apply", "/api/marks/apply");
}
