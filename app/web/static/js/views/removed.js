import { html, useState } from "../lib/html.js";
import { api } from "../lib/api.js";
import { href } from "../lib/router.js";
import { summary, settings, dataVersion, refreshSummary, anyJobRunning } from "../lib/store.js";
import { bytes, plural } from "../lib/format.js";
import { Icon } from "../ui/icon.js";
import { usePagedList } from "../ui/paged.js";
import { confirm } from "../ui/dialog.js";
import { toast } from "../ui/toast.js";
import { PhotoGrid } from "./review.js";

export function RemovedView() {
  const s = summary.value;
  const version = dataVersion.value;
  const [busy, setBusy] = useState(false);
  const list = usePagedList((offset, limit) => api.get(`/api/removed?offset=${offset}&limit=${limit}`), {
    pageSize: 120,
    deps: [version],
  });
  const total = s.removed.count;

  async function refresh() {
    dataVersion.value += 1;
    await refreshSummary();
  }

  async function restore(ids) {
    setBusy(true);
    try {
      const result = await api.post("/api/removed/restore", { ids });
      toast(
        result.failed
          ? `Restored ${plural(result.restored, "item")}. ${plural(result.failed, "item")} couldn't be put back.`
          : `Restored ${plural(result.restored, "item")} to your library`,
        { kind: result.failed ? "error" : "success" }
      );
      await refresh();
    } catch (error) {
      toast(error.message, { kind: "error" });
    } finally {
      setBusy(false);
    }
  }

  async function purge(ids) {
    const everything = ids == null;
    const n = everything ? total : ids.length;
    const ok = await confirm({
      title: `Delete ${plural(n, "item")} permanently?`,
      danger: true,
      confirmLabel: "Delete permanently",
      requireText: "DELETE",
      body: html`<p>
        ${everything ? "Everything in Removed" : "The selected items"} will be deleted from your computer. This can't be undone.
        Photo Organizer only deletes files inside your review folder, never anything in your photos folder.
      </p>`,
    });
    if (!ok) return;
    setBusy(true);
    try {
      const result = await api.post("/api/removed/purge", { ids: everything ? null : ids, confirm: "DELETE" });
      toast(`Deleted ${plural(result.deleted, "item")}, freeing ${bytes(result.freed_bytes)}`, { kind: "success" });
      await refresh();
    } catch (error) {
      toast(error.message, { kind: "error" });
    } finally {
      setBusy(false);
    }
  }

  const empty = html`
    <div class="empty">
      <span class="art"><${Icon} name="trash-2" size="lg" /></span>
      <h2>Nothing has been removed</h2>
      <p>Photos you move out of your library wait here, so you can change your mind. Start in Review.</p>
      <a class="btn primary" href=${href("/review")}>Go to Review</a>
    </div>
  `;

  return html`
    <div class="page wide">
      <div class="page-head">
        <div>
          <h1>Removed</h1>
          <p>
            ${total
              ? `${plural(total, "item")} (${bytes(s.removed.bytes)}). Nothing here is deleted until you choose to.`
              : "Items you remove from your library wait here until you restore or delete them."}
          </p>
          ${total > 0 &&
          html`<p class="folder-line faint"><${Icon} name="folder" size="sm" /><span class="path">${settings.value?.quarantine_dir}</span></p>`}
        </div>
        ${total > 0 &&
        html`<div class="row">
          <button class="btn" disabled=${busy || anyJobRunning.value} onClick=${() => restore(null)}>
            <${Icon} name="undo-2" /> Restore all
          </button>
          <button class="btn danger" disabled=${busy || anyJobRunning.value} onClick=${() => purge(null)}>
            <${Icon} name="trash-2" /> Delete all permanently
          </button>
        </div>`}
      </div>
      <${PhotoGrid}
        list=${list}
        minCell=${170}
        quick=${false}
        marking=${false}
        emptyState=${empty}
        renderSelection=${(ids, clear) => html`
          <button class="btn sm" onClick=${() => restore(ids).then(clear)}><${Icon} name="undo-2" size="sm" /> Restore</button>
          <button class="btn sm danger" onClick=${() => purge(ids).then(clear)}><${Icon} name="trash-2" size="sm" /> Delete permanently</button>
        `}
      />
    </div>
  `;
}
