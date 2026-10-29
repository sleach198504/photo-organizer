import { signal } from "./html.js";

const KEY = "po-theme";

function stored() {
  try {
    return localStorage.getItem(KEY) || "system";
  } catch {
    return "system";
  }
}

export const themePref = signal(stored()); // "system" | "dark" | "light"

const query = matchMedia("(prefers-color-scheme: light)");

export function applyTheme() {
  const light = themePref.value === "light" || (themePref.value === "system" && query.matches);
  document.documentElement.dataset.theme = light ? "light" : "dark";
}

export function setTheme(pref) {
  themePref.value = pref;
  try {
    localStorage.setItem(KEY, pref);
  } catch {
    /* private mode etc. - the choice just won't persist */
  }
  applyTheme();
}

query.addEventListener("change", applyTheme);
