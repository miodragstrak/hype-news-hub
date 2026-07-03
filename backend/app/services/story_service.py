from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from uuid import uuid4

from app.core.config import settings
from app.schemas.article import NormalizedArticle
from app.schemas.story import StoriesResponse, Story, StorySummary
from app.services.story_matcher import similarity_score

_DEFAULT_MERGE_THRESHOLD = max(0, min(100, settings.story_merge_threshold))
_latest_stories: list[Story] = []


@dataclass(frozen=True)
class StoryBuildResult:
    stories: list[Story]
    story_candidates_total: int


def _sort_stories(stories: Iterable[Story]) -> list[Story]:
    return sorted(stories, key=lambda story: story.published_at or "", reverse=True)


def _merge_into_story(story: Story, article: NormalizedArticle, match_score: int) -> Story:
    merged_articles = [*story.articles, article]
    merged_sources = sorted({*story.sources, article.source})
    merged_categories = sorted({*story.categories, *article.categories})

    # Keep the strongest pairwise score observed in this story.
    merged_score = max(story.similarity_score, match_score)

    return story.model_copy(
        update={
            "articles": merged_articles,
            "sources": merged_sources,
            "categories": merged_categories,
            "similarity_score": merged_score,
            "status": "merged",
        }
    )


def _story_summary(story: Story) -> StorySummary:
    return StorySummary(
        id=story.id,
        headline=story.headline,
        sources=story.sources,
        article_count=len(story.articles),
        similarity_score=story.similarity_score,
        status="review" if len(story.articles) > 1 else story.status,
        published_at=story.published_at,
    )


def build_stories_from_articles(
    articles: list[NormalizedArticle],
    merge_threshold: int = _DEFAULT_MERGE_THRESHOLD,
) -> StoryBuildResult:
    if not articles:
        return StoryBuildResult(stories=[], story_candidates_total=0)

    stories: list[Story] = []
    merged_candidates = 0

    for article in articles:
        best_match_index: int | None = None
        best_match_score = -1

        for index, story in enumerate(stories):
            score = similarity_score(article, story.primary_article)
            if score > best_match_score:
                best_match_index = index
                best_match_score = score

        if best_match_index is not None and best_match_score >= merge_threshold:
            merged_candidates += 1
            stories[best_match_index] = _merge_into_story(stories[best_match_index], article, best_match_score)
            continue

        stories.append(
            Story(
                id=f"story-{uuid4().hex[:10]}",
                headline=article.title,
                primary_article=article,
                articles=[article],
                sources=[article.source],
                published_at=article.published_at,
                categories=sorted({*article.categories}),
                similarity_score=100,
                status="collected",
                language=article.language,
            )
        )

    return StoryBuildResult(stories=_sort_stories(stories), story_candidates_total=merged_candidates)


def set_latest_stories(stories: list[Story]) -> None:
    global _latest_stories
    _latest_stories = _sort_stories(stories)


def get_latest_stories() -> list[Story]:
    return _sort_stories(_latest_stories)


def get_stories_response() -> StoriesResponse:
    story_summaries = [_story_summary(story) for story in get_latest_stories()]
    return StoriesResponse(stories_total=len(story_summaries), stories=story_summaries)
