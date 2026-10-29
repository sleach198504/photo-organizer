// Hash router: the whole app is one page, and the back button just works.
import { signal } from "./html.js";

export function parseHash(hash) {
  const raw = (hash || "").replace(/^#/, "") || "/";
  const [path, search = ""] = raw.split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  return { path: "/" + parts.join("/"), parts, query: new URLSearchParams(search) };
}

export const route = signal(parseHash(location.hash));

addEventListener("hashchange", () => {
  route.value = parseHash(location.hash);
});

export function go(path) {
  if (location.hash.replace(/^#/, "") === path) return;
  location.hash = path;
}

// Replace the current history entry (for filters and search text that shouldn't pile up in Back).
export function replace(path) {
  history.replaceState(null, "", "#" + path);
  route.value = parseHash(location.hash);
}

export function href(path) {
  return "#" + path;
}
