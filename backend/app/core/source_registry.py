from __future__ import annotations

from urllib.parse import urlparse

KNOWN_SOURCES: dict[str, str] = {
    "https://hypetv.hr": "Hype Croatia",
    "https://hypebih.ba": "Hype Bosnia",
    "https://hypetv.si": "Hype Slovenia",
    "https://hypetv.rs": "Hype Serbia",
    "https://www.hypeproduction.rs": "Hype Production",
    "https://hypetv.mk": "Hype Macedonia",
}


def normalize_source_url(url: str) -> str:
    parsed = urlparse(url.strip())
    netloc = parsed.netloc.lower()
    scheme = parsed.scheme.lower()
    return f"{scheme}://{netloc}" if scheme and netloc else url.strip().rstrip("/")


def resolve_source_name(url: str) -> str:
    normalized = normalize_source_url(url)
    if normalized in KNOWN_SOURCES:
        return KNOWN_SOURCES[normalized]

    parsed = urlparse(normalized)
    host = parsed.netloc.replace("www.", "")
    if not host:
        return "Unknown Source"
    return host
