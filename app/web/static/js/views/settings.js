import { html, useState } from "../lib/html.js";
import { api } from "../lib/api.js";
import { settings, system, refreshSettings, anyJobRunning } from "../lib/store.js";
import { themePref, setTheme } from "../lib/theme.js";
import { Icon } from "../ui/icon.js";
import { FolderField } from "../ui/folder-field.js";
import { toast } from "../ui/toast.js";
import { beginScan } from "./scan.js";
import { confirm } from "../ui/dialog.js";

const SIMILARITY = [
  ["strict", "Strict", "Only shots that are almost identical."],
  ["balanced", "Balanced", "Bursts and retakes of the same scene. A good default."],
  ["loose", "Loose", "Also groups shots that are merely similar. Expect to review more."],
];

const VIDEO_REVIEW = [
  ["off", "Don't flag videos", "Videos are never suggested for review."],
  ["medium", "Videos over a minute", "Longer clips take the most space, so they're the best place to start."],
  ["long", "Videos over five minutes", "Only the biggest ones."],
  ["all", "Every video", "Flag all of them so you can go through them one by one."],
];

function Radios({ options, value, onChange, name }) {
  return html`
    <div class="options" role="radiogroup" aria-label=${name}>
      ${options.map(
        ([key, label, desc]) => html`
          <button class="option" role="radio" aria-checked=${value === key} onClick=${() => onChange(key)} key=${key}>
            <span class="radio"></span>
            <span><b>${label}</b><span class="desc">${desc}</span></span>
          </button>
        `
      )}
    </div>
  `;
}

function Switch({ checked, onChange, label }) {
  return html`<button class="switch" role="switch" aria-checked=${checked} aria-label=${label} onClick=${() => onChange(!checked)}></button>`;
}

export function SettingsView() {
  const current = settings.value;
  const [draft, setDraft] = useState({ source_dir: current.source_dir, quarantine_dir: current.quarantine_dir });
  const [folderError, setFolderError] = useState("");
  const [update, setUpdate] = useState(null);
  const [checking, setChecking] = useState(false);
  const foldersChanged = draft.source_dir !== current.source_dir || draft.quarantine_dir !== current.quarantine_dir;

  async function save(patch, { quiet = false } = {}) {
    try {
      await api.put("/api/settings", patch);
      await refreshSettings();
      if (!quiet) toast("Saved", { kind: "success", timeout: 1800 });
      return true;
    } catch (error) {
      toast(error.message, { kind: "error" });
      return false;
    }
  }

  async function saveFolders() {
    setFolderError("");
    try {
      await api.put("/api/settings", draft);
      await refreshSettings();
      toast("Folders saved", { kind: "success", timeout: 2200 });
      const rescan = await confirm({
        title: "Scan the new folder now?",
        body: "Your folders changed, so the library needs a scan to match.",
        confirmLabel: "Scan now",
        cancelLabel: "Later",
      });
      if (rescan) beginScan();
    } catch (error) {
      setFolderError(error.message);
    }
  }

  async function checkUpdates() {
    setChecking(true);
    try {
      setUpdate(await api.get("/api/update-check"));
    } catch (error) {
      setUpdate({ error: error.message });
    } finally {
      setChecking(false);
    }
  }

  const sys = system.value;

  return html`
    <div class="page narrow stack settings">
      <div class="page-head"><div><h1>Settings</h1></div></div>

      <section class="stack tight">
        <h2>Folders</h2>
        <div class="panel panel-pad stack">
          <div class="field">
            <label for="set-source">Photos folder</label>
            <${FolderField}
              id="set-source"
              value=${draft.source_dir}
              purpose="photos"
              invalid=${!!folderError}
              onChange=${(v) => setDraft({ ...draft, source_dir: v })}
            />
            <span class="hint">Photo Organizer reads this folder, including everything inside it.</span>
          </div>
          <div class="field">
            <label for="set-review">Removed photos wait in</label>
            <${FolderField}
              id="set-review"
              value=${draft.quarantine_dir}
              purpose="review"
              invalid=${!!folderError}
              onChange=${(v) => setDraft({ ...draft, quarantine_dir: v })}
            />
            <span class="hint">Removing a photo only moves it here. It's never deleted until you choose to.</span>
          </div>
          ${folderError && html`<div class="field-error"><${Icon} name="circle-alert" size="sm" /> ${folderError}</div>`}
          ${foldersChanged &&
          html`<div class="row">
            <button class="btn primary" disabled=${anyJobRunning.value} onClick=${saveFolders}>Save folders</button>
            <button class="btn subtle" onClick=${() => setDraft({ source_dir: current.source_dir, quarantine_dir: current.quarantine_dir })}>
              Discard
            </button>
          </div>`}
        </div>
      </section>

      <section class="stack tight">
        <h2>Finding similar photos</h2>
        <div class="panel panel-pad stack">
          <div class="field">
            <span class="label">How alike must two photos be?</span>
            <${Radios}
              name="Similarity"
              options=${SIMILARITY}
              value=${current.similarity}
              onChange=${(v) => save({ similarity: v })}
            />
            <span class="hint">Takes effect the next time you scan.</span>
          </div>
        </div>
        <div class="panel">
          <div class="setting">
            <div class="copy">
              <b>Move exact duplicates automatically</b>
              <span>Identical files are moved to Removed during a scan, keeping one. You can still restore them.</span>
            </div>
            <${Switch}
              label="Move exact duplicates automatically"
              checked=${current.auto_remove_exact_duplicates}
              onChange=${(v) => save({ auto_remove_exact_duplicates: v })}
            />
          </div>
        </div>
      </section>

      <section class="stack tight">
        <h2>Videos</h2>
        <div class="panel panel-pad stack">
          <div class="field">
            <span class="label">Which videos should be flagged for review?</span>
            <${Radios}
              name="Video review"
              options=${VIDEO_REVIEW}
              value=${current.video_review_mode}
              onChange=${(v) => save({ video_review_mode: v })}
            />
          </div>
          <div class="field">
            <span class="label">Search inside videos</span>
            <div class="segmented" role="radiogroup" aria-label="Video search detail">
              ${[
                ["fast", "Faster"],
                ["thorough", "More thorough"],
              ].map(
                ([key, label]) =>
                  html`<button role="radio" aria-checked=${current.video_search_depth === key} onClick=${() => save({ video_search_depth: key })} key=${key}>${label}</button>`
              )}
            </div>
            <span class="hint">More thorough looks at a frame every second instead of every ten, so scans take longer.</span>
          </div>
        </div>
      </section>

      <section class="stack tight">
        <h2>Appearance</h2>
        <div class="panel">
          <div class="setting">
            <div class="copy"><b>Theme</b><span>Photos look best against a dark background, but it's your call.</span></div>
            <div class="segmented" role="radiogroup" aria-label="Theme">
              ${[
                ["system", "Match Windows", "monitor"],
                ["dark", "Dark", "moon"],
                ["light", "Light", "sun"],
              ].map(
                ([key, label, icon]) => html`
                  <button role="radio" aria-checked=${themePref.value === key} onClick=${() => setTheme(key)} key=${key}>
                    ${label}
                  </button>
                `
              )}
            </div>
          </div>
        </div>
      </section>

      <section class="stack tight">
        <h2>About</h2>
        <div class="panel">
          <div class="setting">
            <div class="copy">
              <b>Photo Organizer ${sys?.version ?? ""}</b>
              <span>Runs entirely on this computer. It never goes online unless you check for updates below.</span>
            </div>
            <button class="btn" disabled=${checking} onClick=${checkUpdates}>
              <${Icon} name="refresh-cw" spin=${checking} /> Check for updates
            </button>
          </div>
          ${update &&
          html`<div class="setting">
            <div class="copy">
              ${update.error
                ? html`<b>Couldn't check</b><span>${update.error}</span>`
                : update.newer
                  ? html`<b>Version ${update.latest} is available</b><span>You have ${update.current}.</span>`
                  : html`<b>You're up to date</b><span>Version ${update.current} is the latest.</span>`}
            </div>
            ${update.newer && update.url && html`<a class="btn primary" href=${update.url} target="_blank" rel="noreferrer">See what's new <${Icon} name="external-link" size="sm" /></a>`}
          </div>`}
          <div class="setting">
            <div class="copy">
              <b>Photo recognition</b>
              <span>
                ${sys?.models_ready
                  ? `Ready, running on your ${sys.gpu ? "graphics card" : "processor"}.`
                  : "Not installed. Run Setup again to turn on search and content recognition."}
              </span>
            </div>
            <span class=${`pill ${sys?.models_ready ? "keep" : "warn"}`}>${sys?.models_ready ? "Ready" : "Unavailable"}</span>
          </div>
          <div class="setting">
            <div class="copy"><b>Where your data lives</b><span class="num">${sys?.home}</span></div>
          </div>
        </div>
      </section>
    </div>
  `;
}
