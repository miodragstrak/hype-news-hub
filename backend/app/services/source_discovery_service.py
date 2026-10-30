from __future__ import annotations

from xml.etree import ElementTree

import logging

from app.config.sources import configured_diagnostic_source
from app.connectors.errors import SourceFetchError, SourceSecurityError
from app.core.content_safety import plain_text, safe_content_url
from app.services.source_collection import normalize_source_batch
from app.schemas.discovery import DiscoveredArticle, DiscoveryResult

SOURCES: list[dict[str, str]] = [
    {"name": "Hype Croatia", "url": "https://hypetv.hr"},
    {"name": "Hype BiH", "url": "https://hypebih.ba"},
    {"name": "Hype Slovenia", "url": "https://hypetv.si"},
    {"name": "Hype Serbia", "url": "https://hypetv.rs"},
    {"name": "Hype Production", "url": "https://www.hypeproduction.rs"},
    {"name": "Hype North Macedonia", "url": "https://hypetv.mk"},
]

RSS_PATHS = ["/feed/", "/rss", "/rss.xml", "/feed.xml"]
logger = logging.getLogger(__name__)


def _find_first_text(element: ElementTree.Element, tags: list[str]) -> str | None:
    for tag in tags:
        found = element.find(tag)
        if found is not None and found.text:
            return found.text.strip()
    return None


def _extract_rss_sample_article(root: ElementTree.Element) -> DiscoveredArticle | None:
    item = root.find("./channel/item")
    if item is None:
        item = root.find("./entry")
    if item is None:
        item = root.find("{http://www.w3.org/2005/Atom}entry")

    if item is None:
        return None

    title = _find_first_text(item, ["title", "{http://www.w3.org/2005/Atom}title"])
    date = _find_first_text(
        item,
        [
            "pubDate",
            "published",
            "updated",
            "{http://www.w3.org/2005/Atom}published",
            "{http://www.w3.org/2005/Atom}updated",
            "{http://purl.org/dc/elements/1.1/}date",
        ],
    )
    link = _find_first_text(item, ["link", "{http://www.w3.org/2005/Atom}link"])

    atom_link = item.find("{http://www.w3.org/2005/Atom}link")
    if atom_link is not None and atom_link.attrib.get("href"):
        link = atom_link.attrib["href"]

    image = None
    media_content = item.find("{http://search.yahoo.com/mrss/}content")
    media_thumbnail = item.find("{http://search.yahoo.com/mrss/}thumbnail")
    enclosure = item.find("enclosure")

    if media_content is not None:
        image = media_content.attrib.get("url")
    elif media_thumbnail is not None:
        image = media_thumbnail.attrib.get("url")
    elif enclosure is not None and enclosure.attrib.get("type", "").startswith("image/"):
        image = enclosure.attrib.get("url")

    return DiscoveredArticle(title=plain_text(title), date=date, image=safe_content_url(image), url=safe_content_url(link))


async def _try_wordpress(connector, source) -> tuple[bool, str | None, DiscoveredArticle | None]:

    is_wordpress = False
    sample_article = None
    posts_endpoint = None

    try:
        index = await connector.http.get_json(connector.wp_json_endpoint)
        is_wordpress = isinstance(index, dict)
    except SourceSecurityError:
        raise
    except SourceFetchError as exc:
        logger.info("discovery_stage=index source=%s outcome=%s", source.name, exc.code)

    try:
        data = await connector.fetch_latest(limit=1)
        normalized = normalize_source_batch(data, source.url, source.connector, source.name)
        if normalized:
            article = normalized[0]
            sample_article = DiscoveredArticle(title=article.title, date=article.published_at,
                image=article.featured_image, url=article.url, categories=article.categories)
        posts_endpoint = connector.posts_endpoint + "&per_page=1"
        is_wordpress = True
    except SourceSecurityError:
        raise
    except SourceFetchError as exc:
        logger.info("discovery_stage=posts source=%s outcome=%s", source.name, exc.code)

    return is_wordpress, posts_endpoint, sample_article


async def _try_rss(client, base_url: str) -> tuple[bool, str | None, DiscoveredArticle | None]:
    for path in RSS_PATHS:
        endpoint = f"{base_url}{path}"

        try:
            response = await client.get(endpoint)
            if b"\x00" in response.content or b"<!DOCTYPE" in response.content.upper() or b"<!ENTITY" in response.content.upper():
                raise SourceFetchError("malformed_structure")
            root = ElementTree.fromstring(response.content)
            if root.tag not in {"rss", "feed", "{http://www.w3.org/2005/Atom}feed"}:
                continue
            sample_article = _extract_rss_sample_article(root)
            return True, endpoint, sample_article
        except SourceSecurityError:
            raise
        except (SourceFetchError, ElementTree.ParseError):
            continue

    return False, None, None


def _normalize_base_url(url: str) -> str:
    return url.rstrip("/")


async def discover_sources() -> list[DiscoveryResult]:
    results: list[DiscoveryResult] = []

    for source in SOURCES:
        name = source["name"]
        base_url = _normalize_base_url(source["url"])

        wordpress = False
        rss = False
        posts_endpoint = None
        rss_endpoint = None
        sample_article = None

        try:
            configured = configured_diagnostic_source(base_url)
            connector = configured.connector_factory(configured.url)
            wordpress, posts_endpoint, wp_sample = await _try_wordpress(connector, configured)
            rss, rss_endpoint, rss_sample = await _try_rss(connector.http, configured.url)
            sample_article = wp_sample if wp_sample is not None else rss_sample
        except SourceFetchError as exc:
            logger.warning("discovery_stage=source source=%s outcome=%s", name, exc.code)
        except Exception as exc:
            logger.warning("discovery_stage=source source=%s outcome=connector_error type=%s", name, type(exc).__name__)

        # Existing API hint only; no scraping or collection fallback is executed.
        preferred = "html_scraping"
        if wordpress and posts_endpoint:
            preferred = "wordpress"
        elif rss and rss_endpoint:
            preferred = "rss"

        results.append(
            DiscoveryResult(
                name=name,
                url=base_url,
                wordpress=wordpress,
                rss=rss,
                preferred=preferred,
                posts_endpoint=posts_endpoint,
                rss_endpoint=rss_endpoint,
                sample_article=sample_article,
            )
        )

    return results
