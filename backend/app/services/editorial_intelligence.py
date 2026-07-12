from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.editorial import EditorialIntelligence, EditorialQueueResponse, EditorialQueueStory
from app.schemas.story import Story
from app.services.story_service import get_latest_stories

_CATEGORY_WEIGHTS: dict[str, int] = {
    "politics": 90,
    "economy": 85,
    "crime": 80,
    "world": 78,
    "society": 72,
    "culture": 64,
    "entertainment": 60,
    "sport": 68,
    "sports": 68,
    "technology": 74,
}


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def source_country_code(source: str) -> str:
    lowered = source.lower()
    if "serbia" in lowered:
        return "RS"
    if "croatia" in lowered:
        return "HR"
    if "bosnia" in lowered or "bih" in lowered:
        return "BA"
    if "slovenia" in lowered:
        return "SI"
    if "macedonia" in lowered:
        return "MK"
    return "RS"


def _coverage_for_story(story: Story) -> str:
    country_codes = {source_country_code(source) for source in story.sources}

    if len(country_codes) >= 4:
        return "International"
    if len(country_codes) >= 2:
        return "Regional"
    return "Local"


def _freshness_score(published_at: str | None) -> int:
    published_dt = _parse_timestamp(published_at)
    if published_dt is None:
        return 35

    elapsed_hours = max(0.0, (datetime.now(timezone.utc) - published_dt).total_seconds() / 3600)

    if elapsed_hours <= 1:
        return 100
    if elapsed_hours <= 3:
        return 92
    if elapsed_hours <= 6:
        return 80
    if elapsed_hours <= 12:
        return 68
    if elapsed_hours <= 24:
        return 56
    if elapsed_hours <= 48:
        return 42
    return 25


def _category_weight(categories: list[str]) -> int:
    if not categories:
        return 50

    weighted = [_CATEGORY_WEIGHTS.get(category.strip().lower(), 52) for category in categories if category.strip()]
    if not weighted:
        return 50

    return max(weighted)


def _importance_score(story: Story, freshness: int, coverage: str) -> int:
    source_factor = min(100, (len(story.sources) * 22) + (len(story.articles) - len(story.sources)) * 6)
    category_factor = _category_weight(story.categories)
    coverage_factor = {"Local": 45, "Regional": 75, "International": 90}[coverage]

    raw_score = (source_factor * 0.35) + (freshness * 0.25) + (category_factor * 0.2) + (coverage_factor * 0.2)
    return max(0, min(100, round(raw_score)))


def _confidence_score(story: Story) -> int:
    source_reliability = min(100, len(story.sources) * 25)
    depth_factor = min(100, len(story.articles) * 16)

    raw_score = (source_reliability * 0.4) + (story.similarity_score * 0.4) + (depth_factor * 0.2)
    return max(0, min(100, round(raw_score)))


def _trend(story: Story, freshness: int) -> str:
    if freshness >= 75 and len(story.sources) >= 2:
        return "Rising"
    if freshness >= 50:
        return "Stable"
    return "Declining"


def _risk_level(story: Story, confidence: int, trend: str) -> str:
    if len(story.sources) <= 1:
        return "High"
    if confidence < 60 or trend == "Declining":
        return "Medium"
    return "Low"


def _recommended_action(importance: int, confidence: int, risk: str) -> str:
    if importance >= 80 and confidence >= 70 and risk != "High":
        return "Publish Immediately"
    if importance >= 60 and confidence >= 55 and risk != "High":
        return "Review Soon"
    if risk == "High" or confidence < 55:
        return "Manual Review"
    return "Ignore"


def _reason_text(story: Story, coverage: str, freshness: int) -> str:
    source_count = len(story.sources)
    return f"Covered by {source_count} {coverage.lower()} sources with freshness score {freshness}."


def build_editorial_intelligence(story: Story) -> EditorialIntelligence:
    coverage = _coverage_for_story(story)
    freshness = _freshness_score(story.published_at)
    importance = _importance_score(story, freshness, coverage)
    confidence = _confidence_score(story)
    trend = _trend(story, freshness)
    risk = _risk_level(story, confidence, trend)
    action = _recommended_action(importance, confidence, risk)

    return EditorialIntelligence(
        importance_score=importance,
        confidence_score=confidence,
        coverage=coverage,
        risk_level=risk,
        recommended_action=action,
        reason=_reason_text(story, coverage, freshness),
    )


def build_editorial_story(story: Story) -> EditorialQueueStory:
    intelligence = build_editorial_intelligence(story)
    freshness = _freshness_score(story.published_at)
    trend = _trend(story, freshness)

    return EditorialQueueStory(
        id=story.id,
        headline=story.headline,
        status=story.status,
        sources=story.sources,
        source_count=len(story.sources),
        article_count=len(story.articles),
        similarity_score=story.similarity_score,
        published_at=story.published_at,
        categories=story.categories,
        language=story.language,
        importance_score=intelligence.importance_score,
        confidence_score=intelligence.confidence_score,
        coverage=intelligence.coverage,
        trend=trend,
        freshness=freshness,
        risk_level=intelligence.risk_level,
        recommended_action=intelligence.recommended_action,
        reason=intelligence.reason,
    )


def get_editorial_queue_response() -> EditorialQueueResponse:
    editorial_stories = [build_editorial_story(story) for story in get_latest_stories()]
    sorted_stories = sorted(
        editorial_stories,
        key=lambda story: (story.importance_score, story.confidence_score, story.published_at or ""),
        reverse=True,
    )

    return EditorialQueueResponse(stories_total=len(sorted_stories), stories=sorted_stories)
