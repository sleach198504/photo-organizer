from __future__ import annotations

import logging
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from .paths import APP_HOME
from .web.app import create_app
from .web.state import HEALTH_SENTINEL, SERVER_PORT

log = logging.getLogger(__name__)

# Chromium's --app mode opens a window with no address bar, tabs, or bookmarks bar -
# just the page and a title bar, which is what a native desktop window looks like.
# Falls back to a normal browser tab if neither is found.
_APP_MODE_BROWSER_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

WINDOW_SIZE = "1360,880"


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
    if not browser:
        webbrowser.open(url)
        return
    # A private browser profile keeps this window separate from the person's everyday
    # browser (no tabs, extensions or sign-ins leaking in) and lets it remember its own
    # size, position and theme choice between runs.
    profile = APP_HOME / "data" / "window-profile"
    subprocess.Popen(
        [
            browser,
            f"--app={url}",
            f"--user-data-dir={profile}",
            f"--window-size={WINDOW_SIZE}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
    )


def _server_answers(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.6) as resp:
            return resp.read().decode("utf-8", errors="replace") == HEALTH_SENTINEL
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return False


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_and_open_window(port: int) -> None:
    deadline = time.time() + 20
    while time.time() < deadline:
        if _server_answers(port):
            _open_app_window(f"http://127.0.0.1:{port}/")
            return
        time.sleep(0.2)


def _start_logging() -> None:
    """A small log file is the only way to diagnose a problem in a windowless app."""
    try:
        from logging.handlers import RotatingFileHandler

        log_dir = APP_HOME / "data"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_dir / "photo-organizer.log", maxBytes=512_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)
    except OSError:
        pass


def main() -> None:
    import uvicorn

    _start_logging()
    port = SERVER_PORT
    if _server_answers(port):
        # Already running (the person double-clicked the shortcut twice): just bring up
        # a window on the existing server instead of starting a second copy.
        _open_app_window(f"http://127.0.0.1:{port}/")
        return
    if not _port_is_free(port):
        port = _free_port()  # something else owns our usual port

    app = create_app(exit_when_idle=True)
    threading.Thread(target=_wait_and_open_window, args=(port,), daemon=True).start()
    # log_config=None: uvicorn's default logging setup configures a formatter that
    # touches sys.stderr, which is None under pythonw.exe (no console) - this app is
    # launched that way, and it crashes with "Unable to configure formatter 'default'"
    # otherwise.
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", log_config=None)


if __name__ == "__main__":
    main()
