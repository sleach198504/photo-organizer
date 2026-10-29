import { html, useState } from "../lib/html.js";
import { go } from "../lib/router.js";
import { settings, startJob, refreshSettings } from "../lib/store.js";
import { Icon } from "../ui/icon.js";
import { Brand } from "../ui/shell.js";
import { FolderField } from "../ui/folder-field.js";

// A contact sheet, drawn the way a photographer would mark it up: the point of the
// whole app in one picture. Frames are abstract on purpose - no stock photos.
function ProofSheet() {
  const tones = [62, 48, 70, 40, 56, 66, 44, 74, 52, 60, 46, 68];
  const frames = tones.map((tone, i) => {
    const col = i % 4;
    const row = Math.floor(i / 4);
    return { x: 24 + col * 128, y: 24 + row * 104, tone, i };
  });
  const removed = new Set([1, 2, 6, 9]);
  const kept = new Set([5, 11]);
  return html`
    <svg class="proof" viewBox="0 0 548 340" role="img" aria-label="A contact sheet with unwanted frames crossed out and the best ones circled">
      <rect width="548" height="340" rx="14" fill="var(--surface)" stroke="var(--line)" />
      ${frames.map(
        ({ x, y, tone, i }) => html`
          <g key=${i}>
            <rect x=${x} y=${y} width="116" height="88" rx="4" fill=${`hsl(210 4% ${tone * 0.55}%)`} opacity=${removed.has(i) ? 0.55 : 1} />
            <path d=${`M${x} ${y + 88} l34 -34 l20 20 l24 -30 l38 44z`} fill="rgba(255,255,255,0.14)" />
            ${kept.has(i) && html`<rect x=${x - 4} y=${y - 4} width="124" height="96" rx="9" fill="none" stroke="var(--keep)" stroke-width="3.5" />`}
            ${removed.has(i) && html`<path d=${`M${x + 8} ${y + 80} L${x + 108} ${y + 8}`} stroke="var(--remove)" stroke-width="4.5" stroke-linecap="round" />`}
          </g>
        `
      )}
    </svg>
  `;
}

export function Onboarding() {
  const [folder, setFolder] = useState(settings.value?.source_dir ?? "");
  const [reviewDir, setReviewDir] = useState("");
  const [showMore, setShowMore] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function start() {
    setError("");
    setBusy(true);
    try {
      await beginScanFor(folder.trim(), reviewDir.trim());
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return html`
    <main class="welcome">
      <div class="welcome-copy">
        <${Brand} />
        <h1>Find the photos worth keeping.</h1>
        <p class="lead">
          Point Photo Organizer at the folder your phone photos are in. It finds duplicates, near-identical bursts,
          blurry shots and screenshots, and lines them up so you can clear hundreds in minutes.
        </p>

        <div class="field">
          <label for="photos-folder">Where are your photos?</label>
          <${FolderField}
            id="photos-folder"
            value=${folder}
            purpose="photos"
            placeholder="Choose the folder with your photos and videos"
            invalid=${!!error}
            onChange=${(v) => {
              setFolder(v);
              setError("");
            }}
          />
          ${error && html`<div class="field-error"><${Icon} name="circle-alert" size="sm" /> ${error}</div>`}
        </div>

        ${showMore &&
        html`<div class="field">
          <label for="review-folder">Where should removed photos wait?</label>
          <${FolderField}
            id="review-folder"
            value=${reviewDir}
            purpose="review"
            placeholder="Defaults to a folder named Image Review inside your photos folder"
            onChange=${setReviewDir}
          />
          <span class="hint">Removed photos are only moved here. You decide later whether to delete them for good.</span>
        </div>`}

        <div class="row">
          <button class="btn primary lg" disabled=${!folder.trim() || busy} onClick=${start}>
            <${Icon} name="scan-search" /> ${busy ? "Starting…" : "Scan my photos"}
          </button>
          ${!showMore && html`<button class="btn subtle" onClick=${() => setShowMore(true)}>More options</button>`}
        </div>

        <ul class="promises">
          <li><${Icon} name="shield-check" /><span><b>Stays on this computer.</b> Nothing is uploaded and the app never goes online by itself.</span></li>
          <li><${Icon} name="undo-2" /><span><b>Nothing is deleted</b> unless you say so. Removed photos wait in a folder you can restore from.</span></li>
        </ul>
      </div>
      <div class="welcome-art"><${ProofSheet} /></div>
    </main>
  `;
}

async function beginScanFor(sourceDir, reviewDir) {
  const body = { source_dir: sourceDir };
  if (reviewDir) body.quarantine_dir = reviewDir;
  await startJob("scan", "/api/scan/start", body);
  await refreshSettings();
  go("/scan");
}
