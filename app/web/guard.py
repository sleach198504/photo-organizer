"""Keeps other websites and other programs' browsers from driving the local API.

The server only listens on the loopback address, but a web page open in the same
browser can still reach it: it can send a form POST to http://127.0.0.1:8765/api/shutdown,
or point its own hostname at 127.0.0.1 (DNS rebinding) and then read and write freely.
Browsers always attach honest `Host`, `Origin` and `Sec-Fetch-Site` headers, so checking
them closes both routes without any sign-in step.
"""
from __future__ import annotations

from urllib.parse import urlsplit

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
REFUSAL = "Photo Organizer only answers requests that come from its own window."


def _hostname(netloc: str) -> str | None:
    try:
        return urlsplit(f"//{netloc}").hostname  # handles "[::1]:8765" and strips the port
    except ValueError:
        return None


def is_allowed(host: str | None, origin: str | None, fetch_site: str | None) -> bool:
    """True when the request could only have come from the app's own window."""
    if not host or _hostname(host) not in LOOPBACK_HOSTS:
        return False  # DNS rebinding: the page's own hostname resolves to 127.0.0.1
    if fetch_site == "cross-site":
        return False
    if origin is not None:
        # A page served by this app sends exactly its own address. "null" (sandboxed
        # frames, redirects) and any other site or local port are refused.
        scheme, _, netloc = origin.partition("://")
        if scheme not in ("http", "https") or netloc.lower() != host.lower():
            return False
    return True
