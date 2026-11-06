"""Bounded private queue reads in one repeatable-read, read-only snapshot."""
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import func, select, true
from sqlalchemy.orm import aliased, selectinload

from app.models import (
    AIProcessingRun,
    CollectedArticle,
    EditorialDraft,
    NewsSource,
    Story,
    StoryArticle,
)
from app.repositories.news_repository import PostgresNewsRepository
from app.schemas.article import NormalizedArticle
from app.schemas.editorial_queue import (
    PrivateEditorialQueueResponse,
    PrivateEditorialQueueStory,
    QueueAIStatus,
    QueueEditorialStatus,
)
from app.schemas.story import Story as APIStory
from app.schemas.story import StoryStatus
from app.services.editorial_intelligence import build_editorial_story


def _intelligence_story(story: Story) -> APIStory:
    """Reuse scoring with source metadata only; do not load article bodies or raw JSON."""
    articles = []
    for link in sorted(story.article_links, key=lambda item: (not item.is_primary, str(item.article_id))):
        article = link.article
        metadata = article.source_metadata or {}
        articles.append(NormalizedArticle(
            external_id=metadata.get("external_id", article.external_id or ""),
            connector=metadata.get("connector", article.source.connector),
            source=metadata.get("source", article.source.name),
            source_url=metadata.get("source_url", article.source.url),
            title=article.title, url=article.url, language=article.language,
            published_at=metadata.get("published_at", article.published_at.isoformat() if article.published_at else None),
        ))
    return APIStory(id=str(story.id), headline=story.headline, primary_article=articles[0], articles=articles,
        sources=sorted({article.source for article in articles}), categories=story.categories,
        published_at=articles[0].published_at, similarity_score=story.similarity_score,
        status=cast(StoryStatus, story.status), language=story.language)


def get_private_editorial_queue(repository: PostgresNewsRepository, limit: int, offset: int) -> PrivateEditorialQueueResponse:
    # The existing (story_id, created_at, id) index supports a bounded lookup per
    # story inside one SQL statement. Explicit columns exclude all sealed payloads.
    eligible = Story.article_links.any()
    page = aliased(Story, select(Story).where(eligible).order_by(
        Story.published_at.desc().nulls_last(), Story.id.desc()).limit(limit).offset(offset).subquery())
    latest = select(AIProcessingRun.id.label("suggestion_id"), AIProcessingRun.status.label("ai_status"),
        AIProcessingRun.created_at.label("ai_created_at"), AIProcessingRun.completed_at.label("ai_completed_at"),
        AIProcessingRun.expires_at.label("ai_expires_at")).where(AIProcessingRun.story_id == page.id).order_by(
        AIProcessingRun.created_at.desc(), AIProcessingRun.id.desc()).limit(1).correlate(page).lateral()
    links = selectinload(page.article_links).joinedload(StoryArticle.article).load_only(
        CollectedArticle.external_id, CollectedArticle.source_metadata, CollectedArticle.title,
        CollectedArticle.url, CollectedArticle.language, CollectedArticle.published_at,
        raiseload=True).joinedload(CollectedArticle.source).load_only(NewsSource.name, NewsSource.url, NewsSource.connector, raiseload=True)
    with repository.read() as session:
        total = session.scalar(select(func.count()).select_from(Story).where(eligible)) or 0
        statement = select(page, EditorialDraft.id.label("draft_id"), EditorialDraft.status.label("editorial_status"),
            EditorialDraft.revision, EditorialDraft.current_version_number, latest).outerjoin(
            EditorialDraft, (EditorialDraft.story_id == page.id) & (EditorialDraft.target_locale == "sr-Latn")
        ).outerjoin(latest, true()).options(links).order_by(
            page.published_at.desc().nulls_last(), page.id.desc())
        rows = session.execute(statement).all()
        now = datetime.now(UTC)
        stories = []
        for row in rows:
            intelligence = build_editorial_story(_intelligence_story(row[0]))
            ai = QueueAIStatus() if row.suggestion_id is None else QueueAIStatus(
                has_suggestion=True, latest_suggestion_id=row.suggestion_id, status=row.ai_status,
                created_at=row.ai_created_at, completed_at=row.ai_completed_at,
                recovery_required=row.ai_status == "processing" and row.ai_expires_at <= now)
            editorial = None if row.draft_id is None else QueueEditorialStatus(draft_id=row.draft_id,
                status=row.editorial_status, revision=row.revision, current_version_number=row.current_version_number)
            stories.append(PrivateEditorialQueueStory(**intelligence.model_dump(), ai=ai, editorial=editorial))
    return PrivateEditorialQueueResponse(stories=stories, stories_total=total, limit=limit, offset=offset,
        has_more=offset + len(stories) < total)
