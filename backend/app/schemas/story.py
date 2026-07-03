from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.article import NormalizedArticle

StoryStatus = Literal["collected", "merged", "translated", "draft", "review", "published"]


class Story(BaseModel):
    id: str
    headline: str
    primary_article: NormalizedArticle
    articles: list[NormalizedArticle] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    published_at: str | None = None
    categories: list[str] = Field(default_factory=list)
    similarity_score: int = Field(default=0, ge=0, le=100)
    status: StoryStatus = "collected"
    language: str | None = None


class StorySummary(BaseModel):
    id: str
    headline: str
    sources: list[str] = Field(default_factory=list)
    article_count: int = Field(default=0, ge=0)
    similarity_score: int = Field(default=0, ge=0, le=100)
    status: StoryStatus = "collected"
    published_at: str | None = None


class StoriesResponse(BaseModel):
    stories_total: int = Field(default=0, ge=0)
    stories: list[StorySummary] = Field(default_factory=list)
