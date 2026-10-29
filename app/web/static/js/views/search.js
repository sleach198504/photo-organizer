import { html, useEffect, useState } from "../lib/html.js";
import { api } from "../lib/api.js";
import { href } from "../lib/router.js";
import { jobs } from "../lib/store.js";
import { plural, duration } from "../lib/format.js";
import { Icon } from "../ui/icon.js";
import { Thumb } from "../ui/thumb.js";
import { openLightbox } from "../ui/lightbox.js";

const EXAMPLES = ["beach at sunset", "birthday cake", "dog in the snow", "whiteboard with notes"];

export function SearchView({ route: r }) {
  const q = (r.query.get("q") ?? "").trim();
  const [state, setState] = useState({ loading: !!q, data: null, error: null });
  const [slow, setSlow] = useState(false);

  // The very first search loads the recognition model, which takes a few seconds.
  useEffect(() => {
    setSlow(false);
    if (!state.loading) return;
    const t = setTimeout(() => setSlow(true), 2500);
    return () => clearTimeout(t);
  }, [state.loading, q]);

  useEffect(() => {
    if (!q) return setState({ loading: false, data: null, error: null });
    let live = true;
    setState({ loading: true, data: null, error: null });
    api
      .get(`/api/search?q=${encodeURIComponent(q)}`)
      .then((data) => live && setState({ loading: false, data, error: null }))
      .catch((error) => live && setState({ loading: false, data: null, error: error.message }));
    return () => {
      live = false;
    };
  }, [q]);

  const items = state.data?.items ?? [];
  const open = (item) =>
    openLightbox({ total: items.length, get: (i) => items[i], index: items.findIndex((x) => x.id === item.id) });

  return html`
    <div class="page wide">
      <div class="page-head">
        <div>
          <h1>${q ? `“${q}”` : "Search"}</h1>
          ${q && state.data?.ready && html`<p>${plural(items.length, "best match", "best matches")}. Search understands what's in a photo, not just its name.</p>`}
        </div>
      </div>

      ${!q &&
      html`<div class="empty">
        <span class="art"><${Icon} name="search" size="lg" /></span>
        <h2>Describe what you're looking for</h2>
        <p>Search finds photos and videos by what's in them. Try:</p>
        <div class="row wrap" style="justify-content:center">
          ${EXAMPLES.map((e) => html`<a class="chip" href=${href(`/search?q=${encodeURIComponent(e)}`)} key=${e}>${e}</a>`)}
        </div>
      </div>`}

      ${q && state.loading &&
      html`<div class="loading-row"><${Icon} name="loader-circle" spin />
        ${slow ? "Getting search ready. The first search takes a few seconds…" : "Searching your library…"}</div>`}
      ${state.error && html`<div class="notice error"><${Icon} name="circle-alert" /><span>${state.error}</span></div>`}

      ${state.data && !state.data.ready &&
      html`<div class="empty">
        <span class="art"><${Icon} name="info" size="lg" /></span>
        <h2>Search isn't set up yet</h2>
        <p>Searching by description needs the recognition model, which wasn't installed. Run Setup again to turn it on.</p>
      </div>`}

      ${state.data?.ready && items.length === 0 &&
      html`<div class="empty">
        <span class="art"><${Icon} name="image-off" size="lg" /></span>
        <h2>No matches</h2>
        <p>${jobs.scan.value?.state === "running" ? "A scan is still running, so some photos aren't searchable yet." : "Try describing it differently, for example the place, object or activity."}</p>
      </div>`}

      ${items.length > 0 &&
      html`<div class="grid" style="--cell:190px">
        ${items.map(
          (item) => html`<div class="search-cell" key=${item.id}>
            <${Thumb} item=${item} onOpen=${open} />
            ${item.kind === "video" && item.offset != null && html`<span class="badge bl at">at ${duration(item.offset)}</span>`}
          </div>`
        )}
      </div>`}
    </div>
  `;
}
