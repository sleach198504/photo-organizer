import { html, useEffect, useRef, useState } from "../lib/html.js";
import { route, href, go } from "../lib/router.js";
import { summary, jobs, marks, applyMarks, clearAllMarks, anyJobRunning } from "../lib/store.js";
import { bytes, count, plural, ago } from "../lib/format.js";
import { Icon } from "./icon.js";
import { useHotkeys } from "../lib/keys.js";
import { showShortcuts } from "./shortcuts.js";
import { exitApp } from "../lib/exit.js";

export const Brand = () => html`
  <div class="brand">
    <svg viewBox="0 0 64 64" aria-hidden="true">
      <g fill="currentColor">
        <rect x="9" y="9" width="21" height="21" rx="4" opacity=".95" />
        <rect x="34" y="9" width="21" height="21" rx="4" opacity=".5" />
        <rect x="9" y="34" width="21" height="21" rx="4" opacity=".5" />
        <rect x="34" y="34" width="21" height="21" rx="4" opacity=".25" />
      </g>
      <rect x="6" y="6" width="27" height="27" rx="7" fill="none" stroke="var(--keep)" stroke-width="3.5" />
      <path d="M36 54 54 36" stroke="var(--remove)" stroke-width="5.5" stroke-linecap="round" />
    </svg>
    <b>Photo Organizer</b>
  </div>
`;

function NavItem({ to, icon, label, badge, attention, exact }) {
  const path = route.value.path;
  const current = exact ? path === to : path === to || path.startsWith(to + "/");
  return html`
    <a class="nav-item" href=${href(to)} aria-current=${current ? "page" : undefined} title=${label}>
      <${Icon} name=${icon} />
      <span class="label">${label}</span>
      ${badge ? html`<span class=${`nav-count${attention ? " attention" : ""}`}>${badge}</span>` : null}
    </a>
  `;
}

function ScanStatus() {
  const scan = jobs.scan.value;
  const s = summary.value;
  if (scan?.state === "running") {
    const stage = scan.stages.find((x) => x.state === "running") ?? scan.stages.find((x) => x.state === "pending");
    const done = scan.stages.filter((x) => x.state === "done" || x.state === "skipped").length;
    const pct = Math.round(((done + (stage?.total ? stage.done / stage.total : 0)) / scan.stages.length) * 100);
    return html`
      <a class="side-status" href=${href("/scan")}>
        <div class="row"><${Icon} name="loader-circle" spin /><b>Scanning</b><span class="spacer"></span><span class="num faint">${pct}%</span></div>
        <div class="bar"><i style=${`width:${pct}%`}></i></div>
        <span class="detail faint">${stage?.label ?? "Starting"}</span>
      </a>
    `;
  }
  return html`
    <a class="side-status" href=${href("/scan")}>
      <div class="row"><${Icon} name="scan-search" /><b>Scan</b></div>
      <span class="detail faint">${s?.last_scan ? `Last scan ${ago(s.last_scan)}` : "Not scanned yet"}</span>
    </a>
  `;
}

export function Sidebar() {
  const s = summary.value;
  const review = s?.review?.flagged_photos ?? 0;
  const removed = s?.removed?.count ?? 0;
  return html`
    <nav class="sidebar" aria-label="Main">
      <${Brand} />
      <${NavItem} to="/" icon="house" label="Home" exact />

      <div class="nav-title">Library</div>
      <${NavItem} to="/photos" icon="images" label="Photos" badge=${s ? count(s.photos) : ""} />
      <${NavItem} to="/videos" icon="film" label="Videos" badge=${s?.videos ? count(s.videos) : ""} />
      <${NavItem} to="/trips" icon="plane" label="Trips" badge=${s?.trips ? count(s.trips) : ""} />

      <div class="nav-title">Tidy up</div>
      <${NavItem} to="/review" icon="list-checks" label="Review" badge=${review ? count(review) : ""} attention />
      <${NavItem} to="/removed" icon="trash-2" label="Removed" badge=${removed ? count(removed) : ""} />
      <${NavItem} to="/organize" icon="folder-tree" label="Organize" />

      <div class="sidebar-spacer"></div>
      <${ScanStatus} />
      <${NavItem} to="/settings" icon="settings" label="Settings" />
      <button class="nav-item" onClick=${showShortcuts} title="Keyboard shortcuts">
        <${Icon} name="keyboard" /><span class="label">Shortcuts</span>
      </button>
      <button class="nav-item" onClick=${exitApp} title="Exit Photo Organizer">
        <${Icon} name="log-out" /><span class="label">Exit</span>
      </button>
    </nav>
  `;
}

export const TITLES = {
  "": "Home",
  photos: "Photos",
  videos: "Videos",
  trips: "Trips",
  review: "Review",
  removed: "Removed",
  organize: "Organize",
  scan: "Scan",
  settings: "Settings",
  search: "Search",
};

export function Topbar() {
  const r = route.value;
  const root = r.parts[0] ?? "";
  const input = useRef(null);
  const [text, setText] = useState(r.path === "/search" ? r.query.get("q") ?? "" : "");

  useHotkeys({
    "/": () => {
      input.current?.focus();
      input.current?.select();
    },
    "ctrl+f": () => {
      input.current?.focus();
      input.current?.select();
    },
  });

  useEffect(() => {
    if (r.path !== "/search") setText("");
  }, [r.path]);

  function submit(event) {
    event.preventDefault();
    const q = text.trim();
    if (q) go(`/search?q=${encodeURIComponent(q)}`);
  }

  return html`
    <header class="topbar">
      <div class="crumbs"><span>${TITLES[root] ?? "Photo Organizer"}</span></div>
      <div class="grow"></div>
      <form class="search" role="search" onSubmit=${submit}>
        <${Icon} name="search" size="sm" />
        <input
          ref=${input}
          class="input"
          type="search"
          placeholder="Search your photos, like “beach at sunset”"
          aria-label="Search photos"
          value=${text}
          onInput=${(e) => setText(e.target.value)}
          onKeyDown=${(e) => e.key === "Escape" && e.target.blur()}
        />
      </form>
    </header>
  `;
}

/** Floating bar that appears whenever decisions are waiting to be applied, on every page. */
export function DecisionTray() {
  const m = marks.value;
  const apply = jobs.apply.value;
  const applying = apply?.state === "running";
  const pending = m.remove + m.keep;
  if (!pending && !applying) return null;

  if (applying) {
    const stage = apply.stages[0];
    const pct = stage?.total ? Math.round((stage.done / stage.total) * 100) : null;
    return html`
      <div class="tray" role="status">
        <div class="tally"><${Icon} name="loader-circle" spin /> <span>Moving ${count(m.remove)} to Removed${pct != null ? ` · ${pct}%` : ""}</span></div>
      </div>
    `;
  }

  return html`
    <div class="tray" role="region" aria-label="Pending decisions">
      <div class="tally">
        ${m.remove > 0 &&
        html`<span><i class="dot remove"></i><b>${count(m.remove)}</b> to remove <span class="muted">· ${bytes(m.remove_bytes)}</span></span>`}
        ${m.keep > 0 && html`<span><i class="dot keep"></i><b>${count(m.keep)}</b> to keep</span>`}
      </div>
      <div class="row">
        <button class="btn subtle" onClick=${() => clearAllMarks()}>Clear marks</button>
        ${m.remove > 0 && html`<a class="btn" href=${href("/review/marked")}>See marked</a>`}
        <button class="btn primary" disabled=${anyJobRunning.value} onClick=${() => applyMarks().catch(() => {})}>
          ${m.remove > 0 ? `Move ${plural(m.remove, "item")} to Removed` : "Apply keeps"}
        </button>
      </div>
    </div>
  `;
}
