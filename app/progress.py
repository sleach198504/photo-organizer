"""Progress reporting and cooperative cancellation for the long-running pipeline
stages (indexing, sharpness scoring, content recognition, ...).

Each stage's loop receives a `Progress`, calls `advance()` per item and `check()` at
safe points. `check()` raises `Cancelled`, which unwinds to the scan runner; since
every stage is idempotent (it only touches rows it hasn't processed yet), a
cancelled scan simply resumes where it left off next time.
"""
from __future__ import annotations

from typing import Callable


class Cancelled(Exception):
    """The person asked to stop the current scan."""


class Progress:
    def __init__(
        self,
        on_update: Callable[[int, int | None, str | None], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> None:
        self._on_update = on_update
        self._should_cancel = should_cancel
        self.done = 0
        self.total: int | None = None

    def start(self, total: int | None, detail: str | None = None) -> None:
        self.done = 0
        self.total = total
        self._emit(detail)

    def advance(self, n: int = 1, detail: str | None = None) -> None:
        self.done += n
        self._emit(detail)

    def set_total(self, total: int | None) -> None:
        self.total = total
        self._emit(None)

    def detail(self, text: str) -> None:
        self._emit(text)

    def check(self) -> None:
        if self._should_cancel is not None and self._should_cancel():
            raise Cancelled()

    def _emit(self, detail: str | None) -> None:
        if self._on_update is not None:
            self._on_update(self.done, self.total, detail)


NULL_PROGRESS = Progress()
