from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.article import NormalizedArticle


@dataclass(slots=True)
class StoryEntity:
    id: str
    headline: str
    primary_article: NormalizedArticle
    articles: list[NormalizedArticle] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    published_at: str | None = None
    categories: list[str] = field(default_factory=list)
    similarity_score: int = 0
    status: str = "collected"
    language: str | None = None
