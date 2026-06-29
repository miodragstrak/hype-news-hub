from pydantic import BaseModel, Field

from app.schemas.article import NormalizedArticle


class CollectArticlesResponse(BaseModel):
    sources_processed: int
    sources_failed: int
    articles_total: int
    articles: list[NormalizedArticle] = Field(default_factory=list)
