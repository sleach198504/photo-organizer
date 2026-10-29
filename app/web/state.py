"""Process-wide state shared by the API routes."""
from __future__ import annotations

import threading
import time

from .. import content_tagging
from ..jobs import Job
from ..pipeline import ORGANIZE_STAGES, SCAN_STAGES

APPLY_STAGES = [("move", "Moving to the review folder")]

SERVER_PORT = 8765
HEALTH_SENTINEL = "photo-organizer-review-server"


class AppState:
    def __init__(self) -> None:
        self.jobs = {
            "scan": Job("scan", SCAN_STAGES),
            "organize": Job("organize", ORGANIZE_STAGES),
            "apply": Job("apply", APPLY_STAGES),
        }
        self.started_at = time.time()
        self.last_heartbeat: float | None = None
        self._clip = None
        self._clip_lock = threading.Lock()
        self.pick_folder_lock = threading.Lock()  # Tcl isn't safe across threads

    def beat(self) -> None:
        self.last_heartbeat = time.time()

    def any_job_running(self, *names: str) -> bool:
        return any(self.jobs[n].running for n in (names or self.jobs))

    def clip(self):
        """Loading the model takes a few seconds, so it is loaded once per process."""
        with self._clip_lock:
            if self._clip is None:
                self._clip = content_tagging.create_backend()
            return self._clip
