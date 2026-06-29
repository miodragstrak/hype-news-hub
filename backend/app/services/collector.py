from __future__ import annotations

import logging
from datetime import datetime

from app.config.sources import HYPE_SOURCES
from app.schemas.article import NormalizedArticle
from app.schemas.collector import CollectArticlesResponse
from app.services.article_normalizer import normalize_articles

logger = logging.getLogger(__name__)


def _published_sort_key(article: NormalizedArticle) -> datetime:
    if not article.published_at:
        return datetime.min

    try:
        return datetime.fromisoformat(article.published_at.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min


async def collect_articles(limit_per_source: int = 5) -> CollectArticlesResponse:
    articles: list[NormalizedArticle] = []
    sources_failed = 0

    for source in HYPE_SOURCES:
        connector = source.connector_factory(source.url)

        try:
            connector_articles = await connector.fetch_latest(limit=limit_per_source)
            articles.extend(
                normalize_articles(
                    connector_articles=connector_articles,
                    source_url=source.url,
                    connector=source.connector,
                    source_name=source.name,
                )
            )
        except Exception as exc:
            sources_failed += 1
            logger.exception("Failed collecting source %s (%s): %s", source.name, source.url, exc)

    sorted_articles = sorted(articles, key=_published_sort_key, reverse=True)

    return CollectArticlesResponse(
        sources_processed=len(HYPE_SOURCES),
        sources_failed=sources_failed,
        articles_total=len(sorted_articles),
        articles=sorted_articles,
    )
