import { html, useEffect, useRef, useState } from "../lib/html.js";
import { media } from "../lib/api.js";
import { duration, bytes } from "../lib/format.js";
import { markOf, setMarks } from "../lib/store.js";
import { Icon } from "./icon.js";
import { thumbLabel, mayTakeFocus } from "../lib/a11y.js";

/**
 * One photo or video cell. Decisions are drawn on the picture itself: a red slash
 * means "remove", a green ring means "keep". Nothing else on the thumbnail is
 * colored, so the marks are what the eye finds first.
 *
 * Accessibility: the cell is a group named after the photo and its decision. Its one
 * way to open it is a real button covering the picture; the select check and the
 * keep/remove buttons are siblings of it, never nested inside it. `tab` says whether
 * the cell's buttons are in the Tab order. A grid sets it on one cell only (the keyboard
 * cursor), so Tab moves through the grid once and the arrow keys move within it.
 */
export function Thumb({
  item,
  selected = false,
  cursor = false,
  quick = true,
  keeper = false,
  showSize = false,
  fit = "cover",
  tab = true,
  onOpen,
  onPick,
  style,
  className = "",
}) {
  const [loaded, setLoaded] = useState(false);
  const opener = useRef(null);
  const mark = markOf(item);
  const tabIndex = tab ? 0 : -1;
  const label = thumbLabel(item, mark, keeper);

  // When the keyboard cursor lands here, so does real focus: that is what tells a screen
  // reader which photo the arrow keys have reached. It never takes focus from a field the
  // person is typing in.
  useEffect(() => {
    if (cursor && mayTakeFocus(document.activeElement)) opener.current?.focus({ preventScroll: true });
  }, [cursor]);

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
      role="group"
      aria-label=${label}
      data-id=${item.id}
      data-mark=${mark ?? ""}
      data-selected=${selected}
      data-cursor=${cursor}
      style=${style}
      onClick=${click}
    >
      <button type="button" class="thumb-open" ref=${opener} tabindex=${tabIndex} aria-label=${`Open ${label}`}>
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
      </button>
      ${mark === "remove" &&
      html`<svg class="slash" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><line x1="10" y1="90" x2="90" y2="10" /></svg>`}
      ${onPick &&
      html`<button
        type="button"
        class="pick"
        role="checkbox"
        tabindex=${tabIndex}
        aria-checked=${selected}
        aria-label=${`Select ${item.name}`}
        onClick=${(e) => {
          e.stopPropagation();
          onPick(item, e);
        }}
        ><${Icon} name="check" /></button
      >`}
      ${keeper && html`<span class="badge tl keeper-tag"><${Icon} name="star" /> Suggested keep</span>`}
      ${item.kind === "video" &&
      html`<span class="badge br"><${Icon} name="play" /> ${duration(item.dur)}</span>`}
      ${item.kind !== "video" && item.live && html`<span class="badge bl">Live</span>`}
      ${showSize && item.kind !== "video" && html`<span class="badge br">${bytes(item.size)}</span>`}
      ${quick &&
      html`<span class="quick">
        <button class="kp" tabindex=${tabIndex} aria-label=${`Keep ${item.name}`} aria-pressed=${mark === "keep"} onClick=${(e) => toggle("keep", e)}>
          <${Icon} name="check" size="sm" />
        </button>
        <button class="rm" tabindex=${tabIndex} aria-label=${`Remove ${item.name}`} aria-pressed=${mark === "remove"} onClick=${(e) => toggle("remove", e)}>
          <${Icon} name="x" size="sm" />
        </button>
      </span>`}
    </div>
  `;
}
