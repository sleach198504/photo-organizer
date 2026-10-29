"""Shared test fixtures: a small synthetic library and a live server to talk to."""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import uvicorn

from app import content_tagging
from app.web.app import create_app


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LiveServer:
    """The real FastAPI app on a real socket, so tests exercise exactly what the window does."""

    def __init__(self) -> None:
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        # Content recognition loads a ~600 MB model; the rest of the pipeline is what these
        # tests are about, and the scan skips that stage cleanly when it is unavailable.
        self._patch = mock.patch.object(content_tagging, "models_downloaded", return_value=False)
        self.server = uvicorn.Server(
            uvicorn.Config(create_app(), host="127.0.0.1", port=self.port, log_level="error", log_config=None)
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> "LiveServer":
        self._patch.start()
        self.thread.start()
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                self.get_raw("/healthz")
                return self
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("test server did not start")

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self._patch.stop()

    def get_raw(self, path: str) -> tuple[int, dict, bytes]:
        try:
            with urllib.request.urlopen(self.base + path, timeout=30) as resp:
                return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict | list | None]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.base + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as resp:
                payload = resp.read()
                return resp.status, json.loads(payload) if payload else None
        except urllib.error.HTTPError as exc:
            with exc:
                payload = exc.read()
                return exc.code, json.loads(payload) if payload else None

    def get(self, path: str):
        return self.call("GET", path)

    def post(self, path: str, body: dict | None = None):
        return self.call("POST", path, body or {})

    def put(self, path: str, body: dict):
        return self.call("PUT", path, body)

    def wait_job(self, name: str, timeout: float = 180) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, snapshot = self.get(f"/api/jobs/{name}")
            if snapshot["state"] not in ("running", "idle"):
                return snapshot
            time.sleep(0.25)
        raise TimeoutError(f"{name} job did not finish")


def build_library(root: Path, scale: float = 0.4) -> dict:
    from dev.make_demo_library import build

    return build(root, scale=scale)
