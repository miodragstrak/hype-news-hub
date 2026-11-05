import unittest
import socket
import threading
import time
import uvicorn
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from app.selfhosted import create_selfhosted_app
from app.api.trusted_request import authority
from tests.test_selfhosted import selfhosted_settings

ORIGIN = "https://news.example.invalid"


class TrustedRequestTests(unittest.TestCase):
    def test_real_uvicorn_wire_targets_never_bypass_the_gate(self):
        for enabled in (True, False):
            app = create_selfhosted_app(selfhosted_settings(auth_enabled=enabled, auth_trusted_proxy_ips="127.0.0.1"))
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(16)
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="off", ws="none"))
            thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 5
                while not server.started and thread.is_alive() and time.monotonic() < deadline: time.sleep(0.01)
                self.assertTrue(server.started)
                cases = [
                    ("/api/discovery", "news.example.invalid", ""),
                    ("/api/discovery", "news.example.invalid/?ignored=", ""),
                    ("/api/discovery", "news.example.invalid:443/?ignored=", ""),
                    ("/api%2fdiscovery", "news.example.invalid", ""),
                    ("http://news.example.invalid/api/discovery", "news.example.invalid", ""),
                    ("http://evil.invalid/api/discovery", "news.example.invalid", ""),
                    ("/api/discovery", "news.example.invalid", "X-Forwarded-Host: news.example.invalid/?x=\r\nX-Original-URL: /\r\n"),
                    ("/api/discovery", "news.example.invalid", "Host: evil.invalid\r\n"),
                ]
                for target, host, extra in cases:
                    with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
                        connection.sendall(f"GET {target} HTTP/1.1\r\nHost: {host}\r\n{extra}Connection: close\r\n\r\n".encode("ascii"))
                        response = b""
                        while b"\r\n" not in response and len(response) < 4096:
                            chunk = connection.recv(4096)
                            if not chunk: break
                            response += chunk
                    status = int(response.split(b" ", 2)[1])
                    self.assertIn(status, (400, 401 if enabled else 503), (target, host, status))
            finally:
                server.should_exit = True
                thread.join(timeout=5)
                listener.close()
                self.assertFalse(thread.is_alive())

    def test_ipv6_and_canonical_authority_validation(self):
        self.assertEqual(authority("[2001:db8::1]:443"), ("2001:db8::1", 443))
        self.assertEqual(authority("NEWS.EXAMPLE.INVALID:443"), ("news.example.invalid", 443))
        for invalid in ["[2001:db8::1]evil:443", "[::1]ignored", "[::1]:", "[::1]:0", "2001:db8::1", "[::1%25zone]:443"]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError): authority(invalid)

    def test_original_host_bypass_and_unexpected_authorities_fail_before_routes(self):
        bad = ["news.example.invalid/?ignored=", "news.example.invalid:443/?ignored=", "news.example.invalid/#x",
               "news.example.invalid@evil.invalid", "news.example.invalid\\evil", "news.example.invalid%2f",
               "evil.invalid", "news.example.invalid.evil", "news.example.invalid.", "news.example.invalid:444",
               "news.example.invalid:", "news.example.invalid:0", "news.example.invalid:65536", "news.example.invalid,evil.invalid"]
        with patch("app.api.routes.discovery.discover_sources", new=AsyncMock(return_value=[])) as discovery:
            for enabled in (True, False):
                app = create_selfhosted_app(selfhosted_settings(auth_enabled=enabled, auth_trusted_proxy_ips="127.0.0.1"))
                with TestClient(app, base_url=ORIGIN) as client:
                    self.assertEqual(client.get("/api/discovery").status_code, 401 if enabled else 503)
                    for host in bad:
                        with self.subTest(enabled=enabled, host=host):
                            result = client.get("/api/discovery", headers={"Host": host, "X-Forwarded-Host": "news.example.invalid", "X-Original-URL": "/"})
                            self.assertEqual(result.status_code, 400)
                            self.assertNotIn(host, result.text)
                    self.assertEqual(client.get("/", headers=[("Host", "news.example.invalid"), ("Host", "news.example.invalid")]).status_code, 400)
                discovery.assert_not_called()

    def test_encoded_and_absolute_form_targets_cannot_reach_protected_routes(self):
        for enabled in (True, False):
            app = create_selfhosted_app(selfhosted_settings(auth_enabled=enabled, auth_trusted_proxy_ips="127.0.0.1"))
            with patch("app.api.routes.discovery.discover_sources", new=AsyncMock(return_value=[])) as discovery, TestClient(app, base_url=ORIGIN) as client:
                for target in ["/api%2fdiscovery", "/%61pi/discovery", "/api%252fdiscovery", ORIGIN + "/api/discovery", "/api/discovery?next=/"]:
                    self.assertEqual(client.get(target).status_code, 401 if enabled else 503, target)
                # An absolute URL supplied to the HTTP client is normalized into
                # origin-form by it; the direct ASGI probe below covers raw targets.
                discovery.assert_not_called()

    def test_only_local_health_probe_accepts_loopback_authority(self):
        app = create_selfhosted_app(selfhosted_settings())
        with patch("app.api.readiness.check_database"), TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)) as client:
            self.assertEqual(client.get("/ready").status_code, 200)
            self.assertEqual(client.get("/api/stories").status_code, 400)
        with TestClient(app, base_url="http://127.0.0.1:8000", client=("198.51.100.1", 1234)) as client:
            self.assertEqual(client.get("/ready").status_code, 400)


class RawTargetTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_asgi_targets_host_duplicates_and_forwarding_headers(self):
        for enabled in (True, False):
            app = create_selfhosted_app(selfhosted_settings(auth_enabled=enabled, auth_trusted_proxy_ips="127.0.0.1"))
            for raw, path, headers, expected in [
                (b"http://news.example.invalid/api/discovery", "/api/discovery", [(b"host", b"news.example.invalid")], 400),
                (b"/api/discovery", "http://news.example.invalid/api/discovery", [(b"host", b"news.example.invalid")], 400),
                (b"/api/discovery", "/api/discovery", [], 400),
                (b"/api/discovery", "/api/discovery", [(b"host", b"news.example.invalid"), (b"host", b"evil.invalid")], 400),
                (b"/api/discovery", "/api/discovery", [(b"host", b"news.example.invalid"), (b"x-forwarded-host", b"news.example.invalid/?x=")], 401 if enabled else 503),
                (b"/api/discovery", "/api/discovery", [(b"host", b"\xff")], 400),
            ]:
                sent = []
                async def receive(): return {"type": "http.request", "body": b"", "more_body": False}
                async def send(message): sent.append(message)
                scope = dict(type="http", asgi={"version": "3.0"}, http_version="1.1", method="GET", scheme="https", path=path,
                             raw_path=raw, query_string=b"", root_path="", headers=headers, client=("198.51.100.1", 1234), server=("news.example.invalid", 443))
                await app(scope, receive, send)
                self.assertEqual(next(m["status"] for m in sent if m["type"] == "http.response.start"), expected)
