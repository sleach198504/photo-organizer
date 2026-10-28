import { html, signal, useEffect, useRef, useState } from "../lib/html.js";
import { api, media } from "../lib/api.js";
import { markOf, setMarks } from "../lib/store.js";
import { bytes, dateLong, timeOfDay, megapixels, duration } from "../lib/format.js";
import { REASON_LABELS } from "../lib/labels.js";
import { useHotkeys } from "../lib/keys.js";
import { Icon } from "./icon.js";
import { toast } from "./toast.js";

/**
 * Full-window viewer. Opened from any grid with a `source` that can hand out items
 * by index, so it can step through a 50,000-photo library without loading it all:
 *
 *   openLightbox({ total, get: (i) => item | undefined, ensure: (i) => void, index,
 *                  peersOf?: (item) => item[], marking?: boolean, onIndex?: (i) => void })
 */
export const lightbox = signal(null);

export function openLightbox(options) {
  lightbox.value = { marking: true, ...options };
}

export function closeLightbox() {
  lightbox.value = null;
}

export function LightboxHost() {
  const box = lightbox.value;
  return box ? html`<${Lightbox} ...${box} />` : null;
}

function preload(item) {
  if (item && item.kind !== "video") new Image().src = media.preview(item);
}

function Lightbox({ total, get, ensure, index: startIndex, peersOf, marking, onIndex }) {
  const [index, setIndex] = useState(startIndex);
  const [zoom, setZoom] = useState(false);
  const [info, setInfo] = useState(false);
  const [compare, setCompare] = useState(false);
  const [detail, setDetail] = useState(null);
  const item = get(index);
  const stage = useRef(null);

  useEffect(() => {
    ensure?.(index);
    onIndex?.(index);
    preload(get(index + 1));
    preload(get(index - 1));
    setZoom(false);
  }, [index]);

  // Poll briefly for items that weren't loaded when we arrived (sparse lists).
  const [, force] = useState(0);
  useEffect(() => {
    if (item) return;
    const t = setInterval(() => force((n) => n + 1), 150);
    return () => clearInterval(t);
  }, [item, index]);

  useEffect(() => {
    if (!info || !item) return;
    let live = true;
    setDetail(null);
    api.get(`/api/photo/${item.id}`).then((d) => live && setDetail(d)).catch(() => {});
    return () => {
      live = false;
    };
  }, [info, item?.id]);

  const go = (delta) => setIndex((i) => Math.min(total - 1, Math.max(0, i + delta)));
  const mark = (value, advance = true) => {
    if (!item || !marking) return;
    setMarks([item], markOf(item) === value ? null : value, { undoable: false });
    if (advance && value && index < total - 1) setTimeout(() => go(1), 120);
  };

  const peers = item && peersOf ? peersOf(item) : null;
  const rival =
    item && peers?.length > 1
      ? (peers.find((p) => p.keeper && p.id !== item.id) ?? peers.find((p) => p.id !== item.id))
      : null;

  useHotkeys(
    {
      escape: () => (compare ? setCompare(false) : closeLightbox()),
      arrowleft: () => go(-1),
      arrowright: () => go(1),
      arrowup: () => go(-1),
      arrowdown: () => go(1),
      k: () => mark("keep"),
      x: () => mark("remove"),
      delete: () => mark("remove"),
      u: () => mark(null, false),
      z: () => item?.kind !== "video" && setZoom((v) => !v),
      i: () => setInfo((v) => !v),
      c: () => rival && setCompare((v) => !v),
    },
    { modal: true }
  );

  const current = item ? markOf(item) : null;

  return html`
    <div class="lightbox" role="dialog" aria-modal="true" aria-label="Photo viewer">
      <header class="lb-top">
        <button class="icon-btn" aria-label="Close" onClick=${closeLightbox}><${Icon} name="arrow-left" /></button>
        <div class="lb-title">
          <b class="truncate">${item?.name ?? "Loading…"}</b>
          <span class="faint">${item ? `${dateLong(item.date)} · ${timeOfDay(item.date)}` : ""}</span>
        </div>
        <span class="spacer"></span>
        <span class="num faint">${index + 1} of ${total}</span>
        ${rival &&
        html`<button class="icon-btn" aria-label="Compare" aria-pressed=${compare} title="Compare with the suggested keep (C)" onClick=${() => setCompare(!compare)}>
          <${Icon} name="columns-2" />
        </button>`}
        ${item?.kind !== "video" &&
        html`<button class="icon-btn" aria-label="Zoom to 100%" aria-pressed=${zoom} title="Actual size (Z)" onClick=${() => setZoom(!zoom)}>
          <${Icon} name=${zoom ? "minimize-2" : "zoom-in"} />
        </button>`}
        <button class="icon-btn" aria-label="Details" aria-pressed=${info} title="Details (I)" onClick=${() => setInfo(!info)}>
          <${Icon} name="info" />
        </button>
      </header>

      <div class="lb-body">
        <div class="lb-stage-wrap">
          ${index > 0 && html`<button class="lb-nav prev" aria-label="Previous" onClick=${() => go(-1)}><${Icon} name="chevron-left" size="lg" /></button>`}
          ${index < total - 1 && html`<button class="lb-nav next" aria-label="Next" onClick=${() => go(1)}><${Icon} name="chevron-right" size="lg" /></button>`}
          ${!item
            ? html`<div class="lb-stage"><${Icon} name="loader-circle" size="lg" spin /></div>`
            : compare && rival
              ? html`<${CompareStage} a=${item} b=${rival} zoom=${zoom} />`
              : item.kind === "video"
                ? html`<div class="lb-stage"><video key=${item.id} src=${media.video(item)} controls autoplay=${false} class="lb-video"></video></div>`
                : html`<${ImageStage} item=${item} zoom=${zoom} onToggle=${() => setZoom(!zoom)} />`}
          ${current && html`<div class=${`lb-flag ${current}`}>${current === "remove" ? "Marked to remove" : "Marked to keep"}</div>`}
        </div>
        ${info && html`<${InfoPanel} item=${item} detail=${detail} />`}
      </div>

      ${marking &&
      html`<footer class="lb-bottom">
        <button class=${`btn lg lb-btn keep${current === "keep" ? " on" : ""}`} onClick=${() => mark("keep")}>
          <${Icon} name="check" /> Keep <kbd>K</kbd>
        </button>
        <button class=${`btn lg lb-btn remove${current === "remove" ? " on" : ""}`} onClick=${() => mark("remove")}>
          <${Icon} name="x" /> Remove <kbd>X</kbd>
        </button>
        ${current && html`<button class="btn subtle lg" onClick=${() => mark(null, false)}>Clear <kbd>U</kbd></button>`}
      </footer>`}
    </div>
  `;
}

function ImageStage({ item, zoom, onToggle }) {
  const box = useRef(null);
  const drag = useRef(null);
  const [ready, setReady] = useState(false);
  const [full, setFull] = useState(false);

  useEffect(() => {
    setReady(false);
    setFull(false);
  }, [item.id]);

  // Centre the picture when zoomed in.
  useEffect(() => {
    if (zoom && box.current) {
      const b = box.current;
      b.scrollLeft = (b.scrollWidth - b.clientWidth) / 2;
      b.scrollTop = (b.scrollHeight - b.clientHeight) / 2;
    }
  }, [zoom, full]);

  const down = (e) => {
    if (!zoom) return;
    drag.current = { x: e.clientX, y: e.clientY, l: box.current.scrollLeft, t: box.current.scrollTop, moved: false };
    box.current.setPointerCapture(e.pointerId);
  };
  const move = (e) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
    box.current.scrollLeft = d.l - dx;
    box.current.scrollTop = d.t - dy;
  };
  const up = () => {
    const d = drag.current;
    drag.current = null;
    if (!d?.moved) onToggle();
  };

  return html`
    <div class=${`lb-stage${zoom ? " zoomed" : ""}`} ref=${box} onPointerDown=${down} onPointerMove=${move} onPointerUp=${up}>
      ${!ready && html`<div class="lb-spinner"><${Icon} name="loader-circle" size="lg" spin /></div>`}
      <img
        key=${item.id + (zoom ? "z" : "f")}
        src=${zoom ? media.original(item) : media.preview(item)}
        alt=${item.name}
        draggable="false"
        class=${ready ? "" : "pending"}
        onLoad=${() => {
          setReady(true);
          setFull(zoom);
        }}
        onClick=${(e) => !zoom && (e.stopPropagation(), onToggle())}
      />
    </div>
  `;
}

function CompareStage({ a, b, zoom }) {
  const left = useRef(null);
  const right = useRef(null);
  const syncing = useRef(false);

  // Keep both panes panned together when zoomed, so the same detail lines up.
  const sync = (from, to) => () => {
    if (syncing.current || !zoom) return;
    syncing.current = true;
    to.current.scrollLeft = from.current.scrollLeft;
    to.current.scrollTop = from.current.scrollTop;
    requestAnimationFrame(() => (syncing.current = false));
  };

  const pane = (item, ref, other, label) => html`
    <figure class="cmp-pane">
      <div class=${`cmp-img${zoom ? " zoomed" : ""}`} ref=${ref} onScroll=${sync(ref, other)}>
        <img src=${zoom ? media.original(item) : media.preview(item)} alt=${item.name} draggable="false" />
      </div>
      <figcaption>
        <span class=${`pill ${item.keeper ? "keep" : ""}`}>${label}</span>
        <span class="num">${megapixels(item.w, item.h)} · ${bytes(item.size)}${item.blur != null ? ` · sharpness ${item.blur}` : ""}</span>
      </figcaption>
    </figure>
  `;

  return html`
    <div class="lb-compare">
      ${pane(a, left, right, a.keeper ? "Suggested keep" : "This photo")}
      ${pane(b, right, left, b.keeper ? "Suggested keep" : "Other photo")}
    </div>
  `;
}

function Row({ label, children }) {
  return html`<div class="info-row"><dt>${label}</dt><dd>${children}</dd></div>`;
}

function InfoPanel({ item, detail }) {
  if (!item) return null;
  async function reveal() {
    try {
      await api.post(`/api/reveal/${item.id}`);
    } catch (error) {
      toast(error.message, { kind: "error" });
    }
  }
  return html`
    <aside class="lb-info" aria-label="Details">
      <h3>Details</h3>
      <dl>
        <${Row} label="File">${item.name}<//>
        <${Row} label="Taken">${dateLong(item.date)} ${timeOfDay(item.date)}<//>
        <${Row} label="Size">${bytes(item.size)}<//>
        ${item.w && html`<${Row} label="Dimensions">${item.w} × ${item.h} (${megapixels(item.w, item.h)})<//>`}
        ${item.kind === "video" && html`<${Row} label="Length">${duration(item.dur)}<//>`}
        ${item.blur != null && html`<${Row} label="Sharpness">${item.blur}<//>`}
        ${detail?.camera && html`<${Row} label="Camera">${detail.camera}<//>`}
        ${detail?.gps && html`<${Row} label="Location">${detail.gps[0].toFixed(4)}, ${detail.gps[1].toFixed(4)}<//>`}
        ${detail?.folder && html`<${Row} label="Folder"><span class="path">${detail.folder}</span><//>`}
      </dl>
      ${detail?.reasons?.length > 0 &&
      html`<div class="stack tight">
        <h3>Why it was flagged</h3>
        <div class="row wrap">${detail.reasons.map((r) => html`<span class="pill" key=${r}>${REASON_LABELS[r] ?? r}</span>`)}</div>
      </div>`}
      <button class="btn" onClick=${reveal}><${Icon} name="folder-open" /> Show in folder</button>
    </aside>
  `;
}
