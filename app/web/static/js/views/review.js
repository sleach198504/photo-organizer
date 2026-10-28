import { html, useCallback, useEffect, useMemo, useRef, useState } from "../lib/html.js";
import { api } from "../lib/api.js";
import { route, href, replace } from "../lib/router.js";
import { summary, markOf, marks, setMarksMulti, suggestMarks, dataVersion, jobs } from "../lib/store.js";
import { bytes, count, plural, dateShort, timeOfDay, megapixels } from "../lib/format.js";
import { categoryIcon } from "../lib/labels.js";
import { useHotkeys } from "../lib/keys.js";
import { Icon } from "../ui/icon.js";
import { Thumb } from "../ui/thumb.js";
import { VirtualGrid } from "../ui/virtual-grid.js";
import { usePagedList } from "../ui/paged.js";
import { openLightbox } from "../ui/lightbox.js";
import { toast } from "../ui/toast.js";

// ---- shared pieces ------------------------------------------------------------

function Rail({ categories, current }) {
  const mk = marks.value;
  return html`
    <nav class="rail" aria-label="Review categories">
      ${categories
        .filter((c) => c.count > 0 || c.key === current)
        .map(
          (c) => html`
            <a class="rail-item" href=${href(`/review/${c.key}`)} aria-current=${c.key === current ? "page" : undefined} key=${c.key}>
              <${Icon} name=${categoryIcon(c.key)} />
              <span class="label">${c.label}</span>
              ${c.marked > 0 && html`<span class="rail-marked" title="Marked so far">${count(c.marked)}</span>`}
              <span class="rail-count num">${count(c.count)}</span>
            </a>
          `
        )}
      ${mk.remove + mk.keep > 0 &&
      html`<a class="rail-item marked-link" href=${href("/review/marked")} aria-current=${current === "marked" ? "page" : undefined}>
        <${Icon} name="flag" /><span class="label">Everything marked</span>
        <span class="rail-count num">${count(mk.remove + mk.keep)}</span>
      </a>`}
    </nav>
  `;
}

function AllClear() {
  return html`
    <div class="empty">
      <span class="art"><${Icon} name="circle-check" size="lg" /></span>
      <h2>Nothing left to review</h2>
      <p>Everything the scan flagged has been decided. Scan again after adding new photos, or tidy up by filing them into folders.</p>
      <div class="row"><a class="btn primary" href=${href("/organize")}>Organize into folders</a><a class="btn" href=${href("/")}>Back to Home</a></div>
    </div>
  `;
}

function useGroupPages(key, version) {
  const [state, setState] = useState({ groups: [], total: null, done: false, loading: false, error: null });
  const gen = useRef(0);
  const stateRef = useRef(state);
  stateRef.current = state;

  const loadMore = useCallback(async () => {
    const cur = stateRef.current;
    if (cur.loading || cur.done) return;
    const mine = gen.current;
    setState((s) => ({ ...s, loading: true }));
    try {
      const data = await api.get(`/api/review/${key}?offset=${cur.groups.length}&limit=20`);
      if (mine !== gen.current) return;
      setState((s) => ({
        groups: [...s.groups, ...data.groups],
        total: data.total,
        done: data.groups.length === 0 || s.groups.length + data.groups.length >= data.total,
        loading: false,
        error: null,
      }));
    } catch (error) {
      if (mine === gen.current) setState((s) => ({ ...s, loading: false, done: true, error: error.message }));
    }
  }, [key]);

  useEffect(() => {
    gen.current += 1;
    const fresh = { groups: [], total: null, done: false, loading: false, error: null };
    stateRef.current = fresh;
    setState(fresh);
    loadMore();
  }, [key, version]);

  return { ...state, loadMore };
}

function Sentinel({ onVisible, disabled }) {
  const ref = useRef(null);
  useEffect(() => {
    if (disabled || !ref.current) return;
    const observer = new IntersectionObserver((entries) => entries[0].isIntersecting && onVisible(), {
      root: ref.current.closest(".content"),
      rootMargin: "600px",
    });
    observer.observe(ref.current);
    return () => observer.disconnect();
  });
  return html`<div ref=${ref} class="sentinel" aria-hidden="true"></div>`;
}

// ---- groups (duplicates and similar shots) ---------------------------------------

function GroupCard({ group, cursorId, onOpen }) {
  const members = group.members;
  const keeper = members.find((m) => m.keeper);
  const others = members.filter((m) => !m.keeper);
  const state = members.map((m) => markOf(m));
  const decided = state.every((m) => m !== null && m !== undefined);
  const first = members[0];

  const keepSuggested = () =>
    setMarksMulti(
      [
        { ids: keeper ? [keeper.id] : [], mark: "keep" },
        { ids: others.map((m) => m.id), mark: "remove" },
      ].filter((c) => c.ids.length),
      { label: `Kept the best of ${members.length}, marked ${others.length} to remove` }
    );
  const keepAll = () => setMarksMulti([{ ids: members.map((m) => m.id), mark: "keep" }], { label: `Kept all ${members.length}` });

  return html`
    <article class=${`panel group${decided ? " decided" : ""}`} data-group=${group.id}>
      <header class="group-head">
        <div class="group-info">
          <div class="group-title">
            <b>${members.length} photos</b>
            <span class="faint">${dateShort(first?.date)} · ${timeOfDay(first?.date)}</span>
          </div>
          ${group.why && html`<span class="why"><${Icon} name="sparkles" size="sm" /> ${group.why}</span>`}
        </div>
        <span class="spacer"></span>
        <span class="faint num">frees ${bytes(group.reclaim)}</span>
        <div class="row nowrap">
          <button class="btn sm" onClick=${keepAll}>Keep all</button>
          <button class=${`btn sm ${decided ? "" : "primary"}`} onClick=${keepSuggested}>
            ${decided ? "Reset to suggestion" : "Keep suggested"}
          </button>
        </div>
      </header>
      <div class="strip">
        ${members.map((m) => {
          const ratio = m.w && m.h ? Math.min(1.9, Math.max(0.62, m.w / m.h)) : 1.33;
          return html`
            <div class="strip-cell" style=${`width:${Math.round(168 * ratio)}px`} key=${m.id}>
              <${Thumb}
                item=${m}
                keeper=${m.keeper}
                cursor=${cursorId === m.id}
                onOpen=${() => onOpen(m, group)}
                style="height:168px"
              />
              <div class="strip-meta faint num">${megapixels(m.w, m.h)} · ${bytes(m.size)}</div>
            </div>
          `;
        })}
      </div>
    </article>
  `;
}

function GroupsList({ category }) {
  const version = dataVersion.value;
  const data = useGroupPages(category.key, version);
  const [cursor, setCursor] = useState(null); // { g, m }
  const groups = data.groups;

  const flat = useMemo(() => groups.flatMap((g) => g.members.map((m) => ({ item: m, group: g }))), [groups]);
  const cursorItem = cursor ? groups[cursor.g]?.members[cursor.m] : null;

  const open = (item, group) => {
    const index = flat.findIndex((f) => f.item.id === item.id);
    const byId = new Map(flat.map((f) => [f.item.id, f.group]));
    openLightbox({
      total: flat.length,
      get: (i) => flat[i]?.item,
      index,
      peersOf: (it) => byId.get(it.id)?.members,
      onIndex: (i) => {
        const f = flat[i];
        if (f) setCursor({ g: groups.indexOf(f.group), m: f.group.members.indexOf(f.item) });
      },
    });
  };

  useEffect(() => {
    if (!cursorItem) return;
    document.querySelector(`.thumb[data-id="${cursorItem.id}"]`)?.scrollIntoView({ block: "nearest", behavior: "auto" });
  }, [cursorItem?.id]);

  function move(dg, dm) {
    if (!groups.length) return;
    if (!cursor) return setCursor({ g: 0, m: 0 });
    let { g, m } = cursor;
    if (dm) {
      m += dm;
      if (m < 0) {
        if (g === 0) return;
        g -= 1;
        m = groups[g].members.length - 1;
      } else if (m >= groups[g].members.length) {
        if (g >= groups.length - 1) return;
        g += 1;
        m = 0;
      }
    } else {
      g = Math.min(groups.length - 1, Math.max(0, g + dg));
      m = Math.min(m, groups[g].members.length - 1);
    }
    setCursor({ g, m });
    if (g >= groups.length - 3) data.loadMore();
  }

  const decide = (mark, advance) => {
    if (!cursorItem) return;
    setMarksMulti([{ ids: [cursorItem.id], mark: markOf(cursorItem) === mark ? null : mark }], { undoable: false });
    if (advance) move(0, 1);
  };

  useHotkeys({
    arrowleft: () => move(0, -1),
    arrowright: () => move(0, 1),
    arrowup: () => move(-1, 0),
    arrowdown: () => move(1, 0),
    x: () => decide("remove", true),
    k: () => decide("keep", true),
    u: () => decide(null, false),
    enter: () => cursorItem && open(cursorItem),
    space: () => cursorItem && open(cursorItem),
  });

  if (data.total === 0 && data.done) return html`<${AllClearCategory} />`;
  return html`
    <div class="groups">
      ${groups.map(
        (g, i) => html`<${GroupCard} group=${g} key=${g.id} cursorId=${cursor?.g === i ? cursorItem?.id : null} onOpen=${open} />`
      )}
      ${!data.done && html`<${Sentinel} onVisible=${data.loadMore} />`}
      ${data.loading && html`<div class="loading-row"><${Icon} name="loader-circle" spin /> Loading…</div>`}
      ${data.error && html`<div class="notice error"><${Icon} name="circle-alert" /><span>${data.error}</span></div>`}
    </div>
  `;
}

function AllClearCategory() {
  return html`<div class="empty"><span class="art"><${Icon} name="circle-check" size="lg" /></span><h2>All clear here</h2><p>Nothing in this category needs a decision.</p></div>`;
}

// ---- flat categories (blurry, screenshots, ...) -----------------------------------

export function PhotoGrid({ list, ids, minCell = 190, emptyState, selectable = true, quick = true, showSize = false, marking = true, renderSelection, scrollToIndex, onFirst }) {
  const version = dataVersion.value;
  const [cursor, setCursor] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const lastPicked = useRef(null);
  const columns = useRef(4);

  useEffect(() => {
    setCursor(null);
    setSelected(new Set());
  }, [version]);

  const total = list.total ?? 0;

  const open = (index) =>
    openLightbox({
      total,
      get: list.get,
      ensure: list.ensure,
      index,
      marking,
      onIndex: setCursor,
    });

  const pick = (item, index, event) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (event.shiftKey && lastPicked.current != null) {
        const [a, b] = [lastPicked.current, index].sort((x, y) => x - y);
        for (let i = a; i <= b; i++) {
          const between = list.get(i);
          if (between) next.add(between.id);
        }
      } else if (next.has(item.id)) next.delete(item.id);
      else next.add(item.id);
      return next;
    });
    lastPicked.current = index;
  };

  const step = (delta) => {
    if (!total) return;
    setCursor((c) => {
      const next = c == null ? 0 : Math.min(total - 1, Math.max(0, c + delta));
      list.ensure(next);
      return next;
    });
  };

  const decide = (mark, advance) => {
    const item = cursor != null ? list.get(cursor) : null;
    if (!item) return;
    setMarksMulti([{ ids: [item.id], mark: markOf(item) === mark ? null : mark }], { undoable: false });
    if (advance) step(1);
  };

  useHotkeys({
    arrowleft: () => step(-1),
    arrowright: () => step(1),
    arrowup: () => step(-columns.current),
    arrowdown: () => step(columns.current),
    x: () => marking && decide("remove", true),
    k: () => marking && decide("keep", true),
    u: () => marking && decide(null, false),
    enter: () => cursor != null && open(cursor),
    space: () => cursor != null && open(cursor),
    "ctrl+a": () => selectable && ids && setSelected(new Set(ids)),
    escape: () => (selected.size ? setSelected(new Set()) : false),
  });

  const selectedIds = [...selected];
  const act = (mark) => {
    setMarksMulti([{ ids: selectedIds, mark }], {
      label: mark ? `Marked ${plural(selectedIds.length, "item")} ${mark === "remove" ? "to remove" : "to keep"}` : `Cleared ${plural(selectedIds.length, "mark")}`,
    });
    setSelected(new Set());
  };

  if (list.error) return html`<div class="notice error"><${Icon} name="circle-alert" /><span>${list.error}</span></div>`;
  if (list.total === 0) return emptyState ?? null;

  return html`
    <div class="photo-grid">
      ${selected.size > 0 &&
      html`<div class="selbar-wrap"><div class="selbar" role="region" aria-label="Selection">
        <b class="num">${count(selected.size)} selected</b>
        <span class="spacer"></span>
        ${renderSelection
          ? renderSelection(selectedIds, () => setSelected(new Set()))
          : html`
              <button class="btn sm" onClick=${() => act("remove")}><${Icon} name="x" size="sm" /> Remove</button>
              <button class="btn sm" onClick=${() => act("keep")}><${Icon} name="check" size="sm" /> Keep</button>
              <button class="btn sm subtle" onClick=${() => act(null)}>Clear marks</button>
            `}
        <button class="btn sm subtle" onClick=${() => setSelected(new Set())}>Deselect</button>
      </div></div>`}
      <${VirtualGrid}
        total=${total}
        minCell=${minCell}
        follow=${cursor}
        scrollToIndex=${scrollToIndex}
        version=${list.tick}
        onVisible=${(first, last, cols) => {
          columns.current = cols;
          onFirst?.(first);
          for (let i = first; i <= last; i += 50) list.ensure(i);
          list.ensure(last);
        }}
        renderCell=${(index) => {
          const item = list.get(index);
          if (!item) return html`<div class="thumb skeleton"></div>`;
          return html`<${Thumb}
            item=${item}
            quick=${quick && marking}
            showSize=${showSize}
            selected=${selected.has(item.id)}
            cursor=${cursor === index}
            onOpen=${() => open(index)}
            onPick=${selectable ? (it, e) => pick(it, index, e) : undefined}
          />`;
        }}
      />
    </div>
  `;
}

function FlatList({ category }) {
  const idsRef = useRef(null);
  const version = dataVersion.value;
  const list = usePagedList(
    async (offset, limit) => {
      const data = await api.get(`/api/review/${category.key}?offset=${offset}&limit=${limit}`);
      if (data.ids) idsRef.current = data.ids;
      return data;
    },
    { pageSize: 120, deps: [category.key, version] }
  );
  return html`<${PhotoGrid}
    list=${list}
    ids=${idsRef.current}
    emptyState=${html`<${AllClearCategory} />`}
  />`;
}

// ---- everything marked ----------------------------------------------------------

function MarkedList() {
  const [which, setWhich] = useState("remove");
  const mk = marks.value;
  const version = dataVersion.value;
  const list = usePagedList((offset, limit) => api.get(`/api/marks/items?mark=${which}&offset=${offset}&limit=${limit}`), {
    pageSize: 120,
    deps: [which, version],
  });
  return html`
    <div class="stack tight">
      <div class="row">
        <div class="segmented" role="radiogroup" aria-label="Which marks">
          <button role="radio" aria-checked=${which === "remove"} onClick=${() => setWhich("remove")}>To remove (${count(mk.remove)})</button>
          <button role="radio" aria-checked=${which === "keep"} onClick=${() => setWhich("keep")}>To keep (${count(mk.keep)})</button>
        </div>
      </div>
      <${PhotoGrid}
        list=${list}
        selectable=${false}
        emptyState=${html`<div class="empty"><h2>No decisions yet</h2><p>Photos you mark appear here.</p></div>`}
      />
    </div>
  `;
}

// ---- the view -----------------------------------------------------------------------

export function ReviewView({ route: r }) {
  const s = summary.value;
  const categories = s.review.categories;
  const key = r.parts[1];
  const scanning = jobs.scan.value?.state === "running";
  const category = categories.find((c) => c.key === key);
  const firstWithItems = categories.find((c) => c.count > 0);

  useEffect(() => {
    if (!key && firstWithItems) replace(`/review/${firstWithItems.key}`);
  }, [key, firstWithItems?.key]);

  if (!s.last_scan && !scanning) {
    return html`<div class="page"><div class="empty"><h2>Nothing to review yet</h2><p>Scan your photos first, then come back here.</p><a class="btn primary" href=${href("/scan")}>Scan now</a></div></div>`;
  }
  if (!key && !firstWithItems) return html`<div class="page"><${AllClear} /></div>`;

  const isMarked = key === "marked";

  return html`
    <div class="review">
      <${Rail} categories=${categories} current=${key} />
      <section class="review-main">
        ${isMarked
          ? html`
              <div class="page-head"><div><h1>Everything marked</h1><p>Decisions you've made that haven't been applied yet. Nothing has moved.</p></div></div>
              <${MarkedList} />
            `
          : category
            ? html`<${CategoryPane} category=${category} key=${category.key} />`
            : html`<div class="empty"><h2>That category doesn't exist</h2><p>Pick one from the list.</p></div>`}
      </section>
    </div>
  `;
}

function CategoryPane({ category }) {
  const isGroup = category.kind === "group";
  const hint =
    category.kind === "group"
      ? `${plural(category.count, "set")} · frees up to ${bytes(category.bytes)}`
      : `${plural(category.count, category.key === "video" || category.key === "screen_recording" ? "video" : "photo")} · ${bytes(category.bytes)}`;

  async function acceptAll() {
    try {
      await suggestMarks([category.group_kind]);
    } catch (error) {
      toast(error.message, { kind: "error" });
    }
  }

  async function markEverything(mark) {
    try {
      const data = await api.get(`/api/review/${category.key}?limit=1`);
      await setMarksMulti([{ ids: data.ids, mark }], {
        label: `Marked ${plural(data.ids.length, "item")} ${mark === "remove" ? "to remove" : "to keep"}`,
      });
    } catch (error) {
      toast(error.message, { kind: "error" });
    }
  }

  return html`
    <div class="page-head">
      <div>
        <h1>${category.label}</h1>
        <p>${category.blurb}</p>
      </div>
    </div>
    <div class="toolbar between">
      <span class="faint num">${hint}</span>
      <div class="row">
        ${isGroup
          ? html`<button class="btn primary" onClick=${acceptAll}><${Icon} name="wand-sparkles" /> Accept all suggestions</button>`
          : html`
              <button class="btn" onClick=${() => markEverything("keep")}><${Icon} name="check" /> Keep all</button>
              <button class="btn primary" onClick=${() => markEverything("remove")}><${Icon} name="x" /> Mark all to remove</button>
            `}
      </div>
    </div>
    ${isGroup ? html`<${GroupsList} category=${category} />` : html`<${FlatList} category=${category} />`}
  `;
}
