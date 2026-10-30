from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, Timestamps, UUIDPrimaryKey
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


class Story(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "stories"
    __table_args__ = (
        CheckConstraint("btrim(headline) <> ''", name="headline_not_blank"),
        CheckConstraint("similarity_score BETWEEN 0 AND 100", name="valid_similarity"),
        CheckConstraint("status IN ('collected', 'merged', 'translated', 'draft', 'review', 'published')", name="valid_status"),
    )

    headline: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="collected", server_default="collected", index=True)
    similarity_score: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    language: Mapped[str | None] = mapped_column(String(16))
    categories: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=text("'{}'::text[]"))

    article_links: Mapped[list["StoryArticle"]] = relationship(
        back_populates="story", cascade="all, delete-orphan", passive_deletes=True,
    )


class StoryArticle(Timestamps, Base):
    __tablename__ = "story_articles"
    __table_args__ = (
        UniqueConstraint("article_id", name="uq_story_articles_article_id"),
        CheckConstraint("match_score IS NULL OR match_score BETWEEN 0 AND 100", name="valid_match_score"),
        Index("uq_story_articles_primary", "story_id", unique=True, postgresql_where=text("is_primary")),
    )

    story_id: Mapped[UUID] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True)
    article_id: Mapped[UUID] = mapped_column(ForeignKey("collected_articles.id", ondelete="RESTRICT"), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    match_score: Mapped[int | None] = mapped_column(SmallInteger)

    story: Mapped[Story] = relationship(back_populates="article_links")
    article: Mapped["CollectedArticle"] = relationship(back_populates="story_links")
