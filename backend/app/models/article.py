from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, Timestamps, UUIDPrimaryKey


class CollectedArticle(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "collected_articles"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_collected_articles_source_external_id"),
        UniqueConstraint("source_id", "url", name="uq_collected_articles_source_url"),
        UniqueConstraint("source_id", "canonical_url", name="uq_collected_articles_source_canonical_url"),
        CheckConstraint("external_id IS NULL OR btrim(external_id) <> ''", name="external_id_not_blank"),
        CheckConstraint("btrim(title) <> ''", name="title_not_blank"),
        CheckConstraint("btrim(url) <> ''", name="url_not_blank"),
        CheckConstraint("canonical_url IS NULL OR btrim(canonical_url) <> ''", name="canonical_url_not_blank"),
        CheckConstraint("content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_format"),
        Index("ix_collected_articles_source_published", "source_id", "published_at"),
    )

    source_id: Mapped[UUID] = mapped_column(ForeignKey("news_sources.id", ondelete="RESTRICT"))
    first_seen_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("collection_runs.id", ondelete="SET NULL"), index=True)
    external_id: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[str] = mapped_column(Text, default="", server_default="")
    content: Mapped[str | None] = mapped_column(Text)
    featured_image: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    categories: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=text("'{}'::text[]"))
    raw: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    source: Mapped["NewsSource"] = relationship(back_populates="articles")
    story_links: Mapped[list["StoryArticle"]] = relationship(back_populates="article", passive_deletes="all")
