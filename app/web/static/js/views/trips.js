import { html, useEffect, useState } from "../lib/html.js";
import { api, media } from "../lib/api.js";
import { dataVersion, refreshSummary } from "../lib/store.js";
import { dateRange, plural } from "../lib/format.js";
import { Icon } from "../ui/icon.js";
import { toast } from "../ui/toast.js";
import { openLightbox } from "../ui/lightbox.js";

function TripCard({ trip, ignored, onChange }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(trip.name);

  useEffect(() => setName(trip.name), [trip.name]);

  async function save() {
    setEditing(false);
    const next = name.trim();
    if (!next || next === trip.name) return setName(trip.name);
    try {
      await api.put(`/api/trips/${trip.id}/name`, { name: next });
      onChange();
    } catch (error) {
      toast(error.message, { kind: "error" });
      setName(trip.name);
    }
  }

  async function toggleIgnore() {
    try {
      await api.post(`/api/trips/${trip.id}/${ignored ? "restore" : "ignore"}`);
      toast(ignored ? "Trip restored" : "Marked as not a trip", {
        kind: "success",
        action: { label: "Undo", run: () => api.post(`/api/trips/${trip.id}/${ignored ? "ignore" : "restore"}`).then(onChange) },
      });
      onChange();
    } catch (error) {
      toast(error.message, { kind: "error" });
    }
  }

  const open = (index) =>
    openLightbox({ total: trip.samples.length, get: (i) => trip.samples[i], index, marking: false });

  return html`
    <article class="panel trip">
      <div class="trip-photos">
        ${trip.samples.slice(0, 4).map(
          (item, i) => html`<button class="trip-photo" onClick=${() => open(i)} key=${item.id} aria-label=${`Open ${item.name}`}>
            <img src=${media.thumb(item)} alt="" loading="lazy" />
          </button>`
        )}
      </div>
      <div class="trip-body">
        ${editing
          ? html`<input
              class="input"
              autofocus
              value=${name}
              aria-label="Folder name"
              onInput=${(e) => setName(e.target.value)}
              onBlur=${save}
              onKeyDown=${(e) => {
                if (e.key === "Enter") save();
                if (e.key === "Escape") {
                  setName(trip.name);
                  setEditing(false);
                }
                e.stopPropagation();
              }}
            />`
          : html`<h3 class="trip-name">${trip.name}</h3>`}
        <div class="faint">
          ${dateRange(trip.start, trip.end)} · ${plural(trip.count, "photo")}
          <span class=${`pill ${trip.kind === "vacation" ? "accent" : ""}`} style="margin-left:8px">${trip.kind === "vacation" ? "Multi-day trip" : "Day trip"}</span>
        </div>
        <div class="row">
          ${!ignored && html`<button class="btn sm" onClick=${() => setEditing(true)}><${Icon} name="pencil" size="sm" /> Rename</button>`}
          <button class="btn sm subtle" onClick=${toggleIgnore}>${ignored ? "Count as a trip again" : "Not a trip"}</button>
        </div>
      </div>
    </article>
  `;
}

export function TripsView() {
  const [tab, setTab] = useState("pending");
  const [trips, setTrips] = useState(null);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const version = dataVersion.value;

  useEffect(() => {
    let live = true;
    setTrips(null);
    api.get(`/api/trips?status=${tab}`).then((t) => live && setTrips(t)).catch((e) => live && toast(e.message, { kind: "error" }));
    return () => {
      live = false;
    };
  }, [tab, tick, version]);

  const changed = () => {
    setTick((n) => n + 1);
    refreshSummary().catch(() => {});
  };

  async function detect() {
    setBusy(true);
    try {
      await api.post("/api/trips/detect");
      toast("Looked for trips again", { kind: "success", timeout: 2500 });
      changed();
    } catch (error) {
      toast(error.message, { kind: "error" });
    } finally {
      setBusy(false);
    }
  }

  return html`
    <div class="page narrow stack">
      <div class="page-head">
        <div>
          <h1>Trips</h1>
          <p>
            Photo Organizer notices when you were away from home, using the location saved in your photos. When you
            organize, each trip gets its own named folder.
          </p>
        </div>
        <button class="btn" disabled=${busy} onClick=${detect}><${Icon} name="refresh-cw" spin=${busy} /> Look again</button>
      </div>
      <div class="segmented" role="radiogroup" aria-label="Which trips" style="justify-self:start">
        <button role="radio" aria-checked=${tab === "pending"} onClick=${() => setTab("pending")}>Trips</button>
        <button role="radio" aria-checked=${tab === "ignored"} onClick=${() => setTab("ignored")}>Not trips</button>
      </div>
      ${trips == null
        ? html`<div class="loading-row"><${Icon} name="loader-circle" spin /> Loading…</div>`
        : trips.length === 0
          ? html`<div class="empty">
              <span class="art"><${Icon} name="plane" size="lg" /></span>
              <h2>${tab === "pending" ? "No trips found" : "Nothing here"}</h2>
              <p>
                ${tab === "pending"
                  ? "Trips are found from photos that have a location. If yours don't, they'll just be filed by month."
                  : "Trips you mark as \"not a trip\" are listed here so you can bring them back."}
              </p>
            </div>`
          : html`<div class="stack tight">${trips.map((t) => html`<${TripCard} trip=${t} ignored=${tab === "ignored"} onChange=${changed} key=${t.id} />`)}</div>`}
    </div>
  `;
}
