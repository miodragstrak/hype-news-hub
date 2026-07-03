from pydantic import BaseModel, Field

from app.schemas.article import NormalizedArticle
from app.schemas.story import StorySummary


class CollectArticlesResponse(BaseModel):
    sources_processed: int
    sources_failed: int
    articles_total: int
    articles: list[NormalizedArticle] = Field(default_factory=list)
    story_candidates_total: int = 0
    stories_total: int = 0
    stories: list[StorySummary] = Field(default_factory=list)
