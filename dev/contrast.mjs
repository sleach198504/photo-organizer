// WCAG contrast check for the design tokens. Run: node dev/contrast.mjs
// Text needs 4.5:1 (3:1 for large text and UI components).
const themes = {
  dark: {
    bg: "#151618", side: "#1a1b1e", surface: "#202225", surface2: "#282a2e", surface3: "#313439",
    text: "#ebecee", text2: "#aeb2b9", text3: "#868b93",
    accent: "#6ea8e6", accentInk: "#0b1826", keep: "#6cc08a", remove: "#ec5b4d", warn: "#e3b04b",
    onKeep: "#04180c", onRemove: "#1a0705", line: "#7b8088",
  },
  light: {
    bg: "#f3f4f5", side: "#eceef0", surface: "#ffffff", surface2: "#f6f7f8", surface3: "#eceef0",
    text: "#1b1d21", text2: "#4f555e", text3: "#666c75",
    accent: "#1f5fa8", accentInk: "#ffffff", keep: "#2a7d4c", remove: "#c8372b", warn: "#8f6200",
    onKeep: "#ffffff", onRemove: "#ffffff", line: "#868c95",
  },
};

const lum = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

let failures = 0;
for (const [name, t] of Object.entries(themes)) {
  const checks = [
    ["text on bg", t.text, t.bg, 4.5], ["text on surface", t.text, t.surface, 4.5], ["text on surface3", t.text, t.surface3, 4.5],
    ["text-2 on bg", t.text2, t.bg, 4.5], ["text-2 on surface", t.text2, t.surface, 4.5], ["text-2 on surface3", t.text2, t.surface3, 4.5],
    ["text-3 on bg", t.text3, t.bg, 4.5], ["text-3 on surface", t.text3, t.surface, 4.5], ["text-3 on sidebar", t.text3, t.side, 4.5],
    ["accent text on bg", t.accent, t.bg, 4.5], ["accent text on surface", t.accent, t.surface, 4.5],
    ["button label on accent", t.accentInk, t.accent, 4.5],
    ["keep text on bg", t.keep, t.bg, 4.5], ["remove text on bg", t.remove, t.bg, 4.5], ["warn text on bg", t.warn, t.bg, 4.5],
    ["label on keep fill", t.onKeep, t.keep, 4.5], ["label on remove fill", t.onRemove, t.remove, 4.5],
    ["input border on surface (UI)", t.line, t.surface, 3],
  ];
  console.log(`\n${name}`);
  for (const [label, fg, bg, min] of checks) {
    const r = ratio(fg, bg);
    const ok = r >= min;
    if (!ok) failures += 1;
    console.log(`  ${ok ? "ok  " : "FAIL"} ${r.toFixed(2).padStart(5)}  (min ${min})  ${label}`);
  }
}
process.exit(failures ? 1 : 0);
