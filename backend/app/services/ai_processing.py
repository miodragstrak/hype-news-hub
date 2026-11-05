"""Persist before generation; never hold a transaction while invoking a provider."""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from starlette.concurrency import run_in_threadpool

from app.core.content_safety import safe_content_url
from app.models import AIProcessingEvent, AIProcessingRun, CollectedArticle, NewsSource, Story, StoryArticle
from app.schemas.ai_processing import (
    FrozenSource, GenerationBudget, GenerationRequest, GenerationResult, MAX_DETAIL_BYTES, MAX_INPUT_BYTES,
    MAX_INPUT_TEXT_BYTES, MAX_OUTPUT_BYTES, MOCK_WARNING, ProcessingMetadata, SuggestionEvent, SuggestionRead, SuggestionSummary,
)
from app.services.ai_provider import ProviderCancelled, ProviderConfigurationError, ProviderError
from app.services.editorial_commands import EditorialCommands, EditorialCommandError, conflict
from app.schemas.editorial_commands import CommandResult


def encoded(value):
    # Match the conservative JSONB size budget (spaces included), never truncate.
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


class AIProcessing:
    def __init__(self, repository, principal, provider=None):
        self.repository, self.principal = repository, principal
        # Reuse the accepted transaction, actor and command-hash boundary without
        # inheriting draft/review operations. Acceptance calls its shared writer.
        self._commands = EditorialCommands(repository, principal)
        self.provider = provider

    @property
    def actor(self):
        return self._commands.actor

    def transaction(self):
        return self._commands.transaction()

    def request_hash(self, action, identity, command):
        return self._commands.request_hash(action, identity, command)

    def command_lock(self, session, command_id):
        key = int.from_bytes(hashlib.sha256(("ai-command:" + str(command_id)).encode()).digest()[:8], "big", signed=True)
        session.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(:key)"), {"key": key})

    def replay_command(self, session, command_id, request_hash):
        event = session.scalar(select(AIProcessingEvent).where(AIProcessingEvent.command_id == command_id))
        if event and (event.request_hash != request_hash or (event.actor_issuer, event.actor_subject) !=
                      (self.principal.issuer, self.principal.subject)):
            conflict("AI command ID was already used for a different request or identity.")
        return event

    def event(self, session, run, action, *, command=None, request_hash=None, reason=None,
              result=None, occurred_at=None):
        session.add(AIProcessingEvent(run_id=run.id, revision=run.revision, action=action,
            status=run.status, command_id=command.command_id if command else None,
            request_hash=request_hash, reason=reason, result=result,
            **({"occurred_at": occurred_at} if occurred_at is not None else {}), **self.actor))

    def summary(self, row):
        values = {field: getattr(row, field) for field in SuggestionSummary.model_fields if field != "recovery_required"}
        values["recovery_required"] = row.status == "processing" and row.expires_at <= datetime.now(timezone.utc)
        return SuggestionSummary(**values)

    def detail(self, session, run):
        events = session.scalars(select(AIProcessingEvent).where(AIProcessingEvent.run_id == run.id)
            .order_by(AIProcessingEvent.revision).limit(3)).all()
        result = SuggestionRead(**self.summary(run).model_dump(), input=run.input_payload, output=run.output,
            actor_issuer=run.actor_issuer, actor_subject=run.actor_subject,
            events=[SuggestionEvent(**{name: getattr(event, name) for name in SuggestionEvent.model_fields}) for event in events],
            processing_metadata=run.processing_metadata)
        if len(result.model_dump_json().encode()) > MAX_DETAIL_BYTES:
            raise EditorialCommandError(422, "AI suggestion detail exceeds the response budget.")
        return result

    def reserve_daily_budget(self, session):
        # Existing immutable reservations are the durable ledger. Count every
        # Gemini reservation, including failed/interrupted/uncertain outcomes.
        # The same global transaction lock is shared by all application processes.
        # Each query after waiting for the lock must see prior committed
        # reservations. A repeatable snapshot could otherwise undercount them.
        if session.scalar(text("SHOW transaction_isolation")) != "read committed":
            raise EditorialCommandError(503, "AI budget requires read-committed database transactions.")
        session.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(724913802115)"))
        now = session.scalar(select(func.pg_catalog.clock_timestamp()))
        start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        limit = self.repository.config.ai_daily_generation_limit
        if limit <= 0:
            raise EditorialCommandError(429, "Daily AI generation budget is unavailable.")
        caps = session.scalars(select(AIProcessingRun.input_payload["budget"]["daily_limit"].as_integer())
            .where(AIProcessingRun.created_at >= start, AIProcessingRun.created_at < start + timedelta(days=1),
                   AIProcessingRun.provenance["provider"].astext == "gemini").limit(limit)).all()
        # An older/smaller configured ceiling is sticky for the rest of the UTC
        # day. Rolling instances cannot silently increase already reserved budget.
        effective = min([limit, *[cap for cap in caps if cap is not None]])
        if len(caps) >= effective:
            raise EditorialCommandError(429, "Daily AI generation budget has been reached.")
        return now, GenerationBudget(utc_day=start.date(), daily_limit=effective)

    def reserve(self, command):
        digest = self.request_hash("ai.generate", None, command)
        with self.transaction() as session:
            self.command_lock(session, command.command_id)
            event = self.replay_command(session, command.command_id, digest)
            if event:
                run = session.scalar(select(AIProcessingRun).where(AIProcessingRun.id == event.run_id).with_for_update())
                # An uncertain request is never silently executed again, even for
                # a deterministic provider. Retrying the original command seals
                # an expired reservation as interrupted and exposes recovery.
                if run.status == "processing" and run.expires_at <= datetime.now(timezone.utc):
                    self.finish_in_session(session, run, error="process_interrupted")
                return self.detail(session, run), None
            if self.provider is None:
                raise EditorialCommandError(503, "AI suggestion processing is disabled. No mock fallback was used.")
            try:
                self.provider.check_configuration()
            except ProviderConfigurationError:
                raise EditorialCommandError(503, "AI provider configuration is unavailable. No fallback was used.") from None
            pair = session.execute(select(CollectedArticle, NewsSource).join(NewsSource,
                NewsSource.id == CollectedArticle.source_id).join(StoryArticle, StoryArticle.article_id == CollectedArticle.id)
                .where(StoryArticle.story_id == command.story_id, CollectedArticle.id == command.article_id,
                    CollectedArticle.source_id == command.source_id)).first()
            if pair is None:
                raise EditorialCommandError(422, "Select a persisted article/source UUID pair belonging to this story.")
            article, source = pair
            for url in (article.url, article.canonical_url, source.url):
                if url is not None and safe_content_url(url) != url:
                    raise EditorialCommandError(422, "Selected evidence contains an unsupported source URL.")
            input_text = "\n\n".join(value for value in (article.title, article.excerpt, article.content) if value)
            if not input_text.strip() or len(input_text.encode()) > MAX_INPUT_TEXT_BYTES:
                raise EditorialCommandError(422, "Selected source must contain 1–65536 UTF-8 bytes of input text.")
            now, identity = datetime.now(timezone.utc), uuid4()
            request = GenerationRequest(request_id=identity, story_id=command.story_id, source=FrozenSource(
                article_id=article.id, source_id=source.id, source_name=source.name, source_url=source.url,
                external_id=article.external_id, original_url=article.url, canonical_url=article.canonical_url,
                language=article.language, source_language=source.language, published_at=article.published_at, title=article.title,
                excerpt=article.excerpt, content=article.content, input_text=input_text,
                input_text_hash=hashlib.sha256(input_text.encode()).hexdigest(), captured_at=now))
            request = self.provider.prepare(request)
            if self.provider.provenance.provider == "gemini":
                now, budget = self.reserve_daily_budget(session)
                request = request.model_copy(update={"budget": budget})
            payload = request.model_dump(mode="json")
            if len(encoded(payload)) > MAX_INPUT_BYTES:
                raise EditorialCommandError(422, "Selected evidence exceeds the frozen-input budget.")
            run = AIProcessingRun(id=identity, story_id=command.story_id, article_id=command.article_id,
                source_id=command.source_id, command_id=command.command_id, request_hash=digest,
                target_locale=command.target_locale, mode=command.mode, status="processing", revision=1,
                input_payload=payload, provenance=self.provider.provenance.model_dump(mode="json"),
                created_at=now, expires_at=now + timedelta(seconds=self.repository.config.ai_processing_timeout_seconds + 5),
                **self.actor)
            session.add(run)
            session.flush()
            self.event(session, run, "generation.requested", command=command, request_hash=digest)
            session.flush()
            return self.detail(session, run), request

    def validate_output(self, value, request):
        # Round-trip rejects constructed/unvalidated model instances as well as
        # dictionaries, non-finite values, invalid Unicode and unexpected fields.
        if isinstance(value, GenerationResult):
            value = value.model_dump(mode="json")
        if len(encoded(value)) > MAX_OUTPUT_BYTES:
            raise ValueError("Output budget exceeded")
        output = GenerationResult.model_validate(value)
        if output.provenance != self.provider.provenance or (output.provenance.is_mock and MOCK_WARNING not in output.warnings):
            raise ValueError("Provider provenance or explicit mock warning is missing")
        if request.generation_settings and request.generation_settings.output_schema_version == 2 and output.seo is None:
            raise ValueError("Editorial output requires SEO metadata")
        reference = output.source_references[0]
        if (reference.article_id, reference.source_id, reference.input_text_hash) != (
            request.source.article_id, request.source.source_id, request.source.input_text_hash
        ) or reference.excerpt not in request.source.input_text:
            raise ValueError("Source reference is not supported by the frozen input")
        def urls(text):
            # Compare complete literal tokens; never canonicalize opaque URLs or
            # strip characters that might belong to a path/query identity.
            return set(re.findall(r"https?://[^\s<>\"']+", text or "", flags=re.IGNORECASE))
        allowed_urls = set().union(*(urls(text) for text in (request.source.input_text, request.source.source_url,
            request.source.original_url, request.source.canonical_url)))
        generated_text = (output.headline, output.excerpt, output.body, *output.warnings)
        if output.seo:
            generated_text += (output.seo.title, output.seo.description)
        generated_urls = set().union(*(urls(value) for value in generated_text))
        if not generated_urls <= allowed_urls:
            raise ValueError("Generated URLs must be present in frozen evidence")
        return output.model_dump(mode="json")

    def finish_in_session(self, session, run, *, output=None, error=None, processing_metadata=None):
        status = "interrupted" if error == "process_interrupted" else "failed" if error else "succeeded"
        result = session.execute(update(AIProcessingRun).where(AIProcessingRun.id == run.id,
            AIProcessingRun.status == "processing", AIProcessingRun.revision == 1).values(
            status=status, revision=2, output=output, error_code=error, processing_metadata=processing_metadata,
            completed_at=datetime.now(timezone.utc))
            .execution_options(synchronize_session=False))
        if result.rowcount != 1:
            conflict("AI processing completion conflicted with recovery.")
        session.refresh(run)
        self.event(session, run, "generation." + status)
        session.flush()

    def finish(self, run_id, *, output=None, error=None, processing_metadata=None):
        with self.transaction() as session:
            run = session.scalar(select(AIProcessingRun).where(AIProcessingRun.id == run_id).with_for_update())
            if run.status == "processing":
                self.finish_in_session(session, run, output=output, error=error, processing_metadata=processing_metadata)
            # A late completion must never revive an interrupted/rejected run.
            return self.detail(session, run)

    async def generate(self, command):
        receipt, request = await run_in_threadpool(self.reserve, command)
        if request is None:
            return receipt, False
        output, error, metadata = None, None, None
        try:
            async with asyncio.timeout(self.repository.config.ai_processing_timeout_seconds):
                try:
                    value = await self.provider.generate(request)
                except ProviderCancelled as exc:
                    # Capture before this context converts deadline cancellation
                    # into TimeoutError. Explicit cancellation still propagates.
                    metadata = exc.metadata.model_dump(mode="json")
                    # Python 3.12 timeout contexts require the exact base type.
                    raise asyncio.CancelledError() from None
            if isinstance(value, GenerationResult) and value.metadata is not None:
                metadata = ProcessingMetadata.model_validate(value.metadata.model_dump()).model_dump(mode="json")
            try:
                output = self.validate_output(value, request)
            except (ValidationError, ValueError, TypeError, UnicodeError, OverflowError):
                error = "invalid_provider_output"
        except ProviderError as exc:
            error = exc.code
            metadata = exc.metadata.model_dump(mode="json") if exc.metadata is not None else None
        except TimeoutError:
            error = "provider_timeout"
        except asyncio.CancelledError:
            # Process termination may prevent this best-effort seal. The durable
            # reservation/deadline still permits explicit command recovery.
            await asyncio.shield(run_in_threadpool(self.finish, receipt.id, error="process_interrupted",
                processing_metadata=metadata))
            raise
        except Exception:
            error = "provider_failure"
        return await run_in_threadpool(self.finish, receipt.id, output=output, error=error, processing_metadata=metadata), True

    def get(self, run_id):
        with self.repository.read() as session:
            run = session.get(AIProcessingRun, run_id)
            if run is None:
                raise EditorialCommandError(404, "AI suggestion not found.")
            return self.detail(session, run)

    def list(self, story_id, limit, offset):
        with self.repository.read() as session:
            if session.get(Story, story_id) is None:
                raise EditorialCommandError(404, "Persisted story not found.")
            columns = [getattr(AIProcessingRun, name) for name in SuggestionSummary.model_fields if name != "recovery_required"]
            rows = session.execute(select(*columns).where(AIProcessingRun.story_id == story_id)
                .order_by(AIProcessingRun.created_at.desc(), AIProcessingRun.id.desc()).limit(limit).offset(offset))
            return [self.summary(row) for row in rows]

    def reject(self, run_id, command):
        digest = self.request_hash("ai.reject", run_id, command)
        with self.transaction() as session:
            self.command_lock(session, command.command_id)
            replay = self.replay_command(session, command.command_id, digest)
            run = session.scalar(select(AIProcessingRun).where(AIProcessingRun.id == run_id).with_for_update())
            if run is None:
                raise EditorialCommandError(404, "AI suggestion not found.")
            if replay:
                return self.detail(session, run)
            if run.status != "succeeded" or command.expected_revision != run.revision:
                conflict("Only the current successful AI suggestion can be rejected.")
            result = session.execute(update(AIProcessingRun).where(AIProcessingRun.id == run_id,
                AIProcessingRun.status == "succeeded", AIProcessingRun.revision == command.expected_revision)
                .values(status="rejected", revision=3, rejected_at=datetime.now(timezone.utc))
                .execution_options(synchronize_session=False))
            if result.rowcount != 1:
                conflict("Stale AI suggestion revision.")
            session.refresh(run)
            self.event(session, run, "suggestion.rejected", command=command, request_hash=digest, reason=command.reason)
            session.flush()
            return self.detail(session, run)

    def accept(self, run_id, command):
        digest = self.request_hash("ai.accept", run_id, command)
        with self.transaction() as session:
            self.command_lock(session, command.command_id)
            replay = self.replay_command(session, command.command_id, digest)
            if replay:
                # Return the immutable receipt, even if later saves/review have
                # changed the draft. Never reapply content on an old retry.
                return CommandResult.model_validate(replay.result)
            run = session.scalar(select(AIProcessingRun).where(AIProcessingRun.id == run_id).with_for_update())
            if run is None:
                raise EditorialCommandError(404, "AI suggestion not found.")
            if run.story_id != command.story_id:
                conflict("The suggestion does not belong to the intended story.")
            if run.status != "succeeded":
                conflict("Only a completed, unconsumed successful suggestion can be accepted.")
            # Parsing the stored records requires no configured/live provider.
            request = GenerationRequest.model_validate(run.input_payload)
            output = GenerationResult.model_validate(run.output)
            source = request.source
            reference = output.source_references[0]
            if (request.request_id, request.story_id, source.article_id, source.source_id) != (
                run.id, run.story_id, run.article_id, run.source_id
            ) or output.provenance.model_dump(mode="json") != run.provenance or (
                reference.article_id, reference.source_id, reference.input_text_hash
            ) != (source.article_id, source.source_id, source.input_text_hash) or reference.excerpt not in source.input_text:
                conflict("Stored suggestion evidence is inconsistent.")
            attribution = command.payload.source_attribution
            if len(attribution) != 1 or (attribution[0].article_id, attribution[0].source_id) != (source.article_id, source.source_id):
                raise EditorialCommandError(422, "Accepted attribution must exactly match the suggestion's single frozen source.")
            if session.scalar(select(StoryArticle.article_id).where(StoryArticle.story_id == run.story_id,
                StoryArticle.article_id == source.article_id)) is None:
                conflict("The frozen article no longer belongs to the intended story.")
            draft = self._commands.lock_workspace(session, run.story_id, run.target_locale)
            # Editorial command IDs also have a namespace in the workspace;
            # reject collisions there before writing either side of the command.
            if draft and self._commands.replay(session, draft, command, digest) is not None:
                conflict("Acceptance receipt is inconsistent.")
            accepted_at = session.scalar(select(func.pg_catalog.clock_timestamp()))
            snapshots = [{name: getattr(source, name) for name in (
                "source_id", "article_id", "source_name", "source_url", "external_id", "original_url",
                "canonical_url", "published_at", "input_text", "captured_at")}]
            provenance = {
                "suggestion_id": str(run.id), "input_hash": run.input_hash, "output_hash": run.output_hash,
                "provider": run.provenance, "prompt_version": request.prompt_version,
                "publishing_payload_schema_version": 1,
                "article_id": str(source.article_id), "source_id": str(source.source_id),
                "input_text_hash": source.input_text_hash, "language": source.language,
                "source_language": source.source_language,
            }
            if run.processing_metadata is not None:
                provenance["processing_metadata"] = run.processing_metadata
            receipt = self._commands.write_payload(session, draft, command, digest,
                story_id=run.story_id, target_locale=run.target_locale, frozen_sources=snapshots,
                origin="ai", action="accept_ai", ai_provenance=provenance, occurred_at=accepted_at)
            changed = session.execute(update(AIProcessingRun).where(AIProcessingRun.id == run.id,
                AIProcessingRun.status == "succeeded", AIProcessingRun.revision == 2).values(
                status="accepted", revision=3, accepted_at=accepted_at,
                accepted_draft_id=receipt.draft_id, accepted_version_number=receipt.version_number,
                accepted_content_hash=receipt.content_hash).execution_options(synchronize_session=False))
            if changed.rowcount != 1:
                conflict("Suggestion acceptance conflicted with another command.")
            session.refresh(run)
            self.event(session, run, "suggestion.accepted", command=command, request_hash=digest,
                result=receipt.model_dump(mode="json"), occurred_at=accepted_at)
            session.flush()
            return receipt
