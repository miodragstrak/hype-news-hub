from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.article import NormalizedArticle
from app.schemas.story import StorySummary


class CollectionSourceResult(BaseModel):
    name: str
    url: str
    status: Literal["success", "failed"]
    articles_total: int = Field(default=0, ge=0)
    error: str | None = None


class CollectArticlesResponse(BaseModel):
    sources_processed: int
    sources_failed: int
    articles_total: int
    articles: list[NormalizedArticle] = Field(default_factory=list)
    story_candidates_total: int = 0
    stories_total: int = 0
    stories: list[StorySummary] = Field(default_factory=list)
    source_results: list[CollectionSourceResult] = Field(default_factory=list)
