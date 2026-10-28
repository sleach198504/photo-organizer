// Scoped keyboard shortcuts. Each mounted view/overlay registers a map; the most
// recently mounted one gets first refusal, so the lightbox's arrow keys never fight
// the grid underneath it.
import { useEffect, useRef } from "./html.js";

const stack = [];

function describe(event) {
  let key = event.key;
  if (key === " ") key = "space";
  key = key.length === 1 ? key.toLowerCase() : key.toLowerCase();
  const mods = [];
  if (event.ctrlKey || event.metaKey) mods.push("ctrl");
  if (event.altKey) mods.push("alt");
  // Shift is encoded in the character for symbols ("?"), but matters for arrows/letters.
  if (event.shiftKey && (key.length > 1 || /[a-z]/.test(key))) mods.push("shift");
  return [...mods, key].join("+");
}

function typingTarget(target) {
  if (!target) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

addEventListener("keydown", (event) => {
  if (event.defaultPrevented) return;
  const combo = describe(event);
  const typing = typingTarget(event.target);
  for (let i = stack.length - 1; i >= 0; i--) {
    const entry = stack[i];
    if (!entry.active.current) continue;
    const handler = entry.map.current[combo];
    if (!handler) {
      if (entry.modal.current) return; // a modal scope swallows nothing but also lets nothing through
      continue;
    }
    if (typing && combo !== "escape") continue;
    if (handler(event) !== false) {
      event.preventDefault();
      return;
    }
  }
});

/**
 * useHotkeys({ "arrowleft": fn, "shift+arrowright": fn, "escape": fn })
 * Handlers may return false to let the key fall through to the next scope.
 */
export function useHotkeys(map, { active = true, modal = false } = {}) {
  const mapRef = useRef(map);
  const activeRef = useRef(active);
  const modalRef = useRef(modal);
  mapRef.current = map;
  activeRef.current = active;
  modalRef.current = modal;

  useEffect(() => {
    const entry = { map: mapRef, active: activeRef, modal: modalRef };
    stack.push(entry);
    return () => {
      const index = stack.indexOf(entry);
      if (index >= 0) stack.splice(index, 1);
    };
  }, []);
}
