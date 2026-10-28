import { html, signal } from "../lib/html.js";
import { useHotkeys } from "../lib/keys.js";

const open = signal(false);
export const showShortcuts = () => (open.value = true);

const GROUPS = [
  {
    title: "Anywhere",
    keys: [
      ["/", "Search"],
      ["?", "Show this list"],
      ["g then h", "Go to Home"],
      ["g then r", "Go to Review"],
      ["g then p", "Go to Photos"],
    ],
  },
  {
    title: "Reviewing",
    keys: [
      ["← → ↑ ↓", "Move between photos"],
      ["X", "Mark to remove"],
      ["K", "Keep this photo"],
      ["U", "Clear the mark"],
      ["Space or Enter", "Open larger"],
      ["Shift + click", "Select a range"],
      ["Ctrl + A", "Select the whole category"],
    ],
  },
  {
    title: "Viewing a photo",
    keys: [
      ["← →", "Previous or next"],
      ["Z", "Zoom to 100%"],
      ["I", "Photo details"],
      ["C", "Compare with the keeper"],
      ["Esc", "Close"],
    ],
  },
];

export function ShortcutsHost() {
  useHotkeys({ "?": () => (open.value = true) });
  useHotkeys({ escape: () => (open.value = false), "?": () => (open.value = false) }, { active: open.value, modal: true });
  if (!open.value) return null;
  return html`
    <div class="scrim" onMouseDown=${(e) => e.target === e.currentTarget && (open.value = false)}>
      <div class="dialog wide" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts">
        <h2>Keyboard shortcuts</h2>
        <div class="shortcut-grid">
          ${GROUPS.map(
            (g) => html`
              <section>
                <h3>${g.title}</h3>
                <dl>
                  ${g.keys.map(
                    ([k, label]) => html`<dt>${k.split(" ").map((part) => (/^(then|or|\+)$/.test(part) ? ` ${part} ` : html`<kbd>${part}</kbd>`))}</dt><dd>${label}</dd>`
                  )}
                </dl>
              </section>
            `
          )}
        </div>
        <div class="actions"><button class="btn primary" onClick=${() => (open.value = false)}>Done</button></div>
      </div>
    </div>
  `;
}
