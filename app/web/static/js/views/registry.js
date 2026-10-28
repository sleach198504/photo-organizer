// Maps a route to its view. Views not built yet fall back to a placeholder so the
// shell can be exercised while the rest lands.
import { html } from "../lib/html.js";
import { HomeView } from "./home.js";
import { ScanView } from "./scan.js";
import { SettingsView } from "./settings.js";
import { ReviewView } from "./review.js";
import { RemovedView } from "./removed.js";

function Soon({ route }) {
  return html`<div class="page"><div class="empty"><h2>Coming up</h2><p>${route.path}</p></div></div>`;
}

const VIEWS = {
  "": HomeView,
  scan: ScanView,
  settings: SettingsView,
  review: ReviewView,
  removed: RemovedView,
};

export function routeView(route) {
  return VIEWS[route.parts[0] ?? ""] ?? Soon;
}
