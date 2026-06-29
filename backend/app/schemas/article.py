from pydantic import BaseModel, Field


class NormalizedArticle(BaseModel):
    external_id: str
    connector: str
    source: str
    source_url: str
    language: str | None = None
    title: str
    url: str
    published_at: str | None = None
    excerpt: str = ""
    content: str | None = None
    featured_image: str | None = None
    categories: list[str] = Field(default_factory=list)
    raw: dict | None = None
