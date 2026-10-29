import { html, signal } from "../lib/html.js";
import { Icon } from "./icon.js";

const toasts = signal([]);
let nextId = 1;

/**
 * toast("Moved 12 items", { action: { label: "Undo", run }, kind: "success" | "error", timeout })
 * Undo beats confirmation for anything reversible, so actions get a long-enough window.
 */
export function toast(message, { kind = "info", action = null, timeout } = {}) {
  const id = nextId++;
  const ms = timeout ?? (action ? 9000 : kind === "error" ? 8000 : 4500);
  toasts.value = [...toasts.value, { id, message, kind, action }];
  if (ms > 0) setTimeout(() => dismiss(id), ms);
  return id;
}

export function dismiss(id) {
  toasts.value = toasts.value.filter((t) => t.id !== id);
}

const ICONS = { success: "circle-check", error: "circle-alert", info: "info" };

export function ToastHost() {
  return html`
    <div class="toasts" role="status" aria-live="polite">
      ${toasts.value.map(
        (t) => html`
          <div class=${`toast ${t.kind}`} key=${t.id}>
            <${Icon} name=${ICONS[t.kind] ?? "info"} />
            <span>${t.message}</span>
            ${t.action &&
            html`<button
              class="btn sm subtle"
              onClick=${() => {
                dismiss(t.id);
                t.action.run();
              }}
            >
              ${t.action.label}
            </button>`}
            <button class="icon-btn sm" aria-label="Dismiss" onClick=${() => dismiss(t.id)}>
              <${Icon} name="x" size="sm" />
            </button>
          </div>
        `
      )}
    </div>
  `;
}
