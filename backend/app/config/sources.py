from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.connectors.base import BaseConnector
from app.connectors.wordpress import WordPressConnector
from app.connectors.errors import SourceSecurityError
from app.connectors.http_client import https_host
from urllib.parse import urlsplit


@dataclass(frozen=True)
class SourceConfig:
    name: str
    url: str
    connector: str
    connector_factory: Callable[[str], BaseConnector]


def _build_wordpress_connector(url: str) -> BaseConnector:
    return WordPressConnector(base_url=url)


def _build_serbia_connector(url: str) -> BaseConnector:
    return WordPressConnector(base_url=url, embed_relations=("wp:featuredmedia", "wp:term"))


HYPE_SOURCES: list[SourceConfig] = [
    SourceConfig(name="Hype Serbia", url="https://hypetv.rs", connector="wordpress", connector_factory=_build_serbia_connector),
    SourceConfig(name="Hype Croatia", url="https://hypetv.hr", connector="wordpress", connector_factory=_build_wordpress_connector),
    SourceConfig(name="Hype Bosnia", url="https://hypebih.ba", connector="wordpress", connector_factory=_build_wordpress_connector),
    SourceConfig(name="Hype Slovenia", url="https://hypetv.si", connector="wordpress", connector_factory=_build_wordpress_connector),
    SourceConfig(name="Hype Macedonia", url="https://hypetv.mk", connector="wordpress", connector_factory=_build_wordpress_connector),
    SourceConfig(name="Hype Production", url="https://www.hypeproduction.rs", connector="wordpress", connector_factory=_build_wordpress_connector),
]


def configured_diagnostic_source(url: str) -> SourceConfig:
    """Authorize only configured HTTPS origins, not arbitrary paths or hosts."""
    host = https_host(url)
    parts = urlsplit(url)
    if parts.path not in ("", "/") or parts.query:
        raise SourceSecurityError()
    for source in HYPE_SOURCES:
        if https_host(source.url) == host:
            return source
    raise SourceSecurityError()
