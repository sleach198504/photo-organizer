import { html } from "../lib/html.js";

// Icons come from the bundled Lucide sprite (see dev/vendor/build.mjs for the list).
export function Icon({ name, size, spin, ...rest }) {
  const cls = `icon${size ? " " + size : ""}${spin ? " spin" : ""}`;
  return html`<svg class=${cls} aria-hidden="true" ...${rest}><use href=${`/static/icons/sprite.svg#i-${name}`} /></svg>`;
}
