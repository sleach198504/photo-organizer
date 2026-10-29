import * as S from "/ui/state.js";

const $ = (id) => document.getElementById(id);

const CATEGORY_LABELS = {
  other: "Ordinary photo", food: "Food", screenshot: "Screenshot", document: "Document or receipt",
  meme: "Meme or saved image", whiteboard: "Whiteboard or notes", blank: "Blank or accidental",
};
const BLUR_CHOICES = [["sharp", "S", "Sharp"], ["soft", "E", "Blurry"], ["unsure", "N", "Borderline"]];
const KIND_HINTS = {
  "candidate-set": "These might be the same moment. Select the ones that are and group them, then mark every photo you would be happy to keep.",
  "soft-focus-candidate": "Check each photo for sharpness at 100% (Z). Mark the ones that are blurry or borderline.",
  random: "Ordinary photos. Mark anything that is a screenshot, document, food, a meme, a whiteboard or a blank shot, and anything blurry. If two of them show the same moment, group them.",
};

let project, labels, undoStack = [], saveTimer = null;
const view = { tab: "sets", clump: 0, focus: 0, query: 0 };
let selected = new Set();
let zoom = null; // { pid, full }

// ---------------------------------------------------------------- data

async function load() {
  const res = await fetch("/api/project");
  const data = await res.json();
  project = data.project;
  labels = data.labels;
  $("project-name").textContent = project.name;
  const firstOpen = project.clumps.findIndex((c) => !labels.done.includes(c.id));
  view.clump = Math.max(0, firstOpen);
  render();
}

const clump = () => project.clumps[view.clump];
const ids = () => clump().ids.map(String);
const photo = (pid) => project.photos[pid];
const entry = (pid) => labels.photos[pid] ?? { cat: "other", blur: null };
const isDone = (c = clump()) => labels.done.includes(c.id);
const targets = () => (selected.size ? [...selected] : [ids()[view.focus]]).filter(Boolean);

function commit(next) {
  if (next === labels) return;
  undoStack.push(labels);
  if (undoStack.length > 80) undoStack.shift();
  labels = next;
  scheduleSave();
  render();
}

function undo() {
  if (!undoStack.length) return;
  labels = undoStack.pop();
  scheduleSave();
  render();
}

function scheduleSave() {
  setSave("Saving…");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flushSave, 300);
}

async function flushSave() {
  clearTimeout(saveTimer);
  saveTimer = null;
  try {
    const res = await fetch("/api/labels", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(labels),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    setSave("Saved");
  } catch (err) {
    setSave("Not saved", true);
    toast(`${err.message}. Your last change is still on screen; try it again.`);
  }
}

function setSave(text, bad = false) {
  const el = $("save-state");
  el.textContent = text;
  el.classList.toggle("bad", bad);
}

let toastTimer;
function toast(text) {
  const el = $("toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 5000);
}

// ---------------------------------------------------------------- rendering

function render() {
  renderHeader();
  const sets = view.tab === "sets";
  $("sets-view").hidden = !sets;
  $("search-view").hidden = sets;
  $("tab-sets").setAttribute("aria-selected", String(sets));
  $("tab-search").setAttribute("aria-selected", String(!sets));
  $("undo").disabled = !undoStack.length;
  if (sets) renderSets();
  else renderSearch();
}

function renderHeader() {
  const done = new Set(labels.done);
  const total = project.clumps.reduce((n, c) => n + c.ids.length, 0);
  const finished = project.clumps.filter((c) => done.has(c.id)).reduce((n, c) => n + c.ids.length, 0);
  $("progress-text").textContent = `${finished} of ${total} photos finished · ${done.size} of ${project.clumps.length} sets`;
  $("bar-fill").style.width = `${total ? (100 * finished) / total : 0}%`;
  $("bar").setAttribute("aria-valuenow", String(Math.round(total ? (100 * finished) / total : 0)));
}

function groupColour(g) {
  const i = labels.groups.indexOf(g);
  return `hsl(${(i * 47) % 360} 62% 64%)`;
}

function makeChip(text, cls) {
  const span = document.createElement("span");
  span.className = `chip ${cls}`;
  span.textContent = text;
  return span;
}

function tile(pid, { small = false, onClick }) {
  const p = photo(pid);
  const e = entry(pid);
  const g = S.groupOf(labels, pid);
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "tile" + (small ? " small" : "");
  btn.dataset.pid = pid;
  btn.setAttribute("aria-label", p.rel);
  btn.title = p.rel;

  const img = document.createElement("img");
  img.alt = "";
  img.loading = "lazy";
  img.src = `/img/${pid}?size=thumb`;
  img.onerror = () => {
    img.replaceWith(Object.assign(document.createElement("div"), { className: "broken", textContent: "Could not open this file" }));
  };
  btn.append(img);

  if (!small) {
    const top = document.createElement("div");
    top.className = "badges";
    const left = document.createElement("span");
    const right = document.createElement("span");
    if (g) {
      btn.classList.add("grouped");
      btn.style.setProperty("--group", groupColour(g));
      const c = makeChip(S.letter(labels.groups.indexOf(g)), "group");
      c.style.setProperty("--group", groupColour(g));
      left.append(c);
      if (g.best.map(String).includes(pid)) right.append(makeChip("Fine to keep", "best"));
    }
    top.append(left, right);
    const foot = document.createElement("div");
    foot.className = "foot";
    if (e.cat !== "other") foot.append(makeChip(CATEGORY_LABELS[e.cat], "cat"));
    if (e.blur === "soft") foot.append(makeChip("Blurry", "soft"));
    else if (e.blur === "unsure") foot.append(makeChip("Borderline", "unsure"));
    else if (e.blur === "sharp") foot.append(makeChip("Sharp", ""));
    btn.append(top, foot);
  }
  btn.addEventListener("click", (ev) => onClick(pid, ev));
  return btn;
}

function renderSets() {
  const c = clump();
  const list = ids();
  view.focus = Math.min(view.focus, list.length - 1);
  $("set-title").textContent = `Set ${view.clump + 1} of ${project.clumps.length}${isDone() ? " · finished" : ""}`;
  $("set-hint").textContent = KIND_HINTS[c.kind] ?? "";
  $("prev-set").disabled = view.clump === 0;
  $("next-set").disabled = view.clump === project.clumps.length - 1;

  const grid = $("grid");
  grid.replaceChildren(...list.map((pid, i) => {
    const t = tile(pid, { onClick: (id, ev) => clickTile(id, i, ev) });
    if (i === view.focus) t.classList.add("focus");
    if (selected.has(pid)) t.classList.add("selected");
    return t;
  }));

  renderPanel();
}

function renderPanel() {
  const pids = targets();
  const first = pids[0];
  $("photo-info").textContent = first
    ? `${photo(first).rel}${photo(first).taken ? ` · ${photo(first).taken.slice(0, 16).replace("T", " ")}` : ""}` +
      `${photo(first).w ? ` · ${photo(first).w}×${photo(first).h}` : ""}` +
      (pids.length > 1 ? ` (and ${pids.length - 1} more selected)` : "")
    : "Nothing selected.";

  const cats = new Set(pids.map((p) => entry(p).cat));
  $("category-buttons").replaceChildren(...S.CATEGORIES.map((cat, i) => {
    const b = button(`${i}`, CATEGORY_LABELS[cat], () => commit(S.setCategory(labels, targets(), cat)));
    b.setAttribute("aria-pressed", String(cats.size === 1 && cats.has(cat)));
    return b;
  }));
  const blurs = new Set(pids.map((p) => entry(p).blur));
  $("blur-buttons").replaceChildren(...BLUR_CHOICES.map(([value, key, label]) => {
    const b = button(key, label, () => commit(S.setBlur(labels, targets(), value)));
    b.setAttribute("aria-pressed", String(blurs.size === 1 && blurs.has(value)));
    return b;
  }));

  const missing = S.groupsMissingBest(labels);
  const warning = $("group-warning");
  warning.hidden = !missing;
  warning.textContent = `${missing} group${missing === 1 ? " has" : "s have"} no photo marked fine to keep.`;
  $("finish-btn").lastChild.textContent = isDone() ? " Go to the next set" : " Finish this set";
}

function button(key, label, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "btn";
  const k = document.createElement("kbd");
  k.textContent = key;
  b.append(k, document.createTextNode(label));
  b.addEventListener("click", () => { onClick(); });
  return b;
}

// ---------------------------------------------------------------- search tab

function renderSearch() {
  const done = new Set(labels.done);
  const pool = project.clumps.filter((c) => done.has(c.id)).flatMap((c) => c.ids.map(String));
  const q = labels.queries[view.query];
  $("query-title").textContent = q ? `Which photos match "${q.text}"?` : "Search terms";
  const relevant = new Set((q?.relevant ?? []).map(String));
  $("relevant-grid").replaceChildren(...pool.map((pid) => {
    const t = tile(pid, { small: true, onClick: (id) => q && commit(S.toggleRelevant(labels, view.query, id)) });
    t.classList.toggle("relevant", relevant.has(pid));
    return t;
  }));
  $("query-list").replaceChildren(...labels.queries.map((query, i) => {
    const li = document.createElement("li");
    const pick = document.createElement("button");
    pick.type = "button";
    pick.className = "pick";
    pick.setAttribute("aria-pressed", String(i === view.query));
    pick.append(query.text);
    const count = document.createElement("span");
    count.className = "count";
    count.textContent = `${query.relevant.length} match${query.relevant.length === 1 ? "" : "es"}`;
    pick.append(count);
    pick.addEventListener("click", () => { view.query = i; render(); });
    const x = document.createElement("button");
    x.type = "button";
    x.className = "x";
    x.setAttribute("aria-label", `Remove ${query.text}`);
    x.textContent = "×";
    x.addEventListener("click", () => { view.query = Math.max(0, Math.min(view.query, labels.queries.length - 2)); commit(S.removeQuery(labels, i)); });
    li.append(pick, x);
    return li;
  }));
}

// ---------------------------------------------------------------- interaction

function clickTile(pid, index, ev) {
  if (ev.shiftKey && selected.size) {
    const list = ids();
    const anchor = list.indexOf([...selected].at(-1));
    const [a, b] = [Math.min(anchor, index), Math.max(anchor, index)];
    list.slice(a, b + 1).forEach((p) => selected.add(p));
  } else if (selected.has(pid)) selected.delete(pid);
  else selected.add(pid);
  view.focus = index;
  render();
}

function gotoClump(index) {
  view.clump = Math.max(0, Math.min(project.clumps.length - 1, index));
  view.focus = 0;
  selected = new Set();
  render();
  $("grid").parentElement.scrollTop = 0;
}

function finishAndAdvance() {
  if (!isDone()) commit(S.finish(labels, clump()));
  const open = project.clumps.findIndex((c, i) => i > view.clump && !labels.done.includes(c.id));
  const any = open >= 0 ? open : project.clumps.findIndex((c) => !labels.done.includes(c.id));
  if (any < 0) {
    toast("Every set is finished. Export the dataset when you are ready.");
    return;
  }
  gotoClump(any);
}

function moveFocus(delta) {
  const list = ids();
  view.focus = Math.max(0, Math.min(list.length - 1, view.focus + delta));
  render();
  if (zoom) openZoom(list[view.focus]);
}

function columns() {
  const tiles = [...$("grid").children];
  if (tiles.length < 2) return 1;
  const top = tiles[0].offsetTop;
  const n = tiles.findIndex((t) => t.offsetTop > top);
  return n < 0 ? tiles.length : n;
}

document.addEventListener("keydown", (ev) => {
  if (!$("dialog").hidden) { if (ev.key === "Escape") $("dialog").hidden = true; return; }
  const tag = ev.target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return;
  if (ev.ctrlKey && ev.key.toLowerCase() === "z") { ev.preventDefault(); undo(); return; }
  if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
  if (view.tab !== "sets") return;

  const key = ev.key.toLowerCase();
  const handled = () => ev.preventDefault();
  if (key === "escape") { handled(); if (zoom) closeZoom(); else { selected = new Set(); render(); } return; }
  if (key === "arrowright") { handled(); moveFocus(1); return; }
  if (key === "arrowleft") { handled(); moveFocus(-1); return; }
  if (key === "arrowdown") { handled(); moveFocus(columns()); return; }
  if (key === "arrowup") { handled(); moveFocus(-columns()); return; }
  if (key === " ") {
    handled();
    const pid = ids()[view.focus];
    selected.has(pid) ? selected.delete(pid) : selected.add(pid);
    render();
    return;
  }
  if (key === "a") { handled(); selected = new Set(ids()); render(); return; }
  if (key === "g") { handled(); commit(S.group(labels, targets())); selected = new Set(); render(); return; }
  if (key === "u") { handled(); commit(S.ungroup(labels, targets())); return; }
  if (key === "b") { handled(); commit(S.toggleBest(labels, targets())); return; }
  if (/^[0-6]$/.test(key)) { handled(); commit(S.setCategory(labels, targets(), S.CATEGORIES[Number(key)])); return; }
  if (key === "s") { handled(); commit(S.setBlur(labels, targets(), "sharp")); return; }
  if (key === "e") { handled(); commit(S.setBlur(labels, targets(), "soft")); return; }
  if (key === "n") { handled(); commit(S.setBlur(labels, targets(), "unsure")); return; }
  if (key === "z") {
    handled();
    const pid = ids()[view.focus];
    if (!zoom) openZoom(pid);
    else if (!zoom.full) openZoom(pid, true);
    else closeZoom();
    return;
  }
  if (key === "enter") { handled(); finishAndAdvance(); return; }
  if (key === "backspace" || key === "pageup") { handled(); gotoClump(view.clump - 1); return; }
  if (key === "pagedown") { handled(); gotoClump(view.clump + 1); }
});

// ---------------------------------------------------------------- zoom

function openZoom(pid, full = false) {
  zoom = { pid, full };
  $("zoom").hidden = false;
  $("zoom-name").textContent = photo(pid).rel;
  $("zoom-mode").textContent = full ? "100% (Z to close)" : "Fit to window (Z for 100%)";
  $("zoom-body").classList.toggle("full", full);
  $("zoom-img").src = `/img/${pid}?size=${full ? "full" : "preview"}`;
}

function closeZoom() {
  zoom = null;
  $("zoom").hidden = true;
  $("zoom-img").removeAttribute("src");
}

$("zoom-close").addEventListener("click", closeZoom);
$("zoom-img").addEventListener("click", () => zoom && (zoom.full ? closeZoom() : openZoom(zoom.pid, true)));

// ---------------------------------------------------------------- chrome

$("tab-sets").addEventListener("click", () => { view.tab = "sets"; render(); });
$("tab-search").addEventListener("click", () => { view.tab = "search"; render(); });
$("undo").addEventListener("click", undo);
$("prev-set").addEventListener("click", () => gotoClump(view.clump - 1));
$("next-set").addEventListener("click", () => gotoClump(view.clump + 1));
$("finish-btn").addEventListener("click", finishAndAdvance);
$("group-btn").addEventListener("click", () => { commit(S.group(labels, targets())); selected = new Set(); render(); });
$("ungroup-btn").addEventListener("click", () => commit(S.ungroup(labels, targets())));
$("best-btn").addEventListener("click", () => commit(S.toggleBest(labels, targets())));
$("query-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const text = $("query-input").value;
  const next = S.addQuery(labels, text);
  if (next === labels) { toast("Enter a new search term."); return; }
  $("query-input").value = "";
  view.query = next.queries.length - 1;
  commit(next);
});

$("dialog-close").addEventListener("click", () => ($("dialog").hidden = true));
function showDialog(title, nodes) {
  $("dialog-title").textContent = title;
  $("dialog-body").replaceChildren(...nodes);
  $("dialog").hidden = false;
  $("dialog-close").focus();
}

$("export").addEventListener("click", async () => {
  if (saveTimer) await flushSave();
  const res = await fetch("/api/export", { method: "POST" });
  const data = await res.json();
  if (!res.ok) { showDialog("Not exported", [Object.assign(document.createElement("p"), { textContent: data.detail })]); return; }
  const list = document.createElement("ul");
  [
    `${data.photos} photos copied`,
    `${data.near_groups} same-moment groups (${data.groups_without_best} without a keeper marked)`,
    `${data.exact_groups} sets of byte-identical copies found automatically`,
    `${data.soft} photos marked blurry`,
    `${data.queries} search terms`,
    `Scored: ${data.tasks.join(", ")}`,
  ].forEach((t) => list.append(Object.assign(document.createElement("li"), { textContent: t })));
  const intro = Object.assign(document.createElement("p"), { textContent: "The dataset is ready. Score the current engine on it with:" });
  const code = Object.assign(document.createElement("code"), {
    textContent: `venv\\Scripts\\python.exe -m dev.evalkit run "${data.dataset}"`,
  });
  showDialog("Dataset exported", [list, intro, code]);
});

load().catch((err) => toast(`Could not load the project: ${err.message}`));
