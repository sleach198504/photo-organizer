// Pure formatting helpers. No DOM access, so they can be unit-tested with `node --test`.

const UNITS = ["B", "KB", "MB", "GB", "TB"];

export function bytes(n) {
  if (n == null || Number.isNaN(n)) return "";
  let value = Math.max(0, n);
  let unit = 0;
  while (value >= 1000 && unit < UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const digits = unit === 0 || value >= 100 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} ${UNITS[unit]}`;
}

export function count(n) {
  return (n ?? 0).toLocaleString("en-US");
}

export function plural(n, one, many = `${one}s`) {
  return `${count(n)} ${n === 1 ? one : many}`;
}

export function duration(seconds) {
  if (seconds == null) return "";
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (v) => String(v).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

// "about 3 minutes", "under a minute" - for ETAs, where false precision reads as noise.
export function eta(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return "";
  if (seconds < 45) return "under a minute left";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `about ${minutes} minute${minutes === 1 ? "" : "s"} left`;
  const hours = Math.round((seconds / 3600) * 2) / 2;
  return `about ${hours} hour${hours === 1 ? "" : "s"} left`;
}

export function elapsed(seconds) {
  const total = Math.max(0, Math.round(seconds ?? 0));
  if (total < 60) return `${total}s`;
  const m = Math.floor(total / 60);
  return `${m}m ${String(total % 60).padStart(2, "0")}s`;
}

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export function monthLabel(ym) {
  if (!ym || ym.length < 7) return "Undated";
  const m = Number(ym.slice(5, 7));
  return `${MONTHS[m - 1] ?? ym.slice(5, 7)} ${ym.slice(0, 4)}`;
}

function parse(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function dateLong(iso) {
  const d = parse(iso);
  return d ? d.toLocaleDateString("en-US", { weekday: "short", month: "long", day: "numeric", year: "numeric" }) : "Unknown date";
}

export function dateShort(iso) {
  const d = parse(iso);
  return d ? d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";
}

export function timeOfDay(iso) {
  const d = parse(iso);
  return d ? d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }) : "";
}

// "Jul 4 – 9, 2025" / "Dec 28, 2024 – Jan 3, 2025" for trips and video sessions.
export function dateRange(startIso, endIso) {
  const a = parse(startIso);
  const b = parse(endIso);
  if (!a) return "";
  if (!b || a.toDateString() === b.toDateString()) return dateShort(startIso);
  const sameYear = a.getFullYear() === b.getFullYear();
  const sameMonth = sameYear && a.getMonth() === b.getMonth();
  const mon = (d) => d.toLocaleDateString("en-US", { month: "short" });
  if (sameMonth) return `${mon(a)} ${a.getDate()} – ${b.getDate()}, ${b.getFullYear()}`;
  if (sameYear) return `${mon(a)} ${a.getDate()} – ${mon(b)} ${b.getDate()}, ${b.getFullYear()}`;
  return `${dateShort(startIso)} – ${dateShort(endIso)}`;
}

export function ago(iso, now = Date.now()) {
  const d = parse(iso);
  if (!d) return "";
  const seconds = Math.round((now - d.getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
  return dateShort(iso);
}

export function megapixels(w, h) {
  return w && h ? `${((w * h) / 1e6).toFixed(1)} MP` : "";
}

export function baseName(path) {
  return String(path ?? "").split(/[\\/]/).filter(Boolean).pop() ?? "";
}
