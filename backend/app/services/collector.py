from __future__ import annotations

import logging
from datetime import datetime
from starlette.concurrency import run_in_threadpool

from app.config.sources import HYPE_SOURCES
from app.schemas.article import NormalizedArticle
from app.schemas.collector import CollectArticlesResponse, CollectionSourceResult
from app.services.source_collection import normalize_source_batch
from app.connectors.errors import SourceFetchError
from app.services.story_service import build_stories_from_articles, set_latest_stories
from app.services.timestamps import published_sort_key

logger = logging.getLogger(__name__)


def _published_sort_key(article: NormalizedArticle) -> datetime:
    return published_sort_key(article.published_at)


async def collect_articles(limit_per_source: int = 5, repository=None, response_headers=None) -> CollectArticlesResponse:
    if repository is not None:
        from app.services.persistent_collector import collect_persistent
        return await run_in_threadpool(collect_persistent, repository, HYPE_SOURCES, limit_per_source,
                                      response_headers if response_headers is not None else {})
    articles: list[NormalizedArticle] = []
    sources_failed = 0
    source_results: list[CollectionSourceResult] = []

    for source in HYPE_SOURCES:
        try:
            connector = source.connector_factory(source.url)
            connector_articles = await connector.fetch_latest(limit=limit_per_source)
            normalized = normalize_source_batch(
                connector_articles=connector_articles,
                source_url=source.url,
                connector=source.connector,
                source_name=source.name,
            )
            articles.extend(normalized)
            source_results.append(CollectionSourceResult(
                name=source.name, url=source.url, status="success", articles_total=len(normalized),
            ))
        except Exception as exc:
            sources_failed += 1
            logger.exception("Failed collecting source %s (%s): %s", source.name, source.url, exc)
            source_results.append(CollectionSourceResult(
                name=source.name, url=source.url, status="failed", error=str(exc) if isinstance(exc, SourceFetchError) else "Unable to collect this source.",
            ))

    sorted_articles = sorted(articles, key=_published_sort_key, reverse=True)
    story_build = build_stories_from_articles(sorted_articles)
    # A failed attempt must not erase the last usable in-memory snapshot.
    if sources_failed < len(HYPE_SOURCES):
        set_latest_stories(story_build.stories)

    return CollectArticlesResponse(
        sources_processed=len(HYPE_SOURCES),
        sources_failed=sources_failed,
        source_results=source_results,
        articles_total=len(sorted_articles),
        articles=sorted_articles,
        story_candidates_total=story_build.story_candidates_total,
        stories_total=len(story_build.stories),
        stories=[
            {
                "id": story.id,
                "headline": story.headline,
                "sources": story.sources,
                "article_count": len(story.articles),
                "similarity_score": story.similarity_score,
                "status": "review" if len(story.articles) > 1 else story.status,
                "published_at": story.published_at,
            }
            for story in story_build.stories
        ],
    )
