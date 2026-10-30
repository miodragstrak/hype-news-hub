"""Runs in a worker thread; synchronous DB work never blocks the API event loop."""
import asyncio
import logging

from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError

from app.schemas.collector import CollectArticlesResponse, CollectionSourceResult
from app.services.article_normalizer import normalize_articles
from app.services.story_service import _story_summary
from app.services.timestamps import published_sort_key

logger = logging.getLogger(__name__)


def collect_persistent(repository, sources, limit, response_headers):
    return asyncio.run(_collect(repository, sources, limit, response_headers))


async def _collect(repository, sources, limit, response_headers):
    articles = []
    results = []
    with repository.collection(sources, limit) as writer:
        try:
            for source in sources:
                writer.begin_source(source.url)
                try:
                    connector = source.connector_factory(source.url)
                    fetched = await connector.fetch_latest(limit=limit)
                    normalized = normalize_articles(fetched, source.url, source.connector, source.name)
                except Exception as exc:
                    logger.warning("Source fetch/normalization failed: %s (%s)", source.name, type(exc).__name__)
                    message = "Unable to collect this source."
                    writer.fail_source(source.url, f"{type(exc).__name__}: {message}")
                    results.append(CollectionSourceResult(name=source.name, url=source.url, status="failed", error=message))
                    continue
                try:
                    stored = writer.save_source(source.url, normalized)
                except (ValueError, DataError, IntegrityError) as exc:
                    # The entire source transaction rolled back; prior sources remain.
                    logger.warning("Source identity/data transaction rejected: %s (%s)", source.name, type(exc).__name__)
                    message = "Source data conflicts with persistent article identities or constraints."
                    writer.fail_source(source.url, f"{type(exc).__name__}: {message}")
                    results.append(CollectionSourceResult(name=source.name, url=source.url, status="failed", error=message))
                    continue
                articles.extend(stored)
                results.append(CollectionSourceResult(name=source.name, url=source.url, status="success", articles_total=len(stored)))
            stories, candidates, headers = writer.finish()
        except BaseException:
            # Best effort only: an unavailable DB can leave a running row. The next
            # exclusive collection marks it interrupted, preserving committed data.
            try:
                writer.finish(error="Collection interrupted by a storage or processing failure.")
            except (SQLAlchemyError, ValueError):
                logger.warning("Unable to finalize interrupted collection history.")
            raise
    response_headers.update(headers)
    articles.sort(key=lambda article: published_sort_key(article.published_at), reverse=True)
    return CollectArticlesResponse(sources_processed=len(sources), sources_failed=sum(result.status == "failed" for result in results),
        articles_total=len(articles), articles=articles, source_results=results,
        stories_total=len(stories), story_candidates_total=candidates, stories=[_story_summary(story) for story in stories])
