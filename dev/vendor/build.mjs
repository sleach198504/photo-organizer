// Copies the pinned UI runtime, font and icons into app/web/static.
// Licenses: preact/htm/@preact/signals MIT, lucide ISC, Figtree OFL-1.1 (copied alongside).
import { copyFileSync, mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const nm = join(here, "node_modules");
const out = resolve(here, "..", "..", "app", "web", "static");

const copy = (from, to) => {
  mkdirSync(dirname(to), { recursive: true });
  copyFileSync(from, to);
};

// --- JS runtime (import-mapped in index.html) ---
const js = join(out, "js", "vendor");
copy(join(nm, "preact/dist/preact.module.js"), join(js, "preact.module.js"));
copy(join(nm, "preact/hooks/dist/hooks.module.js"), join(js, "hooks.module.js"));
copy(join(nm, "htm/dist/htm.module.js"), join(js, "htm.module.js"));
copy(join(nm, "@preact/signals/dist/signals.module.js"), join(js, "signals.module.js"));
copy(join(nm, "@preact/signals-core/dist/signals-core.module.js"), join(js, "signals-core.module.js"));
for (const [pkg, name] of [["preact", "preact"], ["htm", "htm"], ["@preact/signals", "signals"]]) {
  const license = join(nm, pkg, "LICENSE");
  if (existsSync(license)) copy(license, join(js, `LICENSE-${name}.txt`));
}

// --- Font ---
copy(
  join(nm, "@fontsource-variable/figtree/files/figtree-latin-wght-normal.woff2"),
  join(out, "fonts", "figtree-latin-wght-normal.woff2")
);
copy(join(nm, "@fontsource-variable/figtree/LICENSE"), join(out, "fonts", "OFL-Figtree.txt"));

// --- Icon sprite: only the icons the UI uses ---
const icons = [
  "house", "images", "image", "video", "plane", "search", "copy", "layers", "focus", "smartphone",
  "file-text", "presentation", "utensils", "sticker", "square-dashed", "film", "monitor-play",
  "trash-2", "undo-2", "folder-tree", "folder-open", "folder", "settings", "scan-search", "play",
  "pause", "x", "check", "chevron-right", "chevron-left", "chevron-down", "chevron-up",
  "arrow-left", "arrow-right", "arrow-up-right", "maximize-2", "minimize-2", "zoom-in", "zoom-out",
  "info", "keyboard", "sun", "moon", "monitor", "refresh-cw", "circle-alert", "triangle-alert",
  "circle-check", "loader-circle", "log-out", "panel-left", "wand-sparkles", "list-checks",
  "columns-2", "eye", "sliders-horizontal", "arrow-up-down", "calendar", "map-pin", "camera",
  "hard-drive", "external-link", "plus", "minus", "circle", "ban", "shield-check", "history",
  "sparkles", "cpu", "zap", "download", "image-off", "user", "user-x", "tag", "rotate-ccw",
  "inbox", "circle-dashed", "square-check", "square", "grip", "ellipsis", "pencil", "link-2",
  "volume-2", "volume-x", "step-forward", "step-back", "git-compare", "flag", "star",
];
const missing = [];
const symbols = [];
for (const name of icons) {
  const file = join(nm, "lucide-static", "icons", `${name}.svg`);
  if (!existsSync(file)) { missing.push(name); continue; }
  const svg = readFileSync(file, "utf8");
  const inner = svg.replace(/^[\s\S]*?<svg[^>]*>/, "").replace(/<\/svg>\s*$/, "").trim();
  symbols.push(`<symbol id="i-${name}" viewBox="0 0 24 24">${inner}</symbol>`);
}
mkdirSync(join(out, "icons"), { recursive: true });
writeFileSync(
  join(out, "icons", "sprite.svg"),
  `<svg xmlns="http://www.w3.org/2000/svg" style="display:none">\n${symbols.join("\n")}\n</svg>\n`
);
copy(join(nm, "lucide-static", "LICENSE"), join(out, "icons", "LICENSE-lucide.txt"));
console.log(`vendored: ${symbols.length} icons${missing.length ? ", MISSING: " + missing.join(", ") : ""}`);
