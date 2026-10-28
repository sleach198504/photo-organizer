import { html, useState } from "../lib/html.js";
import { api } from "../lib/api.js";
import { Icon } from "./icon.js";
import { toast } from "./toast.js";

/**
 * A folder path with a Browse button. The browser can't read a local path, so Browse
 * asks the app for the real Windows folder picker.
 */
export function FolderField({ id, value, purpose, placeholder, onChange, invalid }) {
  const [busy, setBusy] = useState(false);

  async function browse() {
    setBusy(true);
    try {
      const { path } = await api.post("/api/pick-folder", { purpose, initial: value || null });
      if (path) onChange(path);
    } catch (error) {
      toast(error.message, { kind: "error" });
    } finally {
      setBusy(false);
    }
  }

  return html`
    <div class="input-group">
      <input
        id=${id}
        class="input"
        spellcheck="false"
        placeholder=${placeholder}
        value=${value}
        aria-invalid=${invalid ? "true" : undefined}
        onInput=${(e) => onChange(e.target.value)}
      />
      <button class="btn" type="button" disabled=${busy} onClick=${browse}>
        <${Icon} name="folder-open" /> Browse
      </button>
    </div>
  `;
}
