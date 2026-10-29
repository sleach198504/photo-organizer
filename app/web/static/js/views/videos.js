import { html, useEffect, useMemo, useState } from "../lib/html.js";
import { api } from "../lib/api.js";
import { href } from "../lib/router.js";
import { dataVersion } from "../lib/store.js";
import { bytes, dateShort, plural, timeOfDay, duration } from "../lib/format.js";
import { Icon } from "../ui/icon.js";
import { Thumb } from "../ui/thumb.js";
import { openLightbox } from "../ui/lightbox.js";

function sessionTitle(session) {
  const day = dateShort(session.start);
  const sameDay = dateShort(session.start) === dateShort(session.end);
  return sameDay ? `${day} · ${timeOfDay(session.start)}` : `${day} – ${dateShort(session.end)}`;
}

export function VideosView() {
  const [sessions, setSessions] = useState(null);
  const [error, setError] = useState(null);
  const version = dataVersion.value;

  useEffect(() => {
    let live = true;
    api
      .get("/api/video-sessions")
      .then((data) => live && setSessions(data))
      .catch((e) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [version]);

  const flat = useMemo(() => (sessions ?? []).flatMap((s) => s.items), [sessions]);
  const total = flat.length;
  const totalBytes = (sessions ?? []).reduce((sum, s) => sum + s.bytes, 0);

  const open = (item) =>
    openLightbox({ total: flat.length, get: (i) => flat[i], index: flat.findIndex((f) => f.id === item.id) });

  if (error) return html`<div class="page"><div class="notice error"><${Icon} name="circle-alert" /><span>${error}</span></div></div>`;
  if (!sessions) return html`<div class="page"><div class="loading-row"><${Icon} name="loader-circle" spin /> Loading…</div></div>`;

  return html`
    <div class="page wide">
      <div class="page-head">
        <div>
          <h1>Videos</h1>
          <p>
            ${total
              ? html`${plural(total, "video")} · ${bytes(totalBytes)}. Grouped by when you filmed them, so clips from one outing sit together.`
              : "Videos from your photos folder appear here, grouped by when you filmed them."}
          </p>
        </div>
      </div>
      ${total === 0
        ? html`<div class="empty">
            <span class="art"><${Icon} name="film" size="lg" /></span>
            <h2>No videos found</h2>
            <p>Videos in your photos folder show up after a scan.</p>
            <a class="btn primary" href=${href("/scan")}>Scan now</a>
          </div>`
        : html`<div class="stack tight">
            ${sessions.map(
              (session) => html`
                <section class="panel session" key=${session.start}>
                  <header class="group-head">
                    <div class="group-info">
                      <div class="group-title"><b>${sessionTitle(session)}</b></div>
                      <span class="why">${plural(session.count, "video")} · ${bytes(session.bytes)}</span>
                    </div>
                  </header>
                  <div class="strip">
                    ${session.items.map(
                      (item) => html`
                        <div class="strip-cell" style="width:224px" key=${item.id}>
                          <${Thumb} item=${item} onOpen=${open} style="height:140px" />
                          <div class="strip-meta faint num">${duration(item.dur)} · ${bytes(item.size)}</div>
                        </div>
                      `
                    )}
                  </div>
                </section>
              `
            )}
          </div>`}
    </div>
  `;
}
