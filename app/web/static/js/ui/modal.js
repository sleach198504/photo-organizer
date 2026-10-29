import { useEffect } from "../lib/html.js";
import { wrapTab } from "../lib/a11y.js";

const FOCUSABLE =
  'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), video[controls], [tabindex]:not([tabindex="-1"])';

let openModals = 0;

/**
 * Everything a modal window needs to be usable without a mouse. While it is open the rest of
 * the app is made inert (it cannot be reached by Tab, clicked, or read by a screen reader);
 * focus moves into the modal; and when it closes focus goes back to what opened it.
 *
 *   const ref = useRef(null);
 *   const onKeyDown = useModal(ref, { initial: ".btn.primary" });
 *   <div role="dialog" aria-modal="true" ref=${ref} onKeyDown=${onKeyDown}>
 */
export function useModal(ref, { initial } = {}) {
  useEffect(() => {
    const opener = document.activeElement;
    const shell = document.getElementById("app-shell");
    openModals += 1;
    if (shell) shell.inert = true;

    const root = ref.current;
    const target = (initial && root?.querySelector(initial)) || root?.querySelector(FOCUSABLE) || root;
    if (target && target === root && !root.hasAttribute("tabindex")) root.setAttribute("tabindex", "-1");
    target?.focus?.({ preventScroll: true });

    return () => {
      openModals -= 1;
      if (openModals === 0 && shell) shell.inert = false;
      if (opener && opener !== document.body && document.contains(opener)) opener.focus?.({ preventScroll: true });
    };
  }, []);

  // Tab and Shift+Tab wrap around inside the modal.
  return (event) => {
    if (event.key !== "Tab" || !ref.current) return;
    const focusables = [...ref.current.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null || el === document.activeElement);
    const next = wrapTab(focusables, document.activeElement, event.shiftKey);
    if (next) {
      next.focus();
      event.preventDefault();
    }
  };
}
