from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, UUIDPrimaryKey


class CollectionRun(UUIDPrimaryKey, Base):
    __tablename__ = "collection_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'partial', 'failed')", name="valid_status"),
        CheckConstraint("limit_per_source BETWEEN 1 AND 50", name="valid_limit"),
        CheckConstraint("sources_processed >= 0 AND sources_failed >= 0 AND sources_failed <= sources_processed", name="valid_source_counts"),
        CheckConstraint("articles_total >= 0 AND stories_total >= 0 AND story_candidates_total >= 0", name="nonnegative_counts"),
        CheckConstraint("finished_at IS NULL OR finished_at >= started_at", name="valid_finish_time"),
        CheckConstraint("(status = 'running' AND finished_at IS NULL) OR (status <> 'running' AND finished_at IS NOT NULL)", name="status_finish_time"),
    )

    status: Mapped[str] = mapped_column(String(16), default="running", server_default="running", index=True)
    limit_per_source: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sources_processed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sources_failed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    articles_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stories_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    story_candidates_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)

    source_results: Mapped[list["CollectionSourceResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True,
    )


class CollectionSourceResult(UUIDPrimaryKey, Base):
    __tablename__ = "collection_source_results"
    __table_args__ = (
        UniqueConstraint("run_id", "source_id", name="uq_collection_source_results_run_source"),
        CheckConstraint("status IN ('pending', 'running', 'success', 'failed')", name="valid_status"),
        CheckConstraint("articles_total >= 0", name="nonnegative_article_count"),
        CheckConstraint("finished_at IS NULL OR (started_at IS NOT NULL AND finished_at >= started_at)", name="valid_finish_time"),
        CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND finished_at IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL) OR "
            "(status IN ('success', 'failed') AND started_at IS NOT NULL AND finished_at IS NOT NULL)",
            name="status_timestamps",
        ),
    )

    run_id: Mapped[UUID] = mapped_column(ForeignKey("collection_runs.id", ondelete="CASCADE"))
    source_id: Mapped[UUID] = mapped_column(ForeignKey("news_sources.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    articles_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)

    run: Mapped[CollectionRun] = relationship(back_populates="source_results")
    source: Mapped["NewsSource"] = relationship()
