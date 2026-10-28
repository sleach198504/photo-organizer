import { html, useEffect, useMemo, useState } from "../lib/html.js";
import { api } from "../lib/api.js";
import { href } from "../lib/router.js";
import { jobs, summary, startJob, cancelJob, anyJobRunning, refreshSummary, dataVersion } from "../lib/store.js";
import { count, plural, elapsed, eta } from "../lib/format.js";
import { Icon } from "../ui/icon.js";
import { FolderField } from "../ui/folder-field.js";
import { confirm } from "../ui/dialog.js";
import { toast } from "../ui/toast.js";

function useDebounced(value, ms) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

function FolderTree({ folders }) {
  const [all, setAll] = useState(false);
  const shown = all ? folders : folders.slice(0, 8);
  return html`
    <ul class="preview-tree">
      ${shown.map(
        (f) => html`<li key=${f.path}>
          <${Icon} name="folder" size="sm" />
          <span class="truncate">${f.path.split("/").join("  /  ")}</span>
          <span class="spacer"></span>
          <span class="num faint">${count(f.count)}</span>
        </li>`
      )}
    </ul>
    ${folders.length > 8 && html`<button class="btn sm subtle" onClick=${() => setAll(!all)}>${all ? "Show fewer" : `Show all ${folders.length} folders`}</button>`}
  `;
}

function Progress() {
  const job = jobs.organize.value;
  const stage = job?.stages?.[0];
  const pct = stage?.total ? Math.round((stage.done / stage.total) * 100) : 0;
  return html`
    <div class="panel panel-pad stack tight" role="status">
      <div class="row"><b>Filing your photos</b><span class="spacer"></span><span class="num muted">${stage?.total ? `${count(stage.done)} of ${count(stage.total)}` : ""}</span></div>
      <div class=${`bar${stage?.total ? "" : " indeterminate"}`}><i style=${stage?.total ? `width:${pct}%` : ""}></i></div>
      <div class="row faint stage-detail"><span class="truncate">${stage?.detail ?? ""}</span><span class="spacer"></span><span>${stage?.eta != null ? eta(stage.eta) : ""}</span></div>
      <div class="row"><button class="btn sm" disabled=${job?.cancelling} onClick=${() => cancelJob("organize")}>${job?.cancelling ? "Stopping…" : "Stop"}</button></div>
    </div>
  `;
}

export function OrganizeView() {
  const [info, setInfo] = useState(null);
  const [dest, setDest] = useState("");
  const [folderName, setFolderName] = useState("");
  const [template, setTemplate] = useState("year_month");
  const [excluded, setExcluded] = useState(new Set());
  const [mode, setMode] = useState("skip");
  const [preview, setPreview] = useState({ state: "idle" });
  const job = jobs.organize.value;
  const s = summary.value;
  const version = dataVersion.value;

  useEffect(() => {
    api.get("/api/organize/state").then((data) => {
      setInfo(data);
      setDest((d) => d || data.dest_dir || "");
      setTemplate((t) => t || data.default_template);
    });
  }, [version]);

  const body = useMemo(
    () => ({ dest_dir: dest.trim(), folder_name: folderName.trim(), template, excluded: [...excluded], exclude_mode: mode }),
    [dest, folderName, template, excluded, mode]
  );
  const key = useDebounced(JSON.stringify(body), 350);

  useEffect(() => {
    const request = JSON.parse(key);
    if (!request.dest_dir) return setPreview({ state: "idle" });
    let live = true;
    setPreview((p) => ({ ...p, state: "loading" }));
    api
      .post("/api/organize/preview", request)
      .then((data) => live && setPreview({ state: "ready", data }))
      .catch((error) => live && setPreview({ state: "error", message: error.message }));
    return () => {
      live = false;
    };
  }, [key, version]);

  if (!info) return null;

  const running = job?.state === "running";
  const flagged = s.review.flagged_photos;
  const data = preview.data;
  const moving = data?.moving ?? 0;

  async function start() {
    const ok = await confirm({
      title: `File ${plural(moving, "item")} into ${data.dest_root}?`,
      confirmLabel: "File my photos",
      body: html`<p>
          Your photos are <b>moved</b> out of their current folders into dated folders. Photo Organizer can't move them
          back automatically, so check the preview first.${flagged ? ` ${plural(flagged, "item")} flagged for review will be filed too unless you review them first.` : ""}
        </p>`,
    });
    if (!ok) return;
    try {
      await startJob("organize", "/api/organize/start", body);
    } catch (error) {
      toast(error.message, { kind: "error" });
    }
  }

  const toggle = (folder) =>
    setExcluded((prev) => {
      const next = new Set(prev);
      next.has(folder) ? next.delete(folder) : next.add(folder);
      return next;
    });

  return html`
    <div class="page narrow stack organize">
      <div class="page-head">
        <div>
          <h1>Organize</h1>
          <p>File everything you're keeping into tidy folders by date. Trips get their own named folders. Nothing moves until you confirm.</p>
        </div>
      </div>

      ${flagged > 0 &&
      html`<div class="notice warn"><${Icon} name="triangle-alert" /><span>
        ${plural(flagged, "item")} still flagged for review. Organizing files them along with the rest, so
        <a href=${href("/review")}>review first</a> if you want clutter left out.
      </span></div>`}

      ${job?.state === "done" &&
      html`<div class="panel result-panel">
        <div class="result-line"><b class="num">${count(job.summary.moved)}</b><span>filed in ${elapsed(job.elapsed)}</span></div>
        ${job.summary.skipped > 0 && html`<div class="result-line"><b class="num">${count(job.summary.skipped)}</b><span>left where they were</span></div>`}
        ${job.summary.problems > 0 && html`<div class="result-line"><b class="num">${count(job.summary.problems)}</b><span>couldn't be moved</span></div>`}
        <span class="spacer"></span>
        <span class="faint path">${job.summary.dest}</span>
      </div>`}
      ${job?.state === "error" && html`<div class="notice error"><${Icon} name="circle-alert" /><span>${job.error}</span></div>`}
      ${job?.state === "cancelled" && html`<div class="notice"><${Icon} name="info" /><span>Stopped. Anything already filed stays where it is, and you can run Organize again to finish.</span></div>`}
      ${running && html`<${Progress} />`}

      <section class="stack tight">
        <h2>Where should they go?</h2>
        <div class="panel panel-pad stack">
          <div class="field">
            <label for="org-dest">Destination folder</label>
            <${FolderField} id="org-dest" value=${dest} purpose="organize" placeholder="Choose where to file your photos" onChange=${setDest} />
          </div>
          <div class="field">
            <label for="org-name">Put everything inside a folder named <span class="faint">(optional)</span></label>
            <input id="org-name" class="input" value=${folderName} placeholder="For example, Photos" onInput=${(e) => setFolderName(e.target.value)} />
          </div>
        </div>
      </section>

      <section class="stack tight">
        <h2>How should they be arranged?</h2>
        <div class="options" role="radiogroup" aria-label="Folder layout">
          ${info.templates.map(
            (t) => html`<button class="option" role="radio" aria-checked=${template === t.key} onClick=${() => setTemplate(t.key)} key=${t.key}>
              <span class="radio"></span>
              <span><b>${t.label}</b><span class="desc num">${t.example}</span></span>
            </button>`
          )}
        </div>
      </section>

      <section class="stack tight">
        <div class="section-head">
          <h2>Folders to leave out</h2>
          <span class="faint">${excluded.size ? `${excluded.size} left out` : "Everything is included"}</span>
        </div>
        <div class="panel folder-list">
          ${info.folders.map(
            (f) => html`<label class="folder-row" key=${f.folder}>
              <input type="checkbox" checked=${!excluded.has(f.folder)} onChange=${() => toggle(f.folder)} />
              <${Icon} name="folder" size="sm" />
              <span class="truncate">${f.folder}</span>
              <span class="spacer"></span>
              <span class="num faint">${count(f.count)}</span>
            </label>`
          )}
        </div>
        ${excluded.size > 0 &&
        html`<div class="options" role="radiogroup" aria-label="What to do with folders left out">
          <button class="option" role="radio" aria-checked=${mode === "skip"} onClick=${() => setMode("skip")}>
            <span class="radio"></span><span><b>Leave them exactly where they are</b></span>
          </button>
          <button class="option" role="radio" aria-checked=${mode === "move_as_is"} onClick=${() => setMode("move_as_is")}>
            <span class="radio"></span><span><b>Move them, but keep their folder names</b><span class="desc">They won't be sorted by date.</span></span>
          </button>
        </div>`}
      </section>

      <section class="stack tight">
        <h2>Preview</h2>
        <div class="panel panel-pad stack tight">
          ${preview.state === "idle" && html`<p class="muted">Choose a destination folder to see what will happen.</p>`}
          ${preview.state === "error" && html`<div class="field-error"><${Icon} name="circle-alert" size="sm" /> ${preview.message}</div>`}
          ${(preview.state === "ready" || (preview.state === "loading" && data)) &&
          html`
            <p>
              <b class="num">${count(moving)}</b> ${moving === 1 ? "item" : "items"} will be filed into
              <b class="num">${count(data.folders.length)}</b> ${data.folders.length === 1 ? "folder" : "folders"} inside
              <span class="path">${data.dest_root}</span>.
              ${data.totals.skip > 0 ? html`<span class="muted"> ${plural(data.totals.skip, "item")} stay where they are.</span>` : null}
            </p>
            <${FolderTree} folders=${data.folders} />
          `}
          ${preview.state === "loading" && !data && html`<div class="loading-row"><${Icon} name="loader-circle" spin /> Working out the plan…</div>`}
        </div>
      </section>

      <div class="row">
        <button class="btn primary lg" disabled=${running || anyJobRunning.value || preview.state !== "ready" || moving === 0} onClick=${start}>
          <${Icon} name="folder-tree" /> File ${moving ? plural(moving, "item") : "my photos"}
        </button>
      </div>
    </div>
  `;
}
