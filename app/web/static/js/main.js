import { html, render, useEffect, useRef } from "./lib/html.js";
import { api } from "./lib/api.js";
import { route, go } from "./lib/router.js";
import { boot, booted, bootError, settings, marks } from "./lib/store.js";
import { applyTheme } from "./lib/theme.js";
import { useHotkeys } from "./lib/keys.js";
import { exited } from "./lib/exit.js";
import { Sidebar, Topbar, DecisionTray, TITLES } from "./ui/shell.js";
import { ToastHost } from "./ui/toast.js";
import { DialogHost } from "./ui/dialog.js";
import { ShortcutsHost } from "./ui/shortcuts.js";
import { LightboxHost } from "./ui/lightbox.js";
import { Icon } from "./ui/icon.js";
import { Onboarding } from "./views/onboarding.js";
import { routeView } from "./views/registry.js";

applyTheme();

function Splash({ error }) {
  return html`
    <div class="splash">
      ${error
        ? html`<${Icon} name="circle-alert" size="lg" />
            <h2>Photo Organizer can't reach its engine</h2>
            <p class="muted">${error}</p>
            <button class="btn primary" onClick=${() => location.reload()}>Try again</button>`
        : html`<${Icon} name="loader-circle" size="lg" spin />`}
    </div>
  `;
}

function Goodbye() {
  return html`
    <div class="splash">
      <${Icon} name="circle-check" size="lg" />
      <h2>Photo Organizer has closed</h2>
      <p class="muted">You can close this window.</p>
    </div>
  `;
}

// "g" then a letter jumps between sections, like in GitHub and Gmail.
function useChords() {
  const armed = useRef(0);
  const jump = (path) => () => {
    if (Date.now() - armed.current > 1200) return false;
    armed.current = 0;
    go(path);
  };
  useHotkeys({
    g: () => {
      armed.current = Date.now();
    },
    h: jump("/"),
    r: jump("/review"),
    p: jump("/photos"),
    v: jump("/videos"),
    t: jump("/trips"),
    o: jump("/organize"),
  });
}

function Shell() {
  useChords();
  const r = route.value;
  const View = routeView(r);
  const scroller = useRef(null);
  const pending = marks.value.remove + marks.value.keep > 0;

  // Each page starts at the top, and the window title says where you are.
  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = 0;
    const name = TITLES[r.parts[0] ?? ""];
    document.title = name && name !== "Home" ? `${name} · Photo Organizer` : "Photo Organizer";
  }, [r.parts[0], r.parts[1]]);

  return html`
    <div id="app-shell" class="shell">
      <${Sidebar} />
      <div class="main">
        <${Topbar} />
        <main class=${`content${pending ? " has-tray" : ""}`} ref=${scroller} id="content">
          <${View} route=${r} />
        </main>
        <${DecisionTray} />
      </div>
    </div>
  `;
}

function App() {
  useEffect(() => {
    boot();
    const beat = () => api.post("/api/heartbeat").catch(() => {});
    beat();
    const timer = setInterval(beat, 20000);
    return () => clearInterval(timer);
  }, []);

  let body;
  if (exited.value) body = html`<${Goodbye} />`;
  else if (!booted.value) body = html`<${Splash} />`;
  else if (bootError.value) body = html`<${Splash} error=${bootError.value} />`;
  else if (!settings.value?.configured) body = html`<${Onboarding} />`;
  else body = html`<${Shell} />`;

  return html`
    ${body}
    <${ToastHost} />
    <${LightboxHost} />
    <${DialogHost} />
    <${ShortcutsHost} />
  `;
}

render(html`<${App} />`, document.getElementById("app"));
