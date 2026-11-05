"""Application-owned contracts. Evidence retains its original language and text."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from app.schemas.editorial_commands import CommandResult, PublishingPayload, SEOMetadata, Text

MAX_INPUT_TEXT_BYTES = 64 * 1024
MAX_INPUT_BYTES = 256 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
MAX_DETAIL_BYTES = 512 * 1024
MOCK_WARNING = "DEMO: deterministički mock izlaz; nije stvarni prevod niti proverena vest."
AI_REVIEW_WARNING = "AI predlog zahteva uredničku proveru; navodi iz izvora nisu nezavisno potvrđeni."


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreateSuggestion(FrozenModel):
    command_id: UUID
    story_id: UUID
    article_id: UUID
    source_id: UUID
    target_locale: Literal["sr-Latn"] = "sr-Latn"
    mode: Literal["translation"] = "translation"


class RejectSuggestion(FrozenModel):
    command_id: UUID
    expected_revision: int = Field(ge=1, strict=True)
    reason: Text = Field(max_length=2000)


class AcceptSuggestion(FrozenModel):
    command_id: UUID
    story_id: UUID
    expected_revision: int = Field(ge=0, strict=True)
    payload: PublishingPayload
    confirm_acceptance: Literal[True]

    @field_validator("confirm_acceptance", mode="before")
    @classmethod
    def explicitly_confirmed(cls, value):
        if value is not True:
            raise ValueError("Explicit acceptance confirmation is required.")
        return value


class FrozenSource(FrozenModel):
    article_id: UUID
    source_id: UUID
    source_name: str
    source_url: str
    external_id: str | None
    original_url: str
    canonical_url: str | None
    language: str | None
    source_language: str | None = None
    published_at: datetime | None
    title: str
    excerpt: str
    content: str | None
    input_text: str = Field(min_length=1)
    input_text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: datetime


class GenerationSettings(FrozenModel):
    max_input_tokens: int = Field(ge=1, le=32768, strict=True)
    max_output_tokens: int = Field(ge=1, le=8192, strict=True)
    output_schema_version: Literal[1, 2] = 1


class GenerationBudget(FrozenModel):
    utc_day: date
    daily_limit: int = Field(ge=1, le=100, strict=True)


class GenerationRequest(FrozenModel):
    request_id: UUID
    story_id: UUID
    mode: Literal["translation"] = "translation"
    target_locale: Literal["sr-Latn"] = "sr-Latn"
    prompt_version: Literal["mock-translation-v1", "sr-latn-translation-v1", "sr-latn-ekavian-v2"] = "mock-translation-v1"
    source: FrozenSource
    budget: GenerationBudget | None = None
    instructions: str | None = Field(default=None, max_length=16000)
    generation_settings: GenerationSettings | None = None
    response_schema: str | None = Field(default=None, max_length=16000)

    @model_serializer(mode="wrap")
    def preserve_legacy_mock_shape(self, handler):
        data = handler(self)
        for name in ("instructions", "generation_settings", "response_schema", "budget"):
            if data.get(name) is None:
                data.pop(name, None)
        return data


class ProviderProvenance(FrozenModel):
    provider: Literal["mock", "gemini"] = "mock"
    model: str = Field(default="deterministic-no-translation-v1", min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._-]+$")
    adapter_version: str = Field(default="1", min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9._-]+$")
    is_mock: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def truthful_provider(self):
        if self.is_mock != (self.provider == "mock") or (self.is_mock and self.model != "deterministic-no-translation-v1"):
            raise ValueError("Provider identity and mock marker disagree.")
        return self


class TokenUsage(FrozenModel):
    prompt_tokens: int | None = Field(default=None, ge=0, le=2147483647, strict=True)
    output_tokens: int | None = Field(default=None, ge=0, le=2147483647, strict=True)
    thinking_tokens: int | None = Field(default=None, ge=0, le=2147483647, strict=True)
    cached_tokens: int | None = Field(default=None, ge=0, le=2147483647, strict=True)
    total_tokens: int | None = Field(default=None, ge=0, le=2147483647, strict=True)


class ProcessingMetadata(FrozenModel):
    counted_input_tokens: int | None = Field(default=None, ge=0, le=2147483647, strict=True)
    usage: TokenUsage | None = None
    model_metadata_version: str | None = Field(default=None, max_length=128, pattern=r"^[a-zA-Z0-9._-]+$")
    reported_model_version: str | None = Field(default=None, max_length=128, pattern=r"^[a-zA-Z0-9._-]+$")
    provider_response_id: str | None = Field(default=None, max_length=256, pattern=r"^[a-zA-Z0-9._~+/=:-]+$")
    http_attempts: int = Field(default=0, ge=0, le=6, strict=True)
    generation_attempts: int = Field(default=0, ge=0, le=2, strict=True)
    generation_outcome: Literal["not_started", "rejected", "completed", "unknown"] = "not_started"
    evidence_sufficient: bool | None = None
    output_schema_version: Literal[1, 2] = 1
    estimated_cost: None = None
    pricing_provenance: None = None
    cost_status: Literal["unknown"] = "unknown"


class SourceReference(FrozenModel):
    article_id: UUID
    source_id: UUID
    input_text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Original-language quotations are evidence, not generated sr-Latn prose.
    excerpt: str = Field(min_length=1, max_length=2000)


class GenerationResult(FrozenModel):
    provenance: ProviderProvenance
    headline: Text = Field(max_length=300)
    excerpt: Text = Field(max_length=1000)
    body: Text = Field(max_length=20_000)
    source_references: tuple[SourceReference, ...] = Field(min_length=1, max_length=1)
    warnings: tuple[Text, ...] = Field(min_length=1, max_length=10)
    seo: SEOMetadata | None = None

    @model_serializer(mode="wrap")
    def preserve_sealed_v1_output(self, handler):
        data = handler(self)
        if self.seo is None:
            data.pop("seo", None)
        return data

    # Provider return-channel metadata is sealed separately, including on failed
    # outputs. It never changes the legacy suggestion-content JSON/hash shape.
    metadata: ProcessingMetadata | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="after")
    def latin_generated_text(self):
        for text in (self.headline, self.excerpt, self.body, *self.warnings, *((self.seo.title, self.seo.description) if self.seo else ())):
            if any(unicodedata.category(char).startswith("L") and "LATIN" not in unicodedata.name(char, "") for char in text):
                raise ValueError("Generated editorial prose must use Latin script.")
        return self


ProcessingStatus = Literal["processing", "succeeded", "failed", "interrupted", "rejected", "accepted"]
ProcessingError = Literal["provider_timeout", "provider_failure", "invalid_provider_output", "process_interrupted",
    "provider_auth", "provider_throttled", "provider_unavailable", "provider_invalid_model", "provider_invalid_request",
    "provider_refused", "provider_incomplete", "insufficient_evidence", "input_token_limit", "provider_uncertain", "provider_response_too_large"]


class SuggestionSummary(FrozenModel):
    id: UUID
    story_id: UUID
    article_id: UUID
    source_id: UUID
    command_id: UUID
    target_locale: Literal["sr-Latn"]
    mode: Literal["translation"]
    status: ProcessingStatus
    revision: int
    provenance: ProviderProvenance
    input_hash: str
    output_hash: str | None
    error_code: ProcessingError | None
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None
    rejected_at: datetime | None
    recovery_required: bool


class SuggestionEvent(FrozenModel):
    revision: int
    action: str
    status: ProcessingStatus
    command_id: UUID | None
    actor_issuer: str
    actor_subject: str
    reason: str | None
    occurred_at: datetime
    result: CommandResult | None = None


class SuggestionRead(SuggestionSummary):
    input: GenerationRequest
    output: GenerationResult | None
    actor_issuer: str
    actor_subject: str
    events: list[SuggestionEvent]
    processing_metadata: ProcessingMetadata | None = None
