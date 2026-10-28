import { html, useState } from "../lib/html.js";
import { media } from "../lib/api.js";
import { duration, bytes } from "../lib/format.js";
import { markOf, setMarks } from "../lib/store.js";
import { Icon } from "./icon.js";

/**
 * One photo or video cell. Decisions are drawn on the picture itself: a red slash
 * means "remove", a green ring means "keep". Nothing else on the thumbnail is
 * colored, so the marks are what the eye finds first.
 */
export function Thumb({
  item,
  selected = false,
  cursor = false,
  quick = true,
  keeper = false,
  showSize = false,
  fit = "cover",
  onOpen,
  onPick,
  style,
  className = "",
}) {
  const [loaded, setLoaded] = useState(false);
  const mark = markOf(item);

  function toggle(target, event) {
    event.stopPropagation();
    setMarks([item], mark === target ? null : target, { undoable: false });
  }

  function click(event) {
    if (onPick && (event.ctrlKey || event.metaKey || event.shiftKey)) {
      event.preventDefault();
      onPick(item, event);
      return;
    }
    onOpen?.(item, event);
  }

  return html`
    <div
      class=${`thumb ${className}`}
      role="button"
      tabindex="-1"
      data-id=${item.id}
      data-mark=${mark ?? ""}
      data-selected=${selected}
      data-cursor=${cursor}
      style=${style}
      onClick=${click}
      aria-label=${`${item.name}${mark ? `, marked ${mark}` : ""}`}
    >
      <img
        class=${loaded ? "" : "loading"}
        style=${fit === "contain" ? "object-fit:contain" : ""}
        src=${media.thumb(item)}
        alt=""
        loading="lazy"
        decoding="async"
        draggable="false"
        onLoad=${() => setLoaded(true)}
        onError=${() => setLoaded(true)}
      />
      ${mark === "remove" &&
      html`<svg class="slash" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><line x1="10" y1="90" x2="90" y2="10" /></svg>`}
      ${onPick &&
      html`<span
        class="pick"
        role="checkbox"
        aria-checked=${selected}
        onClick=${(e) => {
          e.stopPropagation();
          onPick(item, e);
        }}
        ><${Icon} name="check" /></span
      >`}
      ${keeper && html`<span class="badge tl keeper-tag"><${Icon} name="star" /> Suggested keep</span>`}
      ${item.kind === "video" &&
      html`<span class="badge br"><${Icon} name="play" /> ${duration(item.dur)}</span>`}
      ${item.kind !== "video" && item.live && html`<span class="badge bl">Live</span>`}
      ${showSize && item.kind !== "video" && html`<span class="badge br">${bytes(item.size)}</span>`}
      ${quick &&
      html`<span class="quick">
        <button class="kp" aria-label="Keep" aria-pressed=${mark === "keep"} onClick=${(e) => toggle("keep", e)}>
          <${Icon} name="check" size="sm" />
        </button>
        <button class="rm" aria-label="Remove" aria-pressed=${mark === "remove"} onClick=${(e) => toggle("remove", e)}>
          <${Icon} name="x" size="sm" />
        </button>
      </span>`}
    </div>
  `;
}
