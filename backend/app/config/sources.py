from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.connectors.base import BaseConnector
from app.connectors.wordpress import WordPressConnector


@dataclass(frozen=True)
class SourceConfig:
    name: str
    url: str
    connector: str
    connector_factory: Callable[[str], BaseConnector]


def _build_wordpress_connector(url: str) -> BaseConnector:
    return WordPressConnector(base_url=url, timeout_seconds=10.0)


HYPE_SOURCES: list[SourceConfig] = [
    SourceConfig(name="Hype Serbia", url="https://hypetv.rs", connector="wordpress", connector_factory=_build_wordpress_connector),
    SourceConfig(name="Hype Croatia", url="https://hypetv.hr", connector="wordpress", connector_factory=_build_wordpress_connector),
    SourceConfig(name="Hype Bosnia", url="https://hypebih.ba", connector="wordpress", connector_factory=_build_wordpress_connector),
    SourceConfig(name="Hype Slovenia", url="https://hypetv.si", connector="wordpress", connector_factory=_build_wordpress_connector),
    SourceConfig(name="Hype Macedonia", url="https://hypetv.mk", connector="wordpress", connector_factory=_build_wordpress_connector),
    SourceConfig(name="Hype Production", url="https://www.hypeproduction.rs", connector="wordpress", connector_factory=_build_wordpress_connector),
]
