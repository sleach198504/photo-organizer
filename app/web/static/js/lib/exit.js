import { signal } from "./html.js";
import { api } from "./api.js";
import { anyJobRunning } from "./store.js";
import { confirm } from "../ui/dialog.js";

export const exited = signal(false);

export async function exitApp() {
  if (anyJobRunning.value) {
    const ok = await confirm({
      title: "Exit while a task is running?",
      body: "Photo Organizer is still working. If you exit now it stops where it is, and you can pick up again next time. Nothing is lost.",
      confirmLabel: "Exit anyway",
    });
    if (!ok) return;
  }
  try {
    await api.post("/api/shutdown");
  } catch {
    /* the server may close the connection while answering */
  }
  exited.value = true;
  window.close();
}
