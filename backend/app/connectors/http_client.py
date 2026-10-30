"""Direct HTTPS transport with public-IP pinning, TLS hostname checks and bounds."""
import asyncio
from collections.abc import Callable
from ipaddress import ip_address, ip_network
import json
import re
import socket
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

from app.connectors.errors import SourceFetchError, SourceSecurityError
from app.core.config import Settings, settings

_TRANSLATION_RANGES = (ip_network("64:ff9b::/96"), ip_network("64:ff9b:1::/48"))


def _reject_json_constant(value):
    raise ValueError()


def public_ip(value: str):
    try:
        if "%" in value:
            raise ValueError()
        address = ip_address(value)
        if (not address.is_global or address.is_multicast or address.is_reserved
                or getattr(address, "is_site_local", False)
                or getattr(address, "ipv4_mapped", None) is not None
                or getattr(address, "sixtofour", None) is not None
                or getattr(address, "teredo", None) is not None
                or any(address.version == network.version and address in network for network in _TRANSLATION_RANGES)):
            raise ValueError()
        return address
    except ValueError:
        raise SourceSecurityError() from None


def https_host(url: str) -> str:
    try:
        if not isinstance(url, str) or re.search(r"[\x00-\x20\x7f]", url):
            raise ValueError()
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username is not None or parts.port not in (None, 443) or parts.fragment:
            raise ValueError()
        hostname = parts.hostname.lower().encode("idna").decode("ascii")
        if "%" in hostname or hostname.endswith("."):
            raise ValueError()
        return hostname
    except (ValueError, UnicodeError):
        raise SourceSecurityError() from None


async def resolve_addresses(host: str, port: int) -> list[str]:
    try:
        answers = await asyncio.get_running_loop().getaddrinfo(host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
        addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
        if not addresses:
            raise OSError()
        return addresses
    except OSError:
        raise SourceFetchError("dns_error") from None


class PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, allowed_hosts, *, resolver=resolve_addresses, backend=None):
        self.allowed_hosts = frozenset(allowed_hosts)
        self.resolver = resolver
        self.backend = backend or httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if host not in self.allowed_hosts or port != 443:
            raise SourceSecurityError()
        async with asyncio.timeout(timeout):
            answers = await self.resolver(host, port)
            # Validate EVERY A/AAAA result before opening any socket.
            addresses = [public_ip(answer) for answer in answers]
            if not addresses:
                raise SourceFetchError("dns_error")
            timed_out = False
            for address in addresses:
                try:
                    # Numeric IP prevents a second hostname lookup/rebinding. TLS
                    # remains httpcore's responsibility using the original origin.
                    stream = await self.backend.connect_tcp(str(address), port, timeout=timeout,
                        local_address=local_address, socket_options=socket_options)
                except httpcore.ConnectTimeout:
                    timed_out = True
                    continue
                except httpcore.ConnectError:
                    continue
                try:
                    peer = stream.get_extra_info("server_addr")
                    if peer is None or public_ip(peer[0]) != address:
                        raise SourceSecurityError()
                except BaseException:
                    await stream.aclose()
                    raise
                return stream
        raise SourceFetchError("timeout" if timed_out else "network_error")


class _ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        async for chunk in self.stream:
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class PublicHTTPTransport(httpx.AsyncBaseTransport):
    def __init__(self, allowed_hosts, *, network_backend=None):
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=httpcore.default_ssl_context(),
            network_backend=network_backend or PublicNetworkBackend(allowed_hosts),
            max_connections=2, max_keepalive_connections=0, retries=0, http2=False,
        )

    async def handle_async_request(self, request):
        extensions = {key: value for key, value in request.extensions.items() if key != "sni_hostname"}
        result = await self.pool.handle_async_request(httpcore.Request(
            method=request.method,
            url=httpcore.URL(scheme=request.url.raw_scheme, host=request.url.raw_host, port=request.url.port, target=request.url.raw_path),
            headers=request.headers.raw, content=request.stream, extensions=extensions,
        ))
        return httpx.Response(result.status, headers=result.headers, stream=_ResponseStream(result.stream), extensions=result.extensions)

    async def aclose(self):
        await self.pool.aclose()


class SourceHTTPClient:
    def __init__(self, base_url: str, *, read_timeout: float | None = None, config: Settings | None = None,
                 redirect_hosts=(), transport_factory: Callable | None = None):
        self.config = config or settings
        self.allowed_hosts = frozenset((https_host(base_url), *redirect_hosts))
        self.read_timeout = read_timeout or self.config.source_http_read_timeout_seconds
        self.transport_factory = transport_factory or (lambda: PublicHTTPTransport(self.allowed_hosts))

    def _validate(self, url):
        if https_host(url) not in self.allowed_hosts:
            raise SourceSecurityError()

    async def get(self, url: str) -> httpx.Response:
        try:
            async with asyncio.timeout(self.config.source_http_request_deadline_seconds):
                timeout = httpx.Timeout(self.read_timeout, connect=self.config.source_http_connect_timeout_seconds)
                async with httpx.AsyncClient(transport=self.transport_factory(), trust_env=False,
                        follow_redirects=False, timeout=timeout, headers={"Accept-Encoding": "identity"}) as client:
                    for hop in range(self.config.source_http_max_redirects + 1):
                        self._validate(url)
                        async with client.stream("GET", url) as response:
                            if response.is_redirect:
                                if hop == self.config.source_http_max_redirects:
                                    raise SourceFetchError("redirect_limit")
                                location = response.headers.get("location")
                                if not location:
                                    raise SourceFetchError("malformed_structure")
                                try:
                                    url = urljoin(url, location)
                                except ValueError:
                                    raise SourceSecurityError() from None
                                self._validate(url)
                                continue
                            if response.status_code != 200:
                                raise SourceFetchError("http_rejected", status_code=response.status_code)
                            if response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                                raise SourceFetchError("unsupported_encoding")
                            limit = self.config.source_http_max_response_bytes
                            try:
                                length = int(response.headers.get("content-length", "0"))
                            except ValueError:
                                raise SourceFetchError("malformed_structure") from None
                            if length < 0:
                                raise SourceFetchError("malformed_structure")
                            if length > limit:
                                raise SourceFetchError("response_too_large")
                            body = bytearray()
                            async for chunk in response.aiter_raw():
                                if len(body) + len(chunk) > limit:
                                    raise SourceFetchError("response_too_large")
                                body.extend(chunk)
                            return httpx.Response(200, headers=response.headers, content=bytes(body), request=response.request)
        except SourceFetchError:
            raise
        except httpx.InvalidURL:
            raise SourceSecurityError() from None
        except (TimeoutError, httpx.TimeoutException, httpcore.TimeoutException):
            raise SourceFetchError("timeout") from None
        except (httpx.HTTPError, httpcore.NetworkError, httpcore.ProtocolError, OSError):
            raise SourceFetchError("network_error") from None

    async def get_json(self, url: str):
        response = await self.get(url)
        mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if mime != "application/json" and not mime.endswith("+json"):
            raise SourceFetchError("invalid_json")
        try:
            return json.loads(response.content, parse_constant=_reject_json_constant)
        except (ValueError, UnicodeError, RecursionError):
            raise SourceFetchError("invalid_json") from None
