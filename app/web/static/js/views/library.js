import { html, useEffect, useMemo, useState } from "../lib/html.js";
import { api, query } from "../lib/api.js";
import { route, replace, href } from "../lib/router.js";
import { summary, dataVersion } from "../lib/store.js";
import { count, monthLabel, plural } from "../lib/format.js";
import { Icon } from "../ui/icon.js";
import { usePagedList } from "../ui/paged.js";
import { FILTER_LABELS } from "../lib/labels.js";
import { PhotoGrid } from "./review.js";

const SORTS = [
  ["newest", "Newest first"],
  ["oldest", "Oldest first"],
  ["largest", "Largest first"],
];
const DENSITY = { small: 130, medium: 190, large: 280 };

function stored(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

/** Year/month scrubber for jumping through a big library without scrolling for a minute. */
function Timeline({ buckets, current, onJump }) {
  const years = useMemo(() => {
    const map = new Map();
    for (const b of buckets) {
      const year = b.month.slice(0, 4);
      if (!map.has(year)) map.set(year, []);
      map.get(year).push(b);
    }
    return [...map.entries()];
  }, [buckets]);
  const currentYear = current?.slice(0, 4);
  if (buckets.length < 2) return null;
  return html`
    <nav class="timeline" aria-label="Jump to a date">
      ${years.map(
        ([year, months]) => html`
          <div class=${`tl-year${year === currentYear ? " open" : ""}`} key=${year}>
            <button class="tl-year-btn" onClick=${() => onJump(months[0].offset)}>${year}</button>
            ${year === currentYear &&
            months.map(
              (m) => html`<button class=${`tl-month${m.month === current ? " on" : ""}`} onClick=${() => onJump(m.offset)} key=${m.month} title=${`${monthLabel(m.month)} · ${plural(m.count, "item")}`}>
                ${monthLabel(m.month).split(" ")[0].slice(0, 3)}
              </button>`
            )}
          </div>
        `
      )}
    </nav>
  `;
}

export function PhotosView({ route: r }) {
  const q = r.query;
  const flagged = q.get("flagged") === "1";
  const person = q.get("person") ?? "";
  const category = q.get("category") ?? "";
  const sort = q.get("sort") ?? "newest";
  const [density, setDensity] = useState(stored("po-density", "medium"));
  const [buckets, setBuckets] = useState([]);
  const [current, setCurrent] = useState(null);
  const [jump, setJump] = useState(null);
  const version = dataVersion.value;
  const s = summary.value;

  const params = { kind: "photo", flagged, person, category, sort };
  const list = usePagedList((offset, limit) => api.get(`/api/photos${query({ ...params, offset, limit })}`), {
    pageSize: 200,
    deps: [flagged, person, category, sort, version],
  });

  useEffect(() => {
    let live = true;
    api.get(`/api/timeline${query(params)}`).then((t) => live && setBuckets(t)).catch(() => {});
    return () => {
      live = false;
    };
  }, [flagged, person, category, sort, version]);

  const update = (patch) => {
    const next = { flagged: flagged ? "1" : "", person, category, sort: sort === "newest" ? "" : sort, ...patch };
    replace(`/photos${query(next)}`);
  };

  const setDensityPref = (value) => {
    setDensity(value);
    try {
      localStorage.setItem("po-density", value);
    } catch {
      /* fine */
    }
  };

  const onFirst = (index) => {
    let found = buckets[0]?.month ?? null;
    for (const b of buckets) {
      if (b.offset <= index) found = b.month;
      else break;
    }
    setCurrent((prev) => (prev === found ? prev : found));
  };

  const flaggedCount = s?.review?.flagged_photos ?? 0;
  // Only offer a kind of photo the library actually has (and keep the chosen one, so it can be cleared).
  const kinds = Object.entries(FILTER_LABELS).filter(([key]) => (s?.tags?.[key] ?? 0) > 0 || key === category);
  const filtered = flagged || person || category;

  return html`
    <div class="page wide library">
      <div class="page-head">
        <div>
          <h1>Photos</h1>
          <p class="num">${list.total != null ? plural(list.total, "photo") : "Loading…"}${flagged ? " flagged for review" : ""}</p>
        </div>
      </div>
      <div class="toolbar">
        <div class="row wrap">
          <button class="chip" aria-pressed=${flagged} onClick=${() => update({ flagged: flagged ? "" : "1" })}>
            <${Icon} name="flag" size="sm" /> Flagged${flaggedCount ? ` (${count(flaggedCount)})` : ""}
          </button>
          <div class="segmented" role="radiogroup" aria-label="People">
            ${[
              ["", "All"],
              ["with", "With people"],
              ["without", "No people"],
            ].map(([key, label]) => html`<button role="radio" aria-checked=${person === key} onClick=${() => update({ person: key })} key=${key}>${label}</button>`)}
          </div>
          ${kinds.length > 0 &&
          html`<select class="select sort-select" aria-label="Kind of photo" value=${category} onChange=${(e) => update({ category: e.target.value })}>
            <option value="">Any kind of photo</option>
            ${kinds.map(([key, label]) => html`<option value=${key} key=${key}>${label}${s?.tags?.[key] ? ` (${count(s.tags[key])})` : ""}</option>`)}
          </select>`}
          <select class="select sort-select" aria-label="Sort" value=${sort} onChange=${(e) => update({ sort: e.target.value === "newest" ? "" : e.target.value })}>
            ${SORTS.map(([key, label]) => html`<option value=${key} key=${key}>${label}</option>`)}
          </select>
          <div class="segmented" role="radiogroup" aria-label="Thumbnail size">
            ${[
              ["small", "Small"],
              ["medium", "Medium"],
              ["large", "Large"],
            ].map(([key, label]) => html`<button role="radio" aria-checked=${density === key} onClick=${() => setDensityPref(key)} key=${key}>${label}</button>`)}
          </div>
        </div>
      </div>

      <div class="library-body">
        <div class="library-grid">
          <${PhotoGrid}
            list=${list}
            minCell=${DENSITY[density]}
            scrollToIndex=${jump}
            onFirst=${onFirst}
            emptyState=${html`
              <div class="empty">
                <span class="art"><${Icon} name="images" size="lg" /></span>
                <h2>${filtered ? "No photos match" : "No photos yet"}</h2>
                <p>${filtered ? "Try a different filter." : "Scan your photos folder to fill your library."}</p>
                ${!filtered && html`<a class="btn primary" href=${href("/scan")}>Scan now</a>`}
              </div>
            `}
          />
        </div>
        <${Timeline} buckets=${buckets} current=${current} onJump=${(offset) => setJump({ i: offset, t: Date.now() })} />
      </div>
    </div>
  `;
}
