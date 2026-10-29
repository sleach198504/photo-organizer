import { html, useEffect, useState } from "../lib/html.js";
import { api, media } from "../lib/api.js";
import { href } from "../lib/router.js";
import { summary, jobs, marks, applyMarks, anyJobRunning, dataVersion } from "../lib/store.js";
import { bytes, count, plural, ago } from "../lib/format.js";
import { Icon } from "../ui/icon.js";
import { beginScan } from "./scan.js";

import { categoryIcon } from "../lib/labels.js";

/** A few real flagged photos laid out like a contact sheet, with the grease-pencil marks
 *  the app would suggest. Purely illustrative - nothing here is a decision yet. */
function ContactStrip({ category }) {
  const [frames, setFrames] = useState(null);
  const version = dataVersion.value;

  useEffect(() => {
    let live = true;
    if (!category) return;
    api.get(`/api/review/${category.key}?limit=3`).then((data) => {
      if (!live) return;
      if (data.groups) {
        const group = data.groups.find((g) => g.members.length > 1) ?? data.groups[0];
        setFrames(group ? group.members.slice(0, 5).map((m) => ({ item: m, suggest: m.keeper ? "keep" : "remove" })) : []);
      } else {
        setFrames(data.items.slice(0, 5).map((item) => ({ item, suggest: "remove" })));
      }
    });
    return () => {
      live = false;
    };
  }, [category?.key, version]);

  if (!frames?.length) return null;
  return html`
    <div class="contact-sheet">
    <div class="contact-strip" aria-hidden="true">
      ${frames.map(
        ({ item, suggest }) => html`
          <div class=${`frame ${suggest}`} key=${item.id}>
            <img src=${media.thumb(item)} alt="" loading="lazy" />
            ${suggest === "remove" && html`<svg viewBox="0 0 100 100" preserveAspectRatio="none"><line x1="10" y1="90" x2="90" y2="10" /></svg>`}
          </div>
        `
      )}
    </div>
    <p class="contact-caption">From <b>${category.label}</b>: the red slash marks what would be removed${frames.some((f) => f.suggest === "keep") ? ", the green outline the best one to keep" : ""}. This is a sample, not a decision.</p>
    </div>
  `;
}

function NextStep() {
  const s = summary.value;
  const m = marks.value;
  const scanning = jobs.scan.value?.state === "running";
  const review = s.review;
  const top = [...review.categories].filter((c) => c.count > 0).sort((a, b) => b.bytes - a.bytes)[0];

  let view;
  if (scanning) {
    view = {
      title: "Scanning your library…",
      body: "You can look around while it works. Results appear here when it's done.",
      action: html`<a class="btn primary lg" href=${href("/scan")}>See progress</a>`,
    };
  } else if (!s.last_scan) {
    view = {
      title: "Scan your photos to get started",
      body: "Photo Organizer reads your folder once, then shows you what's worth clearing.",
      action: html`<button class="btn primary lg" onClick=${() => beginScan()}><${Icon} name="scan-search" /> Scan now</button>`,
    };
  } else if (m.remove + m.keep > 0) {
    view = {
      title: `${plural(m.remove + m.keep, "decision")} waiting`,
      body:
        m.remove > 0
          ? `${plural(m.remove, "item")} marked to remove (${bytes(m.remove_bytes)}). Moving them is reversible. They wait in Removed until you delete them.`
          : "Apply your keeps to stop seeing these suggestions.",
      action: html`
        <button class="btn primary lg" disabled=${anyJobRunning.value} onClick=${() => applyMarks().catch(() => {})}>
          Move to Removed
        </button>
        <a class="btn lg" href=${href("/review")}>Keep reviewing</a>
      `,
    };
  } else if (review.flagged_photos > 0) {
    view = {
      title: `${plural(review.flagged_photos, "item")} to review`,
      body: `Clearing everything flagged would free up to ${bytes(review.flagged_bytes)}. Nothing moves until you say so.`,
      action: html`<a class="btn primary lg" href=${href("/review")}>Start reviewing <${Icon} name="arrow-right" /></a>`,
    };
  } else {
    view = {
      title: "You're all caught up",
      body: "There's nothing left to review. Next you could file everything into tidy folders by date.",
      action: html`<a class="btn primary lg" href=${href("/organize")}>Organize into folders</a>`,
    };
  }

  return html`
    <section class="panel hero">
      <div class="hero-copy">
        <h2>${view.title}</h2>
        <p>${view.body}</p>
        <div class="row wrap">${view.action}</div>
      </div>
      ${!scanning && top && html`<${ContactStrip} category=${top} />`}
    </section>
  `;
}

function CleanupList() {
  const cats = summary.value.review.categories.filter((c) => c.count > 0);
  if (!cats.length) return null;
  const max = Math.max(...cats.map((c) => c.bytes), 1);
  return html`
    <section class="stack tight">
      <div class="section-head">
        <h2>What was found</h2>
        <a href=${href("/review")}>Review all</a>
      </div>
      <ul class="panel cleanup">
        ${cats.map(
          (c) => html`
            <li key=${c.key}>
              <a class="cleanup-row" href=${href(`/review/${c.key}`)}>
                <span class="cleanup-icon"><${Icon} name=${categoryIcon(c.key)} /></span>
                <span class="cleanup-label">
                  <b>${c.label}</b>
                  <span class="faint">
                    ${c.kind === "group"
                      ? `${plural(c.count, "set")} · ${plural(c.photos, "extra copy", "extra copies")}`
                      : plural(c.count, c.key === "video" || c.key === "screen_recording" ? "video" : "photo")}
                  </span>
                </span>
                <span class="cleanup-size">
                  <span class="num">${bytes(c.bytes)}</span>
                  <span class="bar thin" aria-hidden="true"><i style=${`width:${Math.max(3, (c.bytes / max) * 100)}%`}></i></span>
                </span>
                <${Icon} name="chevron-right" size="sm" />
              </a>
            </li>
          `
        )}
      </ul>
    </section>
  `;
}

function LibraryFacts() {
  const s = summary.value;
  const facts = [
    ["Photos", count(s.photos)],
    ["Videos", count(s.videos)],
    ["Total size", bytes(s.bytes)],
    ["With a date", s.photos + s.videos ? `${Math.round((s.dated / (s.photos + s.videos)) * 100)}%` : "–"],
  ];
  return html`
    <section class="stack tight">
      <h2>Your library</h2>
      <dl class="panel facts">
        ${facts.map(([label, value]) => html`<div><dt>${label}</dt><dd class="num">${value}</dd></div>`)}
      </dl>
    </section>
  `;
}

const ACTIVITY_ICONS = { scan: "scan-search", applied: "trash-2", restored: "undo-2", purged: "trash-2", organized: "folder-tree" };

function Activity() {
  const items = summary.value.activity;
  return html`
    <section class="stack tight">
      <h2>Recent activity</h2>
      ${items.length === 0
        ? html`<p class="faint">Nothing yet. What you do will be listed here.</p>`
        : html`<ul class="panel activity">
            ${items.map(
              (a) => html`
                <li key=${a.id}>
                  <${Icon} name=${ACTIVITY_ICONS[a.kind] ?? "history"} size="sm" />
                  <span class="activity-text"><b>${a.title}</b>${a.detail && !/^\d+$/.test(a.detail) ? html`<span class="faint">${a.detail}</span>` : null}</span>
                  <time class="faint">${ago(a.ts)}</time>
                </li>
              `
            )}
          </ul>`}
    </section>
  `;
}

export function HomeView() {
  const s = summary.value;
  if (!s) return null;
  const scanning = jobs.scan.value?.state === "running";
  return html`
    <div class="page home">
      <div class="page-head">
        <div>
          <h1>Home</h1>
          <p>${s.last_scan ? `Last scanned ${ago(s.last_scan)}.` : "Welcome."}</p>
        </div>
      </div>
      ${s.needs_rescan > 0 && !scanning &&
      html`<div class="notice"><${Icon} name="refresh-cw" /><span>
        ${plural(s.needs_rescan, "item")} in your library were scanned by an older version, so some details (like dates) are
        missing. <button class="link" onClick=${() => beginScan()}>Scan again</button> to fill them in. It's quick.
      </span></div>`}
      <div class="home-grid">
        <div class="stack">
          <${NextStep} />
          <${CleanupList} />
        </div>
        <aside class="stack">
          <${LibraryFacts} />
          <${Activity} />
        </aside>
      </div>
    </div>
  `;
}
