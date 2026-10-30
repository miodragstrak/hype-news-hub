from __future__ import annotations

import re
from urllib.parse import urljoin

from app.connectors.base import BaseConnector
from app.core.config import settings
from app.connectors.errors import SourceFetchError, SourceSecurityError
from app.connectors.http_client import SourceHTTPClient, https_host
from app.core.content_safety import plain_text, safe_content_url


class WordPressConnector(BaseConnector):
    def __init__(self, base_url: str, timeout_seconds: float | None = None, *,
                 embed_relations: tuple[str, ...] | None = None, http_client: SourceHTTPClient | None = None):
        self.base_url = self._normalize_base_url(base_url)
        self.wp_json_endpoint = urljoin(f"{self.base_url}/", "wp-json") if self.base_url else ""
        if embed_relations is not None and (not embed_relations or any(not re.fullmatch(r"[a-z0-9:_-]+", relation) for relation in embed_relations)):
            raise ValueError("Embedding relations must be explicit WordPress relation names.")
        embedding = "_embed" if embed_relations is None else "_embed=" + ",".join(embed_relations)
        self.posts_endpoint = urljoin(f"{self.base_url}/", "wp-json/wp/v2/posts?" + embedding) if self.base_url else ""
        self.http = http_client or SourceHTTPClient(self.base_url, read_timeout=timeout_seconds or settings.source_http_read_timeout_seconds)

    @staticmethod
    def _normalize_base_url(url: str) -> str:
        return (url or "").strip().rstrip("/")

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        try:
            https_host(url)
            return True
        except SourceSecurityError:
            return False

    @staticmethod
    def _embedded(post):
        embedded = post.get("_embedded")
        if embedded is None:
            return {}
        if not isinstance(embedded, dict):
            raise SourceFetchError("malformed_structure")
        return embedded

    @staticmethod
    def _terms(post):
        terms = WordPressConnector._embedded(post).get("wp:term")
        if terms is None:
            return []
        if not isinstance(terms, list) or any(not isinstance(group, list) or any(
                not isinstance(term, dict) or (term.get("taxonomy") is not None and not isinstance(term["taxonomy"], str))
                for term in group) for group in terms):
            raise SourceFetchError("malformed_structure")
        return terms

    @staticmethod
    def _extract_wordpress_version(wp_json: dict) -> str | None:
        generator = wp_json.get("generator")
        if not isinstance(generator, str):
            return None

        # Common format: https://wordpress.org/?v=6.6.1
        match = re.search(r"[?&]v=([0-9]+(?:\.[0-9]+){0,2})", generator)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _extract_featured_image(post: dict) -> str | None:
        featured_media = WordPressConnector._embedded(post).get("wp:featuredmedia")
        if featured_media is None:
            return None
        if not isinstance(featured_media, list) or any(not isinstance(item, dict) for item in featured_media):
            raise SourceFetchError("malformed_structure")
        if featured_media:
            return safe_content_url(featured_media[0].get("source_url"))
        return None

    @staticmethod
    def _extract_categories(post: dict) -> list[str]:
        terms = WordPressConnector._terms(post)

        categories: list[str] = []
        for term_group in terms:
            if not isinstance(term_group, list):
                continue
            for term in term_group:
                if term.get("taxonomy") == "category" and isinstance(term.get("name"), str):
                    categories.append(term["name"])
        return categories

    @staticmethod
    def _extract_language(post: dict) -> str | None:
        if isinstance(post.get("lang"), str):
            return post["lang"]
        if isinstance(post.get("language"), str):
            return post["language"]

        terms = WordPressConnector._terms(post)
        for term_group in terms:
            if not isinstance(term_group, list):
                continue
            for term in term_group:
                taxonomy = term.get("taxonomy")
                if taxonomy in {"language", "lang"} and isinstance(term.get("slug"), str):
                    return term["slug"]
        return None

    @staticmethod
    def _strip_html(value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise SourceFetchError("malformed_structure")
        return plain_text(value)

    def _normalize_post(self, post: dict) -> dict[str, object | None | list[str]]:
        title_data = post.get("title") if isinstance(post.get("title"), dict) else {}
        excerpt_data = post.get("excerpt") if isinstance(post.get("excerpt"), dict) else {}
        content_data = post.get("content") if isinstance(post.get("content"), dict) else {}

        return {
            "external_id": post.get("id"),
            "title": self._strip_html(title_data.get("rendered") if isinstance(title_data, dict) else None),
            "url": post.get("link"),
            "published_at": post.get("date_gmt") or post.get("date"),
            "featured_image": self._extract_featured_image(post),
            "categories": self._extract_categories(post),
            "excerpt": self._strip_html(excerpt_data.get("rendered") if isinstance(excerpt_data, dict) else None),
            "language": self._extract_language(post),
            "content": self._strip_html(content_data.get("rendered")),
            "raw": post,
        }

    async def test_connection(self) -> dict[str, object | None]:
        if not self._is_valid_url(self.base_url):
            return {
                "success": False,
                "wordpress_version": None,
                "endpoint": self.posts_endpoint,
                "error": str(SourceSecurityError()),
            }

        try:
            index = await self.http.get_json(self.wp_json_endpoint)
            if not isinstance(index, dict):
                raise SourceFetchError("malformed_structure")
            posts = await self.fetch_latest(limit=1)
            from app.services.source_collection import normalize_source_batch
            normalize_source_batch(posts, self.base_url)
            return {"success": True, "wordpress_version": self._extract_wordpress_version(index), "endpoint": self.posts_endpoint}
        except SourceFetchError as exc:
            return {
                "success": False,
                "wordpress_version": None,
                "endpoint": self.posts_endpoint,
                "error": str(exc),
            }

    async def fetch_latest(self, limit: int = 10) -> list[dict[str, object | None | list[str]]]:
        if not self._is_valid_url(self.base_url):
            raise SourceSecurityError()

        per_page = max(1, min(limit, 100))
        endpoint = f"{self.posts_endpoint}&per_page={per_page}"

        posts = await self.http.get_json(endpoint)
        if not isinstance(posts, list) or any(not isinstance(post, dict) for post in posts):
            raise SourceFetchError("malformed_structure")
        return [self._normalize_post(post) for post in posts]

    async def health(self) -> dict[str, object | None]:
        connection = await self.test_connection()
        return {
            "connector": "wordpress",
            "success": connection.get("success", False),
            "endpoint": connection.get("endpoint"),
            "wordpress_version": connection.get("wordpress_version"),
        }
