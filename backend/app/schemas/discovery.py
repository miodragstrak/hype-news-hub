from typing import Literal

from pydantic import BaseModel, Field


class DiscoveredArticle(BaseModel):
    title: str | None = None
    date: str | None = None
    image: str | None = None
    url: str | None = None
    categories: list[str] = Field(default_factory=list)


class DiscoveryResult(BaseModel):
    name: str
    url: str
    wordpress: bool
    rss: bool
    preferred: Literal["wordpress", "rss", "html_scraping"]
    posts_endpoint: str | None = None
    rss_endpoint: str | None = None
    sample_article: DiscoveredArticle | None = None
