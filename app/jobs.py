"""Background job state for the scan and organize runs.

A job is a fixed list of named stages. Each stage reports real `done/total` progress
(through a `Progress` handed to the stage's loop), so the UI can show an honest bar,
a current file, and an ETA instead of a scrolling log.
"""
from __future__ import annotations

import threading
import time

from .progress import Progress

MAX_WARNINGS = 100


class Job:
    def __init__(self, kind: str, stage_defs: list[tuple[str, str]]) -> None:
        self.kind = kind
        self._stage_defs = stage_defs
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self.reset()

    # -- lifecycle ---------------------------------------------------------

    def reset(self) -> None:
        with self._lock:
            self.state = "idle"  # idle | running | done | cancelled | error
            self.started_at: float | None = None
            self.ended_at: float | None = None
            self.error: str | None = None
            self.summary: dict | None = None
            self.warnings: list[str] = []
            self._cancel.clear()
            self.stages = [
                {"key": k, "label": label, "state": "pending", "done": 0, "total": None,
                 "detail": None, "note": None, "started": None, "ended": None}
                for k, label in self._stage_defs
            ]

    @property
    def running(self) -> bool:
        return self.state == "running"

    def start(self) -> None:
        self.reset()
        with self._lock:
            self.state = "running"
            self.started_at = time.time()

    def finish(self, summary: dict | None = None) -> None:
        with self._lock:
            self.state = "done"
            self.ended_at = time.time()
            self.summary = summary

    def fail(self, message: str) -> None:
        with self._lock:
            self.state = "error"
            self.ended_at = time.time()
            self.error = message
            for stage in self.stages:
                if stage["state"] == "running":
                    stage["state"] = "error"

    def mark_cancelled(self) -> None:
        with self._lock:
            self.state = "cancelled"
            self.ended_at = time.time()
            for stage in self.stages:
                if stage["state"] == "running":
                    stage["state"] = "pending"

    # -- cancellation ------------------------------------------------------

    def request_cancel(self) -> None:
        self._cancel.set()

    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    # -- stages ------------------------------------------------------------

    def _stage(self, key: str) -> dict:
        return next(s for s in self.stages if s["key"] == key)

    def begin(self, key: str) -> Progress:
        with self._lock:
            stage = self._stage(key)
            stage.update(state="running", done=0, total=None, detail=None, started=time.time())

        def on_update(done: int, total: int | None, detail: str | None) -> None:
            with self._lock:
                stage["done"] = done
                stage["total"] = total
                if detail is not None:
                    stage["detail"] = detail

        return Progress(on_update=on_update, should_cancel=self.cancel_requested)

    def end(self, key: str, note: str | None = None) -> None:
        with self._lock:
            stage = self._stage(key)
            stage.update(state="done", ended=time.time(), detail=None)
            if stage["total"] is not None:
                stage["done"] = stage["total"]
            if note:
                stage["note"] = note

    def skip(self, key: str, note: str) -> None:
        with self._lock:
            self._stage(key).update(state="skipped", note=note, detail=None)

    def warn(self, message: str) -> None:
        with self._lock:
            if len(self.warnings) < MAX_WARNINGS:
                self.warnings.append(message)

    # -- reporting ---------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            stages = []
            for s in self.stages:
                entry = dict(s)
                eta = None
                if s["state"] == "running" and s["total"] and s["done"] > 0 and s["started"]:
                    elapsed = now - s["started"]
                    eta = max(0.0, elapsed * (s["total"] - s["done"]) / s["done"])
                entry["eta"] = eta
                entry.pop("started", None)
                entry.pop("ended", None)
                stages.append(entry)
            elapsed = ((self.ended_at or now) - self.started_at) if self.started_at else 0.0
            return {
                "kind": self.kind,
                "state": self.state,
                "elapsed": elapsed,
                "stages": stages,
                "error": self.error,
                "summary": self.summary,
                "warnings": list(self.warnings),
                "cancelling": self._cancel.is_set() and self.state == "running",
            }
