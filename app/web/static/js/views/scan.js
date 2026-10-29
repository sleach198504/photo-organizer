import { html, useState } from "../lib/html.js";
import { go, href } from "../lib/router.js";
import { jobs, settings, summary, startJob, cancelJob } from "../lib/store.js";
import { count, plural, eta, elapsed, ago } from "../lib/format.js";
import { Icon } from "../ui/icon.js";
import { toast } from "../ui/toast.js";

function StageIcon({ state }) {
  if (state === "done") return html`<${Icon} name="circle-check" />`;
  if (state === "running") return html`<${Icon} name="loader-circle" spin />`;
  if (state === "skipped") return html`<${Icon} name="minus" />`;
  if (state === "error") return html`<${Icon} name="circle-alert" />`;
  return html`<${Icon} name="circle-dashed" />`;
}

function Stage({ stage }) {
  const determinate = stage.state === "running" && stage.total;
  const pct = determinate ? Math.min(100, Math.round((stage.done / stage.total) * 100)) : 0;
  return html`
    <li class=${`stage ${stage.state}`}>
      <span class="stage-icon"><${StageIcon} state=${stage.state} /></span>
      <div class="stage-body">
        <div class="row">
          <b>${stage.label}</b>
          <span class="spacer"></span>
          ${determinate && html`<span class="num muted">${count(stage.done)} of ${count(stage.total)}</span>`}
        </div>
        ${stage.state === "running" &&
        html`<div class=${`bar${determinate ? "" : " indeterminate"}`} role="progressbar" aria-label=${stage.label} aria-valuemin="0" aria-valuemax="100" aria-valuenow=${determinate ? pct : undefined}><i style=${determinate ? `width:${pct}%` : ""}></i></div>`}
        ${stage.state === "running" &&
        html`<div class="row faint stage-detail">
          <span class="truncate">${stage.detail ?? ""}</span>
          <span class="spacer"></span>
          ${determinate && stage.eta != null && html`<span>${eta(stage.eta)}</span>`}
        </div>`}
        ${stage.state !== "running" && stage.note && html`<div class="faint stage-detail">${stage.note}</div>`}
      </div>
    </li>
  `;
}

export async function beginScan(patch = {}) {
  try {
    await startJob("scan", "/api/scan/start", patch);
    go("/scan");
  } catch (error) {
    toast(error.message, { kind: "error" });
  }
}

export function ScanView() {
  const job = jobs.scan.value;
  const [showWarnings, setShowWarnings] = useState(false);
  const state = job?.state ?? "idle";
  const s = summary.value;
  const config = settings.value;

  if (state === "idle") {
    return html`
      <div class="page narrow stack">
        <div class="page-head">
          <div>
            <h1>Scan your photos</h1>
            <p>
              Reads every photo and video in your folder, then looks for duplicates, blurry shots, screenshots and
              documents. Your files are only read, never changed.
            </p>
          </div>
        </div>
        <div class="panel">
          <div class="setting">
            <div class="copy">
              <b>Photos folder</b>
              <span class="num">${config?.source_dir || "Not chosen yet"}</span>
            </div>
            <a class="btn" href=${href("/settings")}>Change</a>
          </div>
          <div class="setting">
            <div class="copy">
              <b>${s?.last_scan ? `Last scanned ${ago(s.last_scan)}` : "Never scanned"}</b>
              <span>Later scans only look at new and changed files, so they finish much faster.</span>
            </div>
            <button class="btn primary" onClick=${() => beginScan()}><${Icon} name="scan-search" /> Scan now</button>
          </div>
        </div>
      </div>
    `;
  }

  const running = state === "running";
  const result = job.summary;
  const heading = {
    running: job.cancelling ? "Stopping…" : "Scanning your library",
    done: "Scan complete",
    cancelled: "Scan stopped",
    error: "The scan ran into a problem",
  }[state];

  return html`
    <div class="page narrow stack">
      <div class="page-head">
        <div>
          <h1>${heading}</h1>
          <p>
            ${running
              ? "You can keep using Photo Organizer while this runs. Everything found so far is saved, so it's safe to stop at any time."
              : state === "done"
                ? `Finished in ${elapsed(result?.seconds ?? job.elapsed)}.`
                : state === "cancelled"
                  ? "Progress is saved. Scanning again picks up where this left off."
                  : ""}
          </p>
        </div>
        ${running &&
        html`<button class="btn" disabled=${job.cancelling} onClick=${() => cancelJob("scan")}>
          ${job.cancelling ? "Stopping…" : "Stop scan"}
        </button>`}
      </div>

      ${state === "error" && html`<div class="notice error"><${Icon} name="circle-alert" /><span>${job.error}</span></div>`}

      ${state === "done" &&
      html`
        <div class="panel result-panel">
          <div class="result-line">
            <b class="num">${count(result.scanned)}</b><span>items in your library</span>
          </div>
          <div class="result-line">
            <b class="num">${count(result.flagged)}</b><span>flagged for you to review</span>
          </div>
          ${result.auto_removed > 0 &&
          html`<div class="result-line"><b class="num">${count(result.auto_removed)}</b><span>exact duplicates moved to Removed automatically</span></div>`}
          <div class="row" style="margin-left:auto">
            <a class="btn primary" href=${href(result.flagged ? "/review" : "/")}>
              ${result.flagged ? "Start reviewing" : "Go to Home"} <${Icon} name="arrow-right" />
            </a>
          </div>
        </div>
      `}

      <ol class="panel stages">
        ${job.stages.map((stage) => html`<${Stage} stage=${stage} key=${stage.key} />`)}
      </ol>

      ${state === "done" && result.online_only > 0 &&
      html`<div class="notice warn"><${Icon} name="triangle-alert" /><span>
        <b>${plural(result.online_only, "photo or video")}</b> ${result.online_only === 1 ? "is" : "are"} stored online only
        (for example in OneDrive), so ${result.online_only === 1 ? "it was" : "they were"} left out rather than downloaded. To include
        ${result.online_only === 1 ? "it" : "them"}, set the folder to "Always keep on this device" and scan again.
      </span></div>`}

      ${job.warnings.length > 0 &&
      html`
        <div class="panel">
          <button class="setting warn-toggle" onClick=${() => setShowWarnings(!showWarnings)} aria-expanded=${showWarnings}>
            <span class="copy">
              <b>${plural(job.warnings.length, "file")} had problems</b>
              <span>These were skipped. Everything else was scanned.</span>
            </span>
            <${Icon} name=${showWarnings ? "chevron-up" : "chevron-down"} />
          </button>
          ${showWarnings && html`<ul class="warn-list">${job.warnings.map((w) => html`<li>${w}</li>`)}</ul>`}
        </div>
      `}

      ${!running && state !== "done" &&
      html`<div class="row"><button class="btn primary" onClick=${() => beginScan()}><${Icon} name="refresh-cw" /> Scan again</button></div>`}
    </div>
  `;
}
