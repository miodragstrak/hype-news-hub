"""Outermost self-hosted ASGI boundary. Never reconstruct a URL to authorize a path."""
from ipaddress import ip_address
import re
from urllib.parse import urlsplit

from starlette.responses import JSONResponse


def authority(value):
    # Host is an authority, never a URL. Reject delimiters before parsing ports.
    if not value or not value.isascii() or any(c in value for c in "/\\?#@%,") or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise ValueError()
    parsed = urlsplit("//" + value)
    host, port = parsed.hostname, parsed.port
    if not host or parsed.username is not None or parsed.password is not None:
        raise ValueError()
    if ":" in host:
        host = ip_address(host).compressed
        if not re.fullmatch(r"\[[0-9a-fA-F:.]+\](?::[0-9]+)?", value):
            raise ValueError()
    elif len(host) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")):
        raise ValueError()
    if value.endswith(":") or (port is not None and not 1 <= port <= 65535):
        raise ValueError()
    return host, port or 443


class TrustedRequestBoundary:
    def __init__(self, app, origin):
        self.app = app
        self.expected = authority(urlsplit(origin).netloc)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        try:
            path = scope.get("path", "")
            raw = scope.get("raw_path", b"/")
            if (not isinstance(path, str) or not path.startswith("/") or path.startswith("//")
                    or any(ord(c) < 32 or ord(c) == 127 or c == "\\" for c in path)
                    or not raw.startswith(b"/") or raw.startswith(b"//")):
                raise ValueError()
            hosts = [v.decode("ascii") for k, v in scope.get("headers", []) if k.lower() == b"host"]
            if len(hosts) != 1:
                raise ValueError()
            host = authority(hosts[0])
            # Docker's in-container health probe is the sole non-public authority.
            peer = scope.get("client")
            health = (path in {"/", "/ready"} and scope.get("method") == "GET"
                      and peer and ip_address(peer[0]).is_loopback
                      and host in {("127.0.0.1", 8000), ("::1", 8000)}) if host != self.expected else False
            if host != self.expected and not health:
                raise ValueError()
        except (ValueError, UnicodeError, TypeError):
            response = JSONResponse({"detail": "Invalid request authority or target."}, status_code=400,
                                    headers={"Cache-Control": "no-store"})
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)
