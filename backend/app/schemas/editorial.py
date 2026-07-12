from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.story import StoryStatus

Coverage = Literal["Local", "Regional", "International"]
Trend = Literal["Rising", "Stable", "Declining"]
RiskLevel = Literal["Low", "Medium", "High"]
RecommendedAction = Literal["Publish Immediately", "Review Soon", "Manual Review", "Ignore"]
EditorialStoryStatus = Literal[
    "needs_generation",
    "draft_ready",
    "in_review",
    "approved",
    "rejected",
    "ready_for_publishing",
    "published",
]
SerbianDraftStatus = Literal["not_generated", "demo_generated", "ready", "approved"]


class EditorialIntelligence(BaseModel):
    importance_score: int = Field(default=0, ge=0, le=100)
    confidence_score: int = Field(default=0, ge=0, le=100)
    coverage: Coverage
    risk_level: RiskLevel
    recommended_action: RecommendedAction
    reason: str


class SourceArticle(BaseModel):
    external_id: str
    source: str
    source_url: str
    country: str
    language: str | None = None
    title: str
    excerpt: str = ""
    content: str | None = None
    featured_image: str | None = None
    published_at: str | None = None
    url: str
    categories: list[str] = Field(default_factory=list)


class SerbianDraft(BaseModel):
    headline: str | None = None
    excerpt: str | None = None
    content: str | None = None
    status: SerbianDraftStatus = "not_generated"


class ProcessingStep(BaseModel):
    key: str
    label: str
    state: Literal["completed", "current", "future"]


class EditorialStoryWorkspace(BaseModel):
    id: str
    story_id: str
    headline: str
    target_language: Literal["sr"] = "sr"
    target_language_label: str = "Serbian"
    status: EditorialStoryStatus = "needs_generation"
    source_articles: list[SourceArticle] = Field(default_factory=list)
    source_count: int = Field(default=0, ge=0)
    source_languages: list[str] = Field(default_factory=list)
    source_countries: list[str] = Field(default_factory=list)
    editorial_intelligence: EditorialIntelligence
    serbian_draft: SerbianDraft = Field(default_factory=SerbianDraft)
    processing_history: list[ProcessingStep] = Field(default_factory=list)


class EditorialQueueStory(BaseModel):
    id: str
    headline: str
    status: StoryStatus
    sources: list[str] = Field(default_factory=list)
    source_count: int = Field(default=0, ge=0)
    article_count: int = Field(default=0, ge=0)
    similarity_score: int = Field(default=0, ge=0, le=100)
    published_at: str | None = None
    categories: list[str] = Field(default_factory=list)
    language: str | None = None

    importance_score: int = Field(default=0, ge=0, le=100)
    confidence_score: int = Field(default=0, ge=0, le=100)
    coverage: Coverage
    trend: Trend
    freshness: int = Field(default=0, ge=0, le=100)
    risk_level: RiskLevel
    recommended_action: RecommendedAction
    reason: str


class EditorialQueueResponse(BaseModel):
    stories_total: int = Field(default=0, ge=0)
    stories: list[EditorialQueueStory] = Field(default_factory=list)
