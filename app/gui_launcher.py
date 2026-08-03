from __future__ import annotations

import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from .web.server import HEALTH_SENTINEL, SERVER_PORT, create_app

# Chromium's --app mode opens a window with no address bar, tabs, or bookmarks bar -
# just the page and a title bar, which is what a native desktop window looks like.
# Falls back to a normal browser tab if neither is found.
_APP_MODE_BROWSER_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def _find_app_mode_browser() -> str | None:
    for path in _APP_MODE_BROWSER_PATHS:
        if Path(path).exists():
            return path
    for name in ("msedge", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _open_app_window(url: str) -> None:
    browser = _find_app_mode_browser()
    if browser:
        subprocess.Popen([browser, f"--app={url}", "--window-size=1100,850"])
    else:
        webbrowser.open(url)


def _wait_and_open_browser() -> None:
    url = f"http://127.0.0.1:{SERVER_PORT}/"
    health_url = f"http://127.0.0.1:{SERVER_PORT}/healthz"
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=0.5) as resp:
                if resp.read().decode("utf-8", errors="replace") == HEALTH_SENTINEL:
                    _open_app_window(url)
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.2)
    # Gave up - nothing else to do here silently; if the server never came up,
    # uvicorn.run() below will have already raised in the main thread.


def main() -> None:
    import uvicorn

    app = create_app()
    threading.Thread(target=_wait_and_open_browser, daemon=True).start()
    # log_config=None: uvicorn's default logging setup configures a formatter that
    # touches sys.stderr, which is None under pythonw.exe (no console) - this app is
    # launched that way, and it crashes with "Unable to configure formatter 'default'"
    # otherwise.
    uvicorn.run(app, host="127.0.0.1", port=SERVER_PORT, log_level="warning", log_config=None)


if __name__ == "__main__":
    main()
