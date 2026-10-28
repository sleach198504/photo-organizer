import { html, signal, useEffect, useRef, useState } from "../lib/html.js";
import { useHotkeys } from "../lib/keys.js";

const current = signal(null);

/**
 * confirm({ title, body, confirmLabel, cancelLabel, danger, requireText })
 * Resolves true/false. Reserved for things that can't be undone - everything
 * reversible uses a toast with Undo instead.
 */
export function confirm(options) {
  return new Promise((resolve) => {
    current.value = { ...options, resolve };
  });
}

function close(result) {
  const dialog = current.value;
  current.value = null;
  dialog?.resolve(result);
}

export function DialogHost() {
  const dialog = current.value;
  if (!dialog) return null;
  return html`<${Dialog} ...${dialog} key=${dialog.title} />`;
}

function Dialog({ title, body, confirmLabel = "OK", cancelLabel = "Cancel", danger, requireText, wide, hideCancel }) {
  const [typed, setTyped] = useState("");
  const ref = useRef(null);
  const opener = useRef(document.activeElement);
  const ready = !requireText || typed.trim() === requireText;

  // Enter confirms, except when a button has focus (then Enter should press that button).
  useHotkeys(
    {
      escape: () => close(false),
      enter: (e) => (e.target.tagName === "BUTTON" || !ready ? false : close(true)),
    },
    { modal: true }
  );

  useEffect(() => {
    const target = ref.current?.querySelector("input") ?? ref.current?.querySelector(".btn:not(.subtle)");
    target?.focus();
    return () => opener.current?.focus?.();
  }, []);

  // Keep Tab inside the dialog.
  function trap(event) {
    if (event.key !== "Tab") return;
    const focusable = ref.current.querySelectorAll("button:not([disabled]), input, [href]");
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      last.focus();
      event.preventDefault();
    } else if (!event.shiftKey && document.activeElement === last) {
      first.focus();
      event.preventDefault();
    }
  }

  return html`
    <div class="scrim" onMouseDown=${(e) => e.target === e.currentTarget && close(false)}>
      <div class=${`dialog${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label=${title} ref=${ref} onKeyDown=${trap}>
        <h2>${title}</h2>
        <div class="body">
          ${typeof body === "function" ? body() : body}
          ${requireText &&
          html`<div class="field">
            <label for="confirm-text">Type <b>${requireText}</b> to confirm</label>
            <input id="confirm-text" class="input" autocomplete="off" value=${typed} onInput=${(e) => setTyped(e.target.value)} />
          </div>`}
        </div>
        <div class="actions">
          ${!hideCancel && html`<button class="btn" onClick=${() => close(false)}>${cancelLabel}</button>`}
          <button class=${`btn ${danger ? "danger" : "primary"}`} disabled=${!ready} onClick=${() => close(true)}>
            ${confirmLabel}
          </button>
        </div>
      </div>
    </div>
  `;
}
