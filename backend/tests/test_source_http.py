import asyncio
import json
import socket
import ssl
import unittest
from unittest.mock import AsyncMock, patch

import httpcore
import httpx

from app.connectors.errors import SourceFetchError, SourceSecurityError
from app.connectors.http_client import PublicHTTPTransport, PublicNetworkBackend, SourceHTTPClient, public_ip, resolve_addresses
from app.core.config import Settings

BASE = "https://hypetv.rs"


def json_response(value, *, status=200, headers=None):
    body = json.dumps(value).encode()
    return httpx.Response(status, headers={"content-type": "application/json", **(headers or {})}, stream=httpx.ByteStream(body))


def mocked_client(handler, **overrides):
    config = Settings(_env_file=None).model_copy(update=overrides)
    return SourceHTTPClient(BASE, config=config, transport_factory=lambda: httpx.MockTransport(handler))


class WireStream(httpcore.AsyncNetworkStream):
    def __init__(self, peer="8.8.8.8", *, read_error=None):
        self.peer = peer
        self.data = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n[]"
        self.read_error = read_error
        self.writes = []
        self.tls = []
        self.closed = False

    async def read(self, max_bytes, timeout=None):
        if self.read_error:
            raise self.read_error
        result, self.data = self.data[:max_bytes], self.data[max_bytes:]
        return result

    async def write(self, buffer, timeout=None):
        self.writes.append(buffer)

    async def aclose(self):
        self.closed = True

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.tls.append((server_hostname, ssl_context.check_hostname, ssl_context.verify_mode))
        return self

    def get_extra_info(self, name):
        return (self.peer, 443) if name == "server_addr" and self.peer is not None else None


class WireBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, stream=None, error=None):
        self.stream = stream or WireStream()
        self.error = error
        self.calls = []

    async def connect_tcp(self, host, port, **kwargs):
        self.calls.append((host, port))
        if self.error:
            raise self.error
        return self.stream


class PublicTransportTests(unittest.IsolatedAsyncioTestCase):
    def client(self, resolver, backend):
        network = PublicNetworkBackend({"hypetv.rs"}, resolver=resolver, backend=backend)
        return SourceHTTPClient(BASE, transport_factory=lambda: PublicHTTPTransport({"hypetv.rs"}, network_backend=network))

    async def test_real_httpcore_path_pins_public_ip_and_preserves_host_tls_verification(self):
        resolver = AsyncMock(return_value=["8.8.8.8"])
        backend = WireBackend()
        with patch.dict("os.environ", {"HTTPS_PROXY": "http://127.0.0.1:9999"}):
            self.assertEqual(await self.client(resolver, backend).get_json(BASE + "/wp-json"), [])
        self.assertEqual(backend.calls, [("8.8.8.8", 443)])
        resolver.assert_awaited_once_with("hypetv.rs", 443)
        self.assertEqual(backend.stream.tls, [("hypetv.rs", True, ssl.CERT_REQUIRED)])
        self.assertIn(b"Host: hypetv.rs", b"".join(backend.stream.writes))

    async def test_all_dns_answers_are_validated_before_any_connection(self):
        for address in ("127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "224.0.0.1", "240.0.0.1", "192.0.2.1", "::1", "::", "fe80::1", "fc00::1", "fec0::1", "ff02::1", "::ffff:127.0.0.1", "64:ff9b::7f00:1", "2002:7f00:1::", "2001:db8::1"):
            with self.subTest(address=address):
                backend = WireBackend()
                client = self.client(AsyncMock(return_value=["8.8.8.8", address]), backend)
                with self.assertRaises(SourceSecurityError):
                    await client.get_json(BASE + "/wp-json")
                self.assertEqual(backend.calls, [])

    async def test_dns_alias_to_private_destination_is_rejected(self):
        backend = WireBackend()
        with self.assertRaises(SourceSecurityError):
            await self.client(AsyncMock(return_value=["10.0.0.2"]), backend).get(BASE)
        self.assertEqual(backend.calls, [])

    async def test_rebinding_on_next_connection_never_opens_private_socket(self):
        resolver = AsyncMock(side_effect=[["8.8.8.8"], ["127.0.0.1"]])
        backend = WireBackend()
        client = self.client(resolver, backend)
        await client.get_json(BASE + "/first")
        with self.assertRaises(SourceSecurityError):
            await client.get_json(BASE + "/second")
        self.assertEqual(backend.calls, [("8.8.8.8", 443)])

    async def test_connection_peer_is_checked_before_sending_http(self):
        for peer in (None, "127.0.0.1", "1.1.1.1"):
            stream = WireStream(peer)
            with self.subTest(peer=peer), self.assertRaises(SourceSecurityError):
                await self.client(AsyncMock(return_value=["8.8.8.8"]), WireBackend(stream)).get(BASE)
            self.assertTrue(stream.closed)
            self.assertEqual(stream.writes, [])

    async def test_connect_and_read_timeouts_have_safe_distinct_error_category(self):
        for backend in (WireBackend(error=httpcore.ConnectTimeout("sensitive details")), WireBackend(WireStream(read_error=httpcore.ReadTimeout("sensitive details")))):
            with self.assertRaises(SourceFetchError) as caught:
                await self.client(AsyncMock(return_value=["8.8.8.8"]), backend).get(BASE)
            self.assertEqual(caught.exception.code, "timeout")
            self.assertNotIn("sensitive", str(caught.exception))

    async def test_dns_failure_is_sanitized(self):
        with patch.object(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(side_effect=socket.gaierror("secret internal resolver"))):
            with self.assertRaises(SourceFetchError) as caught:
                await resolve_addresses("hypetv.rs", 443)
        self.assertEqual(caught.exception.code, "dns_error")
        self.assertNotIn("secret", str(caught.exception))

    async def test_overall_deadline_covers_dns_resolution_without_opening_socket(self):
        async def resolver(host, port):
            await asyncio.sleep(1)
            return ["8.8.8.8"]
        backend = WireBackend()
        client = self.client(resolver, backend)
        client.config = client.config.model_copy(update={"source_http_request_deadline_seconds": .03})
        with self.assertRaises(SourceFetchError) as caught:
            await client.get(BASE)
        self.assertEqual(caught.exception.code, "timeout")
        self.assertEqual(backend.calls, [])

    async def test_same_host_redirect_revalidates_dns_and_blocks_rebinding(self):
        resolver = AsyncMock(side_effect=[["8.8.8.8"], ["127.0.0.1"]])
        backend = WireBackend()
        backend.stream.data = b"HTTP/1.1 302 Found\r\nLocation: /redirected\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        with self.assertRaises(SourceSecurityError):
            await self.client(resolver, backend).get(BASE)
        self.assertEqual(resolver.await_count, 2)
        self.assertEqual(backend.calls, [("8.8.8.8", 443)])


class BoundedHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_host_relative_redirect_is_followed(self):
        requested = []
        def handler(request):
            requested.append(str(request.url))
            return httpx.Response(301, headers={"location": "/wp-json/"}) if len(requested) == 1 else json_response({"routes": {}})
        self.assertEqual(await mocked_client(handler).get_json(BASE + "/wp-json"), {"routes": {}})
        self.assertEqual(requested, [BASE + "/wp-json", BASE + "/wp-json/"])

    async def test_redirects_to_other_hosts_private_ips_credentials_or_http_are_blocked(self):
        for target in ("http://hypetv.rs/wp-json", "https://127.0.0.1/", "https://169.254.169.254/", "https://www.hypeproduction.rs/", "https://hypetv.rs.attacker.invalid/", "https://user:secret@hypetv.rs/", "https://hypetv.rs:8443/"):
            requests = []
            def handler(request):
                requests.append(request)
                return httpx.Response(302, headers={"location": target})
            with self.subTest(target=target), self.assertRaises(SourceSecurityError):
                await mocked_client(handler).get(BASE)
            self.assertEqual(len(requests), 1)

    async def test_redirect_count_is_bounded(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(302, headers={"location": "/next"})
        with self.assertRaises(SourceFetchError) as caught:
            await mocked_client(handler, source_http_max_redirects=2).get(BASE)
        self.assertEqual(caught.exception.code, "redirect_limit")
        self.assertEqual(len(requests), 3)

    async def test_malformed_redirect_is_blocked_with_safe_error(self):
        with self.assertRaises(SourceSecurityError) as caught:
            await mocked_client(lambda request: httpx.Response(302, headers={"location": "https://[secret"})).get(BASE)
        self.assertNotIn("secret", str(caught.exception))

    async def test_http_rejections_never_expose_body(self):
        for status in (403, 429, 500, 502, 503):
            with self.subTest(status=status), self.assertRaises(SourceFetchError) as caught:
                await mocked_client(lambda request: httpx.Response(status, content="private internal response secret")).get_json(BASE)
            self.assertEqual(caught.exception.code, "http_rejected")
            self.assertEqual(caught.exception.status_code, status)
            self.assertNotIn("secret", str(caught.exception))

    async def test_non_json_and_malformed_json_are_classified(self):
        for mime, value in (("text/html", b"<h1>secret</h1>"), ("application/json", b"{invalid"), ("application/json", b"[NaN]")):
            with self.subTest(mime=mime), self.assertRaises(SourceFetchError) as caught:
                await mocked_client(lambda request: httpx.Response(200, headers={"content-type": mime}, stream=httpx.ByteStream(value))).get_json(BASE)
            self.assertEqual(caught.exception.code, "invalid_json")

    async def test_declared_and_streamed_oversized_responses_are_rejected_and_closed(self):
        class Chunks(httpx.AsyncByteStream):
            closed = False
            async def __aiter__(self):
                yield b"x" * 800
                yield b"y" * 800
            async def aclose(self):
                self.closed = True
        for headers in ({}, {"content-length": "5000"}):
            stream = Chunks()
            with self.subTest(headers=headers), self.assertRaises(SourceFetchError) as caught:
                await mocked_client(lambda request: httpx.Response(200, headers=headers, stream=stream), source_http_max_response_bytes=1024).get(BASE)
            self.assertEqual(caught.exception.code, "response_too_large")
            self.assertTrue(stream.closed)

    async def test_unsolicited_compression_is_rejected_without_decoding(self):
        with self.assertRaises(SourceFetchError) as caught:
            await mocked_client(lambda request: httpx.Response(200, headers={"content-encoding": "gzip"}, stream=httpx.ByteStream(b"invalid"))).get(BASE)
        self.assertEqual(caught.exception.code, "unsupported_encoding")

    async def test_overall_deadline_covers_slow_body_and_closes_stream(self):
        class Slow(httpx.AsyncByteStream):
            closed = False
            async def __aiter__(self):
                yield b"["
                await asyncio.sleep(1)
                yield b"]"
            async def aclose(self):
                self.closed = True
        stream = Slow()
        with self.assertRaises(SourceFetchError) as caught:
            await mocked_client(lambda request: httpx.Response(200, stream=stream), source_http_request_deadline_seconds=.03).get(BASE)
        self.assertEqual(caught.exception.code, "timeout")
        self.assertTrue(stream.closed)

    async def test_redirects_do_not_reset_overall_deadline(self):
        async def handler(request):
            await asyncio.sleep(.02)
            return httpx.Response(302, headers={"location": "/next"})
        with self.assertRaises(SourceFetchError) as caught:
            await mocked_client(handler, source_http_request_deadline_seconds=.03).get(BASE)
        self.assertEqual(caught.exception.code, "timeout")
