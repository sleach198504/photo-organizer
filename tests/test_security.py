"""The local API must refuse requests that did not come from the app's own window."""
from __future__ import annotations

import http.client
import unittest

from app.web.guard import is_allowed

from .helpers import LiveServer


class GuardRuleTests(unittest.TestCase):
    def test_own_window_is_allowed(self) -> None:
        self.assertTrue(is_allowed("127.0.0.1:8765", None, None))
        self.assertTrue(is_allowed("127.0.0.1:8765", "http://127.0.0.1:8765", "same-origin"))
        self.assertTrue(is_allowed("localhost:8765", "http://localhost:8765", None))
        self.assertTrue(is_allowed("[::1]:8765", "http://[::1]:8765", None))

    def test_rebinding_hostnames_are_refused(self) -> None:
        self.assertFalse(is_allowed("evil.example:8765", None, None))
        self.assertFalse(is_allowed("127.0.0.1.evil.example", None, None))
        self.assertFalse(is_allowed("localhost.evil.example:8765", None, None))
        self.assertFalse(is_allowed(None, None, None))
        self.assertFalse(is_allowed("", None, None))

    def test_foreign_origins_are_refused(self) -> None:
        self.assertFalse(is_allowed("127.0.0.1:8765", "https://evil.example", None))
        self.assertFalse(is_allowed("127.0.0.1:8765", "null", None))
        self.assertFalse(is_allowed("127.0.0.1:8765", "http://127.0.0.1:3000", None))  # another local app
        self.assertFalse(is_allowed("127.0.0.1:8765", "http://localhost:8765", None))  # different host spelling
        self.assertFalse(is_allowed("127.0.0.1:8765", "file://127.0.0.1:8765", None))

    def test_cross_site_fetches_are_refused(self) -> None:
        self.assertFalse(is_allowed("127.0.0.1:8765", None, "cross-site"))


class LiveGuardTests(unittest.TestCase):
    """Against the real server, forging the headers a hostile page's browser would send."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = LiveServer()
        cls.server.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.__exit__(None, None, None)

    def send(self, method: str, path: str, headers: dict | None = None) -> int:
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        try:
            # skip_host lets a test supply its own Host header, as a rebinding page's browser would.
            conn.putrequest(method, path, skip_host="Host" in (headers or {}))
            for name, value in (headers or {}).items():
                conn.putheader(name, value)
            conn.putheader("Content-Length", "0")
            conn.endheaders()
            return conn.getresponse().status
        finally:
            conn.close()

    def test_own_window_requests_work(self) -> None:
        own = f"127.0.0.1:{self.server.port}"
        self.assertEqual(self.send("GET", "/healthz"), 200)
        self.assertEqual(self.send("GET", "/api/settings", {"Host": own, "Sec-Fetch-Site": "same-origin"}), 200)
        self.assertEqual(self.send("POST", "/api/heartbeat", {"Host": own, "Origin": f"http://{own}"}), 200)

    def test_licences_page_is_served(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        try:
            conn.request("GET", "/api/licences")
            response = conn.getresponse()
            body = response.read().decode("utf-8")
        finally:
            conn.close()
        self.assertEqual(response.status, 200)
        self.assertIn("GNU GENERAL PUBLIC LICENSE", body)
        self.assertIn("GeoNames", body)

    def test_forged_host_is_refused(self) -> None:
        self.assertEqual(self.send("GET", "/api/settings", {"Host": "rebind.example:8765"}), 403)
        self.assertEqual(self.send("GET", "/", {"Host": "rebind.example"}), 403)

    def test_foreign_origin_cannot_write(self) -> None:
        for origin in ("https://evil.example", "null"):
            self.assertEqual(self.send("POST", "/api/heartbeat", {"Origin": origin}), 403, origin)
            self.assertEqual(self.send("PUT", "/api/settings", {"Origin": origin}), 403, origin)
            self.assertEqual(self.send("POST", "/api/shutdown", {"Origin": origin}), 403, origin)
        self.assertEqual(self.send("GET", "/healthz"), 200)  # still running

    def test_cross_site_fetch_metadata_is_refused(self) -> None:
        self.assertEqual(self.send("GET", "/api/settings", {"Sec-Fetch-Site": "cross-site"}), 403)


if __name__ == "__main__":
    unittest.main()
