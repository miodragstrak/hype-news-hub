from __future__ import annotations

import html
import re

from app.core.source_registry import normalize_source_url, resolve_source_name
from app.schemas.article import NormalizedArticle


def _decode_text(value: object | None) -> str:
    if value is None:
        return ""

    decoded = html.unescape(str(value))
    decoded = decoded.replace("\xa0", " ")
    decoded = re.sub(r"\s+", " ", decoded)
    return decoded.strip()


def normalize_articles(
    connector_articles: list[dict],
    source_url: str,
    connector: str = "wordpress",
    source_name: str | None = None,
) -> list[NormalizedArticle]:
    resolved_source_url = normalize_source_url(source_url)
    resolved_source_name = source_name or resolve_source_name(source_url)

    normalized: list[NormalizedArticle] = []

    for article in connector_articles:
        title = _decode_text(article.get("title"))
        article_url = str(article.get("url") or "").strip()

        if not title or not article_url:
            # Skip malformed entries while keeping connector and endpoint stable.
            continue

        categories = article.get("categories")
        safe_categories = [_decode_text(value) for value in categories if _decode_text(value)] if isinstance(categories, list) else []

        external_id = article.get("external_id")
        published_at = article.get("published_at")
        excerpt = article.get("excerpt")
        featured_image = article.get("featured_image")
        language = article.get("language")

        normalized.append(
            NormalizedArticle(
                external_id=str(external_id) if external_id is not None else "",
                connector=connector,
                source=resolved_source_name,
                source_url=resolved_source_url,
                language=str(language).strip() if isinstance(language, str) and language.strip() else None,
                title=title,
                url=article_url,
                published_at=str(published_at) if published_at is not None else None,
                excerpt=_decode_text(excerpt),
                content=None,
                featured_image=str(featured_image).strip() if isinstance(featured_image, str) else None,
                categories=safe_categories,
                raw=None,
            )
        )

    return normalized
