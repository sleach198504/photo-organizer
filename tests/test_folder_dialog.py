"""The native folder dialog: opens, can be cancelled, and returns the folder it was confirmed on.

These open a real (briefly visible) Windows dialog and then close or confirm it from the test, so
they only run on Windows and are skipped if no desktop is available.
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

WINDOWS = sys.platform == "win32"
if WINDOWS:
    import ctypes

    from app import folder_dialog

    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    WM_CLOSE, WM_COMMAND, IDOK = 0x0010, 0x0111, 1


def run_dialog(title: str, initial: str | None, act) -> object:
    """Opens the dialog on its own thread, waits for its window, and calls act(hwnd) on it."""
    outcome: dict = {}

    def worker() -> None:
        try:
            outcome["value"] = folder_dialog.choose_folder(title, initial)
        except Exception as exc:  # noqa: BLE001 - reported by the test below
            outcome["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    hwnd = None
    deadline = time.time() + 10
    while time.time() < deadline and not hwnd and thread.is_alive():
        hwnd = user32.FindWindowW(None, title)
        time.sleep(0.1)
    if hwnd:
        time.sleep(0.5)  # let it finish drawing
        act(hwnd)
    thread.join(10)
    if thread.is_alive():
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)  # never leave a dialog open behind a failed test
        thread.join(5)
        raise AssertionError("the dialog did not close")
    if "error" in outcome:
        raise outcome["error"]
    if not hwnd:
        raise unittest.SkipTest("the dialog window could not be found (no desktop?)")
    return outcome.get("value")


@unittest.skipUnless(WINDOWS, "Windows only")
class FolderDialogTests(unittest.TestCase):
    def test_cancelling_returns_nothing(self) -> None:
        value = run_dialog("Photo Organizer test: cancel me", None, lambda h: user32.PostMessageW(h, WM_CLOSE, 0, 0))
        self.assertIsNone(value)

    def test_confirming_returns_the_folder_it_was_opened_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp).resolve()
            value = run_dialog(
                "Photo Organizer test: confirm me", str(folder), lambda h: user32.PostMessageW(h, WM_COMMAND, IDOK, 0)
            )
        self.assertIsNotNone(value)
        self.assertEqual(Path(value).resolve(), folder)


if __name__ == "__main__":
    unittest.main()
