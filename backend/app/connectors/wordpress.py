from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx

from app.connectors.base import BaseConnector
from app.core.config import settings


class WordPressConnector(BaseConnector):
    def __init__(self, base_url: str, timeout_seconds: float | None = None):
        self.base_url = self._normalize_base_url(base_url)
        self.wp_json_endpoint = urljoin(f"{self.base_url}/", "wp-json") if self.base_url else ""
        self.posts_endpoint = urljoin(f"{self.base_url}/", "wp-json/wp/v2/posts?_embed") if self.base_url else ""
        self.timeout = httpx.Timeout(timeout_seconds or settings.discovery_timeout_seconds)

    @staticmethod
    def _normalize_base_url(url: str) -> str:
        return (url or "").strip().rstrip("/")

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
            return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        except ValueError:
            return False

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
        embedded = post.get("_embedded", {})
        featured_media = embedded.get("wp:featuredmedia", [])
        if featured_media and isinstance(featured_media, list):
            source_url = featured_media[0].get("source_url")
            if isinstance(source_url, str):
                return source_url
        return None

    @staticmethod
    def _extract_categories(post: dict) -> list[str]:
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

    @staticmethod
    def _extract_language(post: dict) -> str | None:
        if isinstance(post.get("lang"), str):
            return post["lang"]
        if isinstance(post.get("language"), str):
            return post["language"]

        embedded = post.get("_embedded", {})
        terms = embedded.get("wp:term", [])
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
        cleaned = re.sub(r"<[^>]*>", "", value)
        return cleaned.strip()

    def _normalize_post(self, post: dict) -> dict[str, object | None | list[str]]:
        title_data = post.get("title") if isinstance(post.get("title"), dict) else {}
        excerpt_data = post.get("excerpt") if isinstance(post.get("excerpt"), dict) else {}

        return {
            "external_id": post.get("id"),
            "title": self._strip_html(title_data.get("rendered") if isinstance(title_data, dict) else None),
            "url": post.get("link"),
            "published_at": post.get("date_gmt") or post.get("date"),
            "featured_image": self._extract_featured_image(post),
            "categories": self._extract_categories(post),
            "excerpt": self._strip_html(excerpt_data.get("rendered") if isinstance(excerpt_data, dict) else None),
            "language": self._extract_language(post),
        }

    async def test_connection(self) -> dict[str, object | None]:
        if not self._is_valid_url(self.base_url):
            return {
                "success": False,
                "wordpress_version": None,
                "endpoint": self.posts_endpoint,
                "error": "Invalid URL",
            }

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                wp_json_response = await client.get(self.wp_json_endpoint)
                if wp_json_response.status_code != 200:
                    return {
                        "success": False,
                        "wordpress_version": None,
                        "endpoint": self.posts_endpoint,
                        "error": f"wp-json returned {wp_json_response.status_code}",
                    }

                wp_json_data = wp_json_response.json()
                wordpress_version = self._extract_wordpress_version(wp_json_data if isinstance(wp_json_data, dict) else {})

                posts_response = await client.get(f"{self.posts_endpoint}&per_page=1")
                if posts_response.status_code != 200:
                    return {
                        "success": False,
                        "wordpress_version": wordpress_version,
                        "endpoint": self.posts_endpoint,
                        "error": f"posts endpoint returned {posts_response.status_code}",
                    }

                return {
                    "success": True,
                    "wordpress_version": wordpress_version,
                    "endpoint": self.posts_endpoint,
                }
        except httpx.TimeoutException:
            return {
                "success": False,
                "wordpress_version": None,
                "endpoint": self.posts_endpoint,
                "error": "Request timed out",
            }
        except (httpx.HTTPError, ValueError):
            return {
                "success": False,
                "wordpress_version": None,
                "endpoint": self.posts_endpoint,
                "error": "Network error",
            }

    async def fetch_latest(self, limit: int = 10) -> list[dict[str, object | None | list[str]]]:
        if not self._is_valid_url(self.base_url):
            raise ValueError("Invalid URL")

        per_page = max(1, min(limit, 100))
        endpoint = f"{self.posts_endpoint}&per_page={per_page}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(endpoint)
                if response.status_code != 200:
                    raise RuntimeError(f"posts endpoint returned {response.status_code}")

                posts = response.json()
                if not isinstance(posts, list):
                    raise RuntimeError("Unexpected posts response format")

                return [self._normalize_post(post) for post in posts if isinstance(post, dict)]
        except httpx.TimeoutException as exc:
            raise RuntimeError("Request timed out") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError("Network error") from exc

    async def health(self) -> dict[str, object | None]:
        connection = await self.test_connection()
        return {
            "connector": "wordpress",
            "success": connection.get("success", False),
            "endpoint": connection.get("endpoint"),
            "wordpress_version": connection.get("wordpress_version"),
        }
