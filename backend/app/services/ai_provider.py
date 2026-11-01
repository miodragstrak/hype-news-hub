"""Application-owned provider boundary; network adapters live in separate modules."""
import asyncio
from typing import Protocol

from app.schemas.ai_processing import (
    GenerationRequest, GenerationResult, MOCK_WARNING, ProcessingError, ProcessingMetadata, ProviderProvenance, SourceReference,
)


class SuggestionProvider(Protocol):
    @property
    def provenance(self) -> ProviderProvenance: ...

    def check_configuration(self) -> None: ...

    def prepare(self, request: GenerationRequest) -> GenerationRequest: ...

    async def generate(self, request: GenerationRequest) -> GenerationResult: ...


class ProviderConfigurationError(Exception):
    """Local configuration is unavailable; never carries secrets or config values."""


class ProviderError(Exception):
    def __init__(self, code: ProcessingError, metadata: ProcessingMetadata | None = None):
        self.code, self.metadata = code, metadata
        super().__init__(code)


class ProviderCancelled(asyncio.CancelledError):
    """Preserve known accounting while retaining cancellation semantics."""
    def __init__(self, metadata: ProcessingMetadata):
        self.metadata = metadata
        super().__init__()


class MockSuggestionProvider:
    provenance = ProviderProvenance()

    def check_configuration(self):
        pass

    def prepare(self, request):
        return request

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            provenance=self.provenance,
            headline="Demonstracioni predlog — nije prevod",
            excerpt="Deterministički testni predlog za proveru uredničkog toka.",
            body="Ovo je mock predlog. Nije stvarni prevod izvornog članka i ne predstavlja proverenu vest. "
                 "Urednik treba da pročita sačuvani izvorni tekst i sam pripremi članak.",
            source_references=(SourceReference(article_id=request.source.article_id,
                source_id=request.source.source_id, input_text_hash=request.source.input_text_hash,
                excerpt=request.source.input_text[:200]),),
            warnings=(MOCK_WARNING,),
        )
