"""Private editorial API v1: complete plain-text payloads and UUID references."""
from datetime import datetime
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, AfterValidator, model_validator

from app.core.content_safety import safe_content_url


def plain_latin(value: str) -> str:
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff]|<[!?/a-zA-Z]", value):
        raise ValueError("Use plain text without HTML or control characters.")
    if re.search(r"[\u0400-\u052f]", value):
        raise ValueError("Editorial text must use Latin script.")
    return value


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1), AfterValidator(plain_latin)]
Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceAttribution(StrictModel):
    article_id: UUID
    source_id: UUID


class ImageReference(StrictModel):
    url: str = Field(min_length=1, max_length=2048)
    alt: Text = Field(max_length=300)
    credit: Text = Field(max_length=300)
    source_article_id: UUID

    @model_validator(mode="after")
    def safe_url(self):
        if safe_content_url(self.url) != self.url:
            raise ValueError("Images require an absolute public HTTP(S) URL without credentials.")
        return self


class SEOMetadata(StrictModel):
    title: Text = Field(max_length=120)
    description: Text = Field(max_length=320)


class PublishingPayload(StrictModel):
    headline: Text = Field(max_length=300)
    body: Text = Field(max_length=100_000)
    excerpt: Text = Field(max_length=1000)
    slug: str = Field(min_length=1, max_length=200, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    categories: list[Annotated[Text, Field(max_length=100)]] = Field(min_length=1, max_length=20)
    tags: list[Annotated[Text, Field(max_length=100)]] = Field(max_length=50)
    seo: SEOMetadata
    images: list[ImageReference] = Field(max_length=10)
    source_attribution: list[SourceAttribution] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def consistent_references(self):
        ids = [source.article_id for source in self.source_attribution]
        if len(ids) != len(set(ids)):
            raise ValueError("Source articles must be unique UUIDs.")
        for values in (self.categories, self.tags):
            if len(values) != len({item.casefold() for item in values}):
                raise ValueError("Categories and tags must not contain duplicates.")
        if any(image.source_article_id not in ids for image in self.images):
            raise ValueError("Image attribution must reference a selected source article.")
        return self


class CreateDraft(StrictModel):
    command_id: UUID
    expected_revision: int = Field(ge=0, le=0, strict=True)
    story_id: UUID
    target_locale: Literal["sr-Latn"]
    payload: PublishingPayload


class RevisionCommand(StrictModel):
    command_id: UUID
    expected_revision: int = Field(ge=1, strict=True)


class SaveRevision(RevisionCommand):
    payload: PublishingPayload


class VersionCommand(RevisionCommand):
    version_number: int = Field(ge=1, strict=True)
    content_hash: Hash


class DecisionCommand(VersionCommand):
    reason: Text | None = Field(default=None, max_length=2000)


class NegativeDecisionCommand(VersionCommand):
    reason: Text = Field(max_length=2000)


class CommandResult(StrictModel):
    command_id: UUID
    draft_id: UUID
    revision: int
    status: str
    version_number: int
    content_hash: Hash


class SourceSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source_id: UUID
    article_id: UUID
    source_name: str
    source_url: str
    external_id: str | None
    original_url: str
    canonical_url: str | None
    published_at: datetime | None
    input_text: str
    captured_at: datetime
    snapshot_hash: Hash


class StorySource(BaseModel):
    article_id: UUID
    source_id: UUID
    source_name: str
    source_url: str | None
    external_id: str | None
    original_url: str | None
    canonical_url: str | None
    title: str
    excerpt: str
    published_at: datetime | None


class VersionRead(BaseModel):
    id: UUID
    version_number: int
    payload_schema_version: int
    payload: dict
    content_hash: Hash
    origin: str
    actor_issuer: str
    actor_subject: str
    created_at: datetime
    sources: list[SourceSnapshot]


class VersionSummary(BaseModel):
    id: UUID
    version_number: int
    payload_schema_version: int
    content_hash: Hash
    source_count: int
    origin: str
    actor_issuer: str
    actor_subject: str
    created_at: datetime


class EditorialAPIError(BaseModel):
    detail: str


class DraftRead(BaseModel):
    id: UUID
    story_id: UUID
    target_locale: Literal["sr-Latn"]
    status: str
    revision: int
    created_at: datetime
    updated_at: datetime
    current_version: VersionRead | None
    effective_approval: bool


class AuditEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    event_type: str
    from_status: str | None
    to_status: str | None
    version_number: int | None
    command_id: UUID | None
    actor_issuer: str
    actor_subject: str
    occurred_at: datetime
    details: dict
