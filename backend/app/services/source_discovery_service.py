from __future__ import annotations

from xml.etree import ElementTree

import httpx

from app.core.config import settings
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


def _extract_wp_featured_image(post: dict) -> str | None:
    embedded = post.get("_embedded", {})
    featured = embedded.get("wp:featuredmedia", [])
    if featured and isinstance(featured, list):
        image = featured[0].get("source_url")
        if isinstance(image, str):
            return image
    return None


def _extract_wp_categories(post: dict) -> list[str]:
    embedded = post.get("_embedded", {})
    terms = embedded.get("wp:term", [])
    categories: list[str] = []

    for term_group in terms:
        if not isinstance(term_group, list):
            continue
        for term in term_group:
            if term.get("taxonomy") == "category" and isinstance(term.get("name"), str):
                categories.append(term["name"])

    return categories


def _extract_wp_sample_article(post: dict) -> DiscoveredArticle:
    return DiscoveredArticle(
        title=(post.get("title") or {}).get("rendered"),
        date=post.get("date"),
        image=_extract_wp_featured_image(post),
        url=post.get("link"),
        categories=_extract_wp_categories(post),
    )


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

    return DiscoveredArticle(title=title, date=date, image=image, url=link)


async def _try_wordpress(client: httpx.AsyncClient, base_url: str) -> tuple[bool, str | None, DiscoveredArticle | None]:
    wp_json_url = f"{base_url}/wp-json"
    posts_url = f"{base_url}/wp-json/wp/v2/posts?_embed&per_page=1"

    is_wordpress = False
    sample_article = None
    posts_endpoint = None

    try:
        wp_response = await client.get(wp_json_url)
        is_wordpress = wp_response.status_code == 200
    except httpx.HTTPError:
        is_wordpress = False

    try:
        posts_response = await client.get(posts_url)
        if posts_response.status_code == 200:
            data = posts_response.json()
            if isinstance(data, list) and data:
                first_post = data[0]
                if isinstance(first_post, dict):
                    sample_article = _extract_wp_sample_article(first_post)
            posts_endpoint = posts_url
            is_wordpress = True
    except (httpx.HTTPError, ValueError):
        pass

    return is_wordpress, posts_endpoint, sample_article


async def _try_rss(client: httpx.AsyncClient, base_url: str) -> tuple[bool, str | None, DiscoveredArticle | None]:
    for path in RSS_PATHS:
        endpoint = f"{base_url}{path}"

        try:
            response = await client.get(endpoint)
            if response.status_code != 200:
                continue

            root = ElementTree.fromstring(response.text)
            sample_article = _extract_rss_sample_article(root)
            return True, endpoint, sample_article
        except (httpx.HTTPError, ElementTree.ParseError):
            continue

    return False, None, None


def _normalize_base_url(url: str) -> str:
    return url.rstrip("/")


async def discover_sources() -> list[DiscoveryResult]:
    timeout = httpx.Timeout(settings.discovery_timeout_seconds)
    results: list[DiscoveryResult] = []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for source in SOURCES:
            name = source["name"]
            base_url = _normalize_base_url(source["url"])

            wordpress = False
            rss = False
            posts_endpoint = None
            rss_endpoint = None
            sample_article = None

            try:
                wordpress, posts_endpoint, wp_sample = await _try_wordpress(client, base_url)
                rss, rss_endpoint, rss_sample = await _try_rss(client, base_url)

                if wp_sample is not None:
                    sample_article = wp_sample
                elif rss_sample is not None:
                    sample_article = rss_sample
            except Exception:
                # Discovery should keep processing even if one source fails.
                pass

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
