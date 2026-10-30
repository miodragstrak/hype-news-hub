"""Versioned URL identity rules shared by ingestion and migration 20261030_02.

After release, introduce a new version/migration for incompatible rule changes.
Query values are opaque URL bytes, never decoded with Unicode replacement.
"""
import re
from urllib.parse import quote, urlsplit, urlunsplit

_TRACKING = {"fbclid", "gclid", "dclid", "msclkid"}
_UNRESERVED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")
_BAD_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")


def _component(value: str, safe: str) -> str:
    if _BAD_ESCAPE.search(value):
        raise ValueError("Malformed percent escape in URL.")

    def normalize_escape(match):
        char = chr(int(match.group()[1:], 16))
        return char if char in _UNRESERVED else match.group().upper()

    escaped = re.sub(r"%[0-9a-fA-F]{2}", normalize_escape, value)
    # Existing percent bytes stay opaque; literal Unicode becomes UTF-8 escapes.
    return quote(escaped, safe=safe + "%")


def canonicalize_url(value: str) -> str:
    value = value.strip()
    if re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("Control characters are not allowed in URLs.")
    if _BAD_ESCAPE.search(value):
        raise ValueError("Malformed percent escape in URL.")
    parts = urlsplit(value)
    if parts.scheme.lower() not in {"https", "http"} or not parts.hostname or parts.username is not None:
        raise ValueError("Article/source URLs must be absolute HTTP(S) URLs without credentials.")
    host = parts.hostname.lower().encode("idna").decode("ascii")
    if ":" in host:
        host = f"[{host}]"
    port = parts.port
    if port is not None and (parts.scheme.lower(), port) not in {("http", 80), ("https", 443)}:
        host += f":{port}"
    path = _component(parts.path or "/", safe="/:@!$&'()*+,;=-._~")
    path = path.rstrip("/") or "/"
    query = _component(parts.query, safe="!$&'()*+,-./:;=?@_~")
    pairs = []
    for pair in query.split("&") if query else []:
        key = pair.partition("=")[0].lower()
        if not key.startswith("utm_") and key not in _TRACKING:
            pairs.append(pair)
    return urlunsplit((parts.scheme.lower(), host, path, "&".join(pairs), ""))
