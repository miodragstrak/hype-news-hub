from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.story import StoryStatus

Coverage = Literal["Local", "Regional", "International"]
Trend = Literal["Rising", "Stable", "Declining"]
RiskLevel = Literal["Low", "Medium", "High"]
RecommendedAction = Literal["Publish Immediately", "Review Soon", "Manual Review", "Ignore"]


class EditorialStory(BaseModel):
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
    stories: list[EditorialStory] = Field(default_factory=list)
