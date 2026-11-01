"""Private editorial records, independent of mutable collection projections.

Migrations additionally enforce append-only history and complete source snapshots
at commit. Collection never writes these tables; private commands own each unit of work.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Computed, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, Timestamps, UUIDPrimaryKey

_STATUSES = "'editing', 'in_review', 'changes_requested', 'approved', 'rejected'"


def _actor_checks():
    return (
        CheckConstraint("btrim(actor_issuer) <> ''", name="actor_issuer_not_blank"),
        CheckConstraint("btrim(actor_subject) <> ''", name="actor_subject_not_blank"),
    )


class _Actor:
    # Command services construct these values exclusively from verified principals.
    actor_issuer: Mapped[str] = mapped_column(Text)
    actor_subject: Mapped[str] = mapped_column(Text)


class EditorialDraft(UUIDPrimaryKey, Timestamps, _Actor, Base):
    __tablename__ = "editorial_drafts"
    __table_args__ = (
        UniqueConstraint("story_id", "target_locale", name="uq_editorial_drafts_story_locale"),
        ForeignKeyConstraint(["id", "current_version_number"],
            ["editorial_draft_versions.draft_id", "editorial_draft_versions.version_number"],
            name="fk_editorial_drafts_current_version", use_alter=True, deferrable=True, initially="DEFERRED"),
        CheckConstraint("target_locale = 'sr-Latn'", name="supported_locale"),
        CheckConstraint(f"status IN ({_STATUSES})", name="valid_status"),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint("current_version_number IS NULL OR current_version_number >= 1", name="valid_current_version"),
        CheckConstraint("status = 'editing' OR current_version_number IS NOT NULL", name="state_requires_version"),
        *_actor_checks(),
        Index("ix_editorial_drafts_status_updated", "status", "updated_at"),
    )

    story_id: Mapped[UUID] = mapped_column(ForeignKey("stories.id", ondelete="RESTRICT"), index=True)
    target_locale: Mapped[str] = mapped_column(String(16), default="sr-Latn", server_default="sr-Latn")
    status: Mapped[str] = mapped_column(String(24), default="editing", server_default="editing")
    current_version_number: Mapped[int | None] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    # ORM updates use WHERE revision = previous_revision. The DB guard also
    # requires exactly one increment for non-ORM writers.
    __mapper_args__ = {"version_id_col": revision}


class EditorialDraftVersion(UUIDPrimaryKey, _Actor, Base):
    __tablename__ = "editorial_draft_versions"
    __table_args__ = (
        UniqueConstraint("draft_id", "version_number", name="uq_editorial_versions_number"),
        UniqueConstraint("draft_id", "version_number", "content_hash", name="uq_editorial_versions_content"),
        CheckConstraint("version_number >= 1", name="positive_version"),
        CheckConstraint("payload_schema_version >= 1", name="positive_schema_version"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        CheckConstraint("source_count >= 1", name="positive_source_count"),
        CheckConstraint("origin IN ('manual', 'imported', 'ai')", name="valid_origin"),
        *_actor_checks(),
    )

    draft_id: Mapped[UUID] = mapped_column(ForeignKey("editorial_drafts.id", ondelete="RESTRICT"))
    version_number: Mapped[int] = mapped_column(Integer)
    payload_schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    payload: Mapped[dict] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64), Computed("hnh_identity_hash(payload::text)"))
    source_count: Mapped[int] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EditorialVersionSource(UUIDPrimaryKey, Base):
    __tablename__ = "editorial_version_sources"
    __table_args__ = (
        ForeignKeyConstraint(["draft_id", "version_number"],
            ["editorial_draft_versions.draft_id", "editorial_draft_versions.version_number"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["article_id", "source_id"],
            ["collected_articles.id", "collected_articles.source_id"], ondelete="RESTRICT"),
        UniqueConstraint("draft_id", "version_number", "article_id", name="uq_editorial_version_sources_article"),
        CheckConstraint("version_number >= 1", name="positive_version"),
        CheckConstraint("btrim(source_name) <> '' AND btrim(source_url) <> ''", name="source_identity_not_blank"),
        CheckConstraint("btrim(original_url) <> ''", name="original_url_not_blank"),
        CheckConstraint("canonical_url IS NULL OR btrim(canonical_url) <> ''", name="canonical_url_not_blank"),
        CheckConstraint("external_id IS NULL OR btrim(external_id) <> ''", name="external_id_not_blank"),
        CheckConstraint("btrim(input_text) <> ''", name="input_text_not_blank"),
        Index("ix_editorial_version_sources_article", "article_id"),
        Index("ix_editorial_version_sources_source", "source_id"),
    )

    draft_id: Mapped[UUID] = mapped_column()
    version_number: Mapped[int] = mapped_column(Integer)
    source_id: Mapped[UUID] = mapped_column()
    article_id: Mapped[UUID] = mapped_column()
    source_name: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)
    original_url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_text: Mapped[str] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    snapshot_hash: Mapped[str] = mapped_column(String(64), Computed(
        "public.hnh_editorial_snapshot_hash(source_id, article_id, source_name, source_url, external_id, "
        "original_url, canonical_url, published_at, input_text, captured_at)"))


class EditorialDecision(UUIDPrimaryKey, _Actor, Base):
    __tablename__ = "editorial_decisions"
    __table_args__ = (
        ForeignKeyConstraint(["draft_id", "version_number", "content_hash"],
            ["editorial_draft_versions.draft_id", "editorial_draft_versions.version_number", "editorial_draft_versions.content_hash"],
            ondelete="RESTRICT"),
        CheckConstraint("decision IN ('approve', 'reject', 'request_changes')", name="valid_decision"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_format"),
        CheckConstraint("reason IS NULL OR btrim(reason) <> ''", name="reason_not_blank"),
        CheckConstraint("decision = 'approve' OR reason IS NOT NULL", name="negative_decision_requires_reason"),
        *_actor_checks(),
        Index("ix_editorial_decisions_version", "draft_id", "version_number", "decided_at"),
    )

    draft_id: Mapped[UUID] = mapped_column()
    version_number: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EditorialEvent(UUIDPrimaryKey, _Actor, Base):
    __tablename__ = "editorial_events"
    __table_args__ = (
        ForeignKeyConstraint(["draft_id", "version_number"],
            ["editorial_draft_versions.draft_id", "editorial_draft_versions.version_number"], ondelete="RESTRICT"),
        UniqueConstraint("draft_id", "command_id", name="uq_editorial_events_command"),
        CheckConstraint("version_number IS NULL OR version_number >= 1", name="valid_version"),
        CheckConstraint("event_type ~ '^[a-z][a-z0-9_.]*$'", name="valid_event_type"),
        CheckConstraint(f"from_status IS NULL OR from_status IN ({_STATUSES})", name="valid_from_status"),
        CheckConstraint(f"to_status IS NULL OR to_status IN ({_STATUSES})", name="valid_to_status"),
        CheckConstraint("jsonb_typeof(details) = 'object'", name="details_object"),
        CheckConstraint("(command_id IS NULL AND request_hash IS NULL) OR "
                        "(command_id IS NOT NULL AND request_hash IS NOT NULL AND request_hash ~ '^[0-9a-f]{64}$')", name="command_hash_pair"),
        *_actor_checks(),
        Index("ix_editorial_events_history", "draft_id", "occurred_at", "id"),
    )

    draft_id: Mapped[UUID] = mapped_column(ForeignKey("editorial_drafts.id", ondelete="RESTRICT"))
    version_number: Mapped[int | None] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64))
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str | None] = mapped_column(String(24))
    command_id: Mapped[UUID | None] = mapped_column()
    request_hash: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
