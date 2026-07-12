from __future__ import annotations

from app.schemas.editorial import (
    EditorialStoryWorkspace,
    ProcessingStep,
    SerbianDraft,
    SourceArticle,
)
from app.schemas.story import Story
from app.services.editorial_intelligence import build_editorial_intelligence, source_country_code
from app.services.story_service import get_story_by_id

_processing_labels = [
    ("collected", "Collected"),
    ("normalized", "Normalized"),
    ("sources_merged", "Sources Merged"),
    ("editorially_scored", "Editorially Scored"),
    ("serbian_draft", "Serbian Draft"),
    ("human_review", "Human Review"),
    ("publishing", "Publishing"),
]

_editorial_story_overrides: dict[str, dict[str, object]] = {}


def _source_article(article) -> SourceArticle:
    return SourceArticle(
        external_id=article.external_id,
        source=article.source,
        source_url=article.source_url,
        country=source_country_code(article.source),
        language=article.language,
        title=article.title,
        excerpt=article.excerpt,
        content=article.content,
        featured_image=article.featured_image,
        published_at=article.published_at,
        url=article.url,
        categories=article.categories,
    )


def _processing_history(status: str, draft_status: str) -> list[ProcessingStep]:
    current_key = "serbian_draft" if draft_status == "not_generated" else "human_review"
    if status in {"approved", "ready_for_publishing"}:
        current_key = "publishing"
    if status == "published":
        current_key = "publishing"

    current_index = next((index for index, (key, _) in enumerate(_processing_labels) if key == current_key), len(_processing_labels) - 1)

    steps: list[ProcessingStep] = []
    for index, (key, label) in enumerate(_processing_labels):
        if index < current_index:
            state = "completed"
        elif index == current_index:
            state = "current"
        else:
            state = "future"

        if status == "published":
            state = "completed"

        steps.append(ProcessingStep(key=key, label=label, state=state))

    return steps


def _workspace_from_story(story: Story) -> EditorialStoryWorkspace:
    override = _editorial_story_overrides.get(story.id, {})
    draft_data = override.get("serbian_draft")
    status = override.get("status", "needs_generation")
    draft = SerbianDraft.model_validate(draft_data) if draft_data else SerbianDraft()
    source_articles = [_source_article(article) for article in story.articles]
    source_languages = sorted({article.language for article in story.articles if article.language})
    source_countries = sorted({source_country_code(article.source) for article in story.articles})

    return EditorialStoryWorkspace(
        id=story.id,
        story_id=story.id,
        headline=story.headline,
        status=status,
        source_articles=source_articles,
        source_count=len(source_articles),
        source_languages=source_languages,
        source_countries=source_countries,
        editorial_intelligence=build_editorial_intelligence(story),
        serbian_draft=draft,
        processing_history=_processing_history(status=status, draft_status=draft.status),
    )


def get_editorial_story_workspace(story_id: str) -> EditorialStoryWorkspace | None:
    story = get_story_by_id(story_id)
    if story is None:
        return None

    return _workspace_from_story(story)


def generate_demo_serbian_draft(story_id: str) -> EditorialStoryWorkspace | None:
    story = get_story_by_id(story_id)
    if story is None:
        return None

    primary_article = story.primary_article
    _editorial_story_overrides[story_id] = {
        "status": "draft_ready",
        "serbian_draft": {
            "headline": story.headline,
            "excerpt": primary_article.excerpt or story.headline,
            "content": (
                "Demo Draft\n\n"
                "This is a deterministic placeholder for the future unified Serbian editorial story. "
                "It is not AI-generated and it is not a real translation. "
                "The final Serbian article will later be prepared from all verified regional sources listed in this workspace."
            ),
            "status": "demo_generated",
        },
    }

    return _workspace_from_story(story)
