"""Single-source requests embed immutable evidence; events retain command recovery."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Computed, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, UUIDPrimaryKey

STATUSES = "'processing', 'succeeded', 'failed', 'interrupted', 'rejected', 'accepted'"


class AIProcessingRun(UUIDPrimaryKey, Base):
    __tablename__ = "ai_processing_runs"
    __table_args__ = (
        ForeignKeyConstraint(["article_id", "source_id"], ["collected_articles.id", "collected_articles.source_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["accepted_draft_id", "accepted_version_number", "accepted_content_hash"],
            ["editorial_draft_versions.draft_id", "editorial_draft_versions.version_number", "editorial_draft_versions.content_hash"],
            name="fk_ai_processing_runs_accepted_version", ondelete="RESTRICT"),
        UniqueConstraint("command_id", name="uq_ai_processing_runs_command"),
        CheckConstraint(f"status IN ({STATUSES})", name="valid_status"),
        CheckConstraint("revision BETWEEN 1 AND 3", name="valid_revision"),
        CheckConstraint("target_locale = 'sr-Latn' AND mode = 'translation'", name="supported_processing"),
        CheckConstraint("btrim(actor_issuer) <> '' AND btrim(actor_subject) <> ''", name="actor_not_blank"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="request_hash_format"),
        CheckConstraint("jsonb_typeof(input_payload) = 'object' AND octet_length(input_payload::text) <= 262144", name="bounded_input"),
        CheckConstraint("coalesce((input_payload->>'request_id' = id::text AND input_payload->>'story_id' = story_id::text "
            "AND input_payload->'source'->>'article_id' = article_id::text AND input_payload->'source'->>'source_id' = source_id::text "
            "AND input_payload->>'mode' = mode AND input_payload->>'target_locale' = target_locale "
            "AND coalesce(octet_length(input_payload->'source'->>'input_text'), 0) BETWEEN 1 AND 65536 "
            "AND input_payload->'source'->>'input_text_hash' = public.hnh_identity_hash(input_payload->'source'->>'input_text')), false)", name="input_identity"),
        CheckConstraint("jsonb_typeof(provenance) = 'object'", name="provenance_object"),
        CheckConstraint("output IS NULL OR (jsonb_typeof(output) = 'object' AND octet_length(output::text) <= 65536)", name="bounded_output"),
        CheckConstraint("expires_at > created_at AND (completed_at IS NULL OR completed_at >= created_at) "
            "AND (rejected_at IS NULL OR rejected_at >= completed_at) "
            "AND (accepted_at IS NULL OR accepted_at >= completed_at)", name="valid_timestamps"),
        CheckConstraint("(status = 'processing' AND revision = 1 AND output IS NULL AND error_code IS NULL AND completed_at IS NULL AND rejected_at IS NULL) OR "
            "(status = 'succeeded' AND revision = 2 AND output IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL AND rejected_at IS NULL) OR "
            "(status IN ('failed', 'interrupted') AND revision = 2 AND output IS NULL AND error_code IN "
            "('provider_timeout','provider_failure','invalid_provider_output','process_interrupted','provider_auth','provider_throttled',"
            "'provider_unavailable','provider_invalid_model','provider_invalid_request','provider_refused','provider_incomplete',"
            "'insufficient_evidence','input_token_limit','provider_uncertain','provider_response_too_large') "
            "AND error_code IS NOT NULL AND completed_at IS NOT NULL AND rejected_at IS NULL) OR "
            "(status = 'rejected' AND revision = 3 AND output IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL AND rejected_at IS NOT NULL) OR "
            "(status = 'accepted' AND revision = 3 AND output IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL AND rejected_at IS NULL)", name="state_payload"),
        CheckConstraint("(status = 'accepted' AND accepted_at IS NOT NULL AND accepted_draft_id IS NOT NULL "
            "AND accepted_version_number >= 1 AND accepted_version_number IS NOT NULL "
            "AND accepted_content_hash ~ '^[0-9a-f]{64}$' AND accepted_content_hash IS NOT NULL) OR "
            "(status <> 'accepted' AND accepted_at IS NULL AND accepted_draft_id IS NULL "
            "AND accepted_version_number IS NULL AND accepted_content_hash IS NULL)", name="acceptance_reference"),
        CheckConstraint("(status <> 'processing' OR processing_metadata IS NULL) AND (processing_metadata IS NULL OR "
            "(jsonb_typeof(processing_metadata) = 'object' AND octet_length(processing_metadata::text) <= 16384))", name="bounded_processing_metadata"),
        Index("ix_ai_processing_runs_story_created", "story_id", "created_at", "id"),
    )
    story_id: Mapped[UUID] = mapped_column(ForeignKey("stories.id", ondelete="RESTRICT"))
    article_id: Mapped[UUID] = mapped_column()
    source_id: Mapped[UUID] = mapped_column()
    command_id: Mapped[UUID] = mapped_column()
    actor_issuer: Mapped[str] = mapped_column(Text)
    actor_subject: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(String(64))
    target_locale: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer)
    input_payload: Mapped[dict] = mapped_column(JSONB)
    input_hash: Mapped[str] = mapped_column(String(64), Computed("public.hnh_identity_hash(input_payload::text)"))
    provenance: Mapped[dict] = mapped_column(JSONB)
    output: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    output_hash: Mapped[str | None] = mapped_column(String(64), Computed("public.hnh_identity_hash(output::text)"))
    error_code: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_draft_id: Mapped[UUID | None] = mapped_column()
    accepted_version_number: Mapped[int | None] = mapped_column(Integer)
    accepted_content_hash: Mapped[str | None] = mapped_column(String(64))
    processing_metadata: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))


class AIProcessingEvent(UUIDPrimaryKey, Base):
    __tablename__ = "ai_processing_events"
    __table_args__ = (
        UniqueConstraint("run_id", "revision", name="uq_ai_processing_events_revision"),
        UniqueConstraint("command_id", name="uq_ai_processing_events_command"),
        CheckConstraint("revision BETWEEN 1 AND 3", name="valid_revision"),
        CheckConstraint(f"status IN ({STATUSES})", name="valid_status"),
        CheckConstraint("action IN ('generation.requested','generation.succeeded','generation.failed','generation.interrupted','suggestion.rejected','suggestion.accepted')", name="valid_action"),
        CheckConstraint("btrim(actor_issuer) <> '' AND btrim(actor_subject) <> ''", name="actor_not_blank"),
        CheckConstraint("(command_id IS NULL AND request_hash IS NULL) OR (command_id IS NOT NULL AND request_hash ~ '^[0-9a-f]{64}$' AND request_hash IS NOT NULL)", name="command_hash_pair"),
        CheckConstraint("reason IS NULL OR (btrim(reason) <> '' AND char_length(reason) <= 2000)", name="bounded_reason"),
        CheckConstraint("(revision = 1 AND action = 'generation.requested' AND status = 'processing' AND command_id IS NOT NULL AND reason IS NULL) OR "
            "(revision = 2 AND action = 'generation.' || status AND status IN ('succeeded','failed','interrupted') AND command_id IS NULL AND reason IS NULL) OR "
            "(revision = 3 AND action = 'suggestion.rejected' AND status = 'rejected' AND command_id IS NOT NULL AND reason IS NOT NULL) OR "
            "(revision = 3 AND action = 'suggestion.accepted' AND status = 'accepted' AND command_id IS NOT NULL AND reason IS NULL)", name="event_shape"),
        CheckConstraint("(action = 'suggestion.accepted' AND result IS NOT NULL AND jsonb_typeof(result) = 'object' "
            "AND octet_length(result::text) <= 4096) OR (action <> 'suggestion.accepted' AND result IS NULL)", name="bounded_result"),
    )
    run_id: Mapped[UUID] = mapped_column(ForeignKey("ai_processing_runs.id", ondelete="RESTRICT"))
    revision: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16))
    command_id: Mapped[UUID | None] = mapped_column()
    request_hash: Mapped[str | None] = mapped_column(String(64))
    actor_issuer: Mapped[str] = mapped_column(Text)
    actor_subject: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    result: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
