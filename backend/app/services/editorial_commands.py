"""Transactional editorial commands. Collection projections remain independent."""
from contextlib import contextmanager
import hashlib
import json

from pydantic import ValidationError
from sqlalchemy import String, cast, exists, func, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.content_safety import safe_content_url
from app.core.editorial_security import EditorialPrincipal
from app.database.runtime_security import assert_runtime_role
from app.models import (CollectedArticle, NewsSource, Story, StoryArticle, EditorialDraft,
    EditorialDraftVersion, EditorialVersionSource, EditorialDecision, EditorialEvent)
from app.repositories.news_repository import StorageUnavailable
from app.schemas.editorial_commands import (AuditEvent, CommandResult, DraftRead, PublishingPayload,
    SourceSnapshot, StorySource, VersionRead, VersionSummary)

MAX_HISTORY_RESPONSE_BYTES = 256 * 1024
MAX_VERSION_RESPONSE_BYTES = 32 * 1024 * 1024


class EditorialCommandError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail


def conflict(message="Editorial revision or state conflicts with this command."):
    raise EditorialCommandError(409, message)


class EditorialCommands:
    def __init__(self, repository, principal: EditorialPrincipal):
        self.repository, self.principal = repository, principal

    @property
    def actor(self):
        return {"actor_issuer": self.principal.issuer, "actor_subject": self.principal.subject}

    @contextmanager
    def transaction(self):
        try:
            with self.repository.engine.begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '5s'"))
                connection.execute(text("SET LOCAL statement_timeout = '15s'"))
                assert_runtime_role(connection)
                with Session(bind=connection, expire_on_commit=False, autoflush=False) as session:
                    yield session
                    session.flush()
        except IntegrityError as exc:
            # Only known uniqueness/concurrent-write conflicts are caller conflicts.
            if exc.orig.sqlstate in {"23505", "40001", "40P01"}:
                conflict("Concurrent editorial command conflicted. Refresh and retry.")
            raise StorageUnavailable() from exc
        except SQLAlchemyError as exc:
            if getattr(getattr(exc, "orig", None), "sqlstate", None) in {"40001", "40P01", "55P03"}:
                conflict("Editorial workspace is busy. Retry this command.")
            raise StorageUnavailable() from exc
        except ValueError as exc:
            raise StorageUnavailable() from exc

    def request_hash(self, action, draft_id, command):
        value = {"action": action, "draft_id": str(draft_id) if draft_id else None,
                 "actor": self.actor, "command": command.model_dump(mode="json")}
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

    def replay(self, session, draft, command, request_hash):
        event = session.scalar(select(EditorialEvent).where(EditorialEvent.draft_id == draft.id,
            EditorialEvent.command_id == command.command_id))
        if event:
            if event.request_hash != request_hash or (event.actor_issuer, event.actor_subject) != (self.principal.issuer, self.principal.subject):
                conflict("Command ID was already used for a different request or identity.")
            return CommandResult.model_validate(event.details["result"])

    def current(self, session, draft):
        return session.scalar(select(EditorialDraftVersion).where(EditorialDraftVersion.draft_id == draft.id,
            EditorialDraftVersion.version_number == draft.current_version_number))

    def sources(self, session, draft_id, version_number):
        return list(session.scalars(select(EditorialVersionSource).where(EditorialVersionSource.draft_id == draft_id,
            EditorialVersionSource.version_number == version_number).order_by(EditorialVersionSource.article_id)))

    def snapshots(self, session, draft, payload):
        # Reuse prior frozen evidence verbatim; recollection must not silently alter
        # the input underpinning a manual edit. Newly selected members are captured
        # in one statement, so article/source fields share one MVCC snapshot.
        previous = {row.article_id: row for row in self.sources(session, draft.id, draft.current_version_number)} if draft.current_version_number else {}
        selected = {source.article_id: source.source_id for source in payload.source_attribution}
        rows = session.execute(select(CollectedArticle, NewsSource).join(NewsSource, NewsSource.id == CollectedArticle.source_id)
            .join(StoryArticle, StoryArticle.article_id == CollectedArticle.id)
            .where(StoryArticle.story_id == draft.story_id, CollectedArticle.id.in_(selected))).all()
        available = {article.id: (article, source) for article, source in rows}
        snapshots = []
        for article_id, source_id in selected.items():
            old = previous.get(article_id)
            if old is not None and old.source_id == source_id:
                values = {name: getattr(old, name) for name in ("article_id", "source_id", "source_name", "source_url",
                    "external_id", "original_url", "canonical_url", "published_at", "input_text", "captured_at")}
            else:
                pair = available.get(article_id)
                if pair is None or pair[0].source_id != source_id:
                    raise EditorialCommandError(422, "Every source must be a matching article/source UUID pair belonging to this story.")
                article, source = pair
                if any(url is not None and safe_content_url(url) is None for url in (source.url, article.url, article.canonical_url)):
                    raise EditorialCommandError(422, "Selected source has an unsupported attribution URL.")
                values = dict(article_id=article.id, source_id=source.id, source_name=source.name, source_url=source.url,
                    external_id=article.external_id, original_url=article.url, canonical_url=article.canonical_url,
                    published_at=article.published_at, input_text="\n\n".join(value for value in (article.title, article.excerpt, article.content) if value))
            snapshots.append(values)
        if sum(len(row["input_text"].encode()) for row in snapshots) > 4 * 1024 * 1024:
            raise EditorialCommandError(422, "Selected source input exceeds the 4 MiB workspace limit.")
        return snapshots

    def add_version(self, session, draft, payload, number, snapshots, *, origin="manual"):
        version = EditorialDraftVersion(draft_id=draft.id, version_number=number,
            payload=payload.model_dump(mode="json"), source_count=len(snapshots), origin=origin, **self.actor)
        session.add(version)
        session.flush()
        for values in snapshots:
            session.add(EditorialVersionSource(draft_id=draft.id, version_number=number, **values))
        session.flush()
        return version

    def cas(self, session, draft, command, status, version_number):
        # Explicit predicate AND rowcount for every command update, including this
        # Core SQL path. Row locks alone never substitute for expected revisions.
        result = session.execute(update(EditorialDraft).where(EditorialDraft.id == draft.id,
            EditorialDraft.revision == command.expected_revision).values(status=status,
            current_version_number=version_number, revision=command.expected_revision + 1)
            .execution_options(synchronize_session=False))
        if result.rowcount != 1:
            conflict("Stale editorial revision. Refresh before saving or deciding.")
        session.refresh(draft)

    def record(self, session, draft, version, command, request_hash, action, previous, decision=None,
               *, ai_provenance=None, occurred_at=None):
        result = CommandResult(command_id=command.command_id, draft_id=draft.id, revision=draft.revision,
            status=draft.status, version_number=version.version_number, content_hash=version.content_hash)
        details = {"result": result.model_dump(mode="json")}
        if getattr(command, "reason", None):
            details["reason"] = command.reason
        if decision:
            details["decision_id"] = str(decision.id)
        if ai_provenance is not None:
            details["ai_provenance"] = ai_provenance
        session.add(EditorialEvent(draft_id=draft.id, version_number=version.version_number,
            event_type="draft." + action, from_status=previous, to_status=draft.status,
            command_id=command.command_id, request_hash=request_hash, details=details,
            occurred_at=occurred_at if occurred_at is not None else func.pg_catalog.clock_timestamp(), **self.actor))
        session.flush()
        return result

    def lock_workspace(self, session, story_id, target_locale):
        # Shared by manual creation and AI acceptance across application instances.
        key = int.from_bytes(hashlib.sha256(f"editorial:{story_id}:{target_locale}".encode()).digest()[:8], "big", signed=True)
        session.execute(text("SELECT pg_catalog.pg_advisory_xact_lock(:key)"), {"key": key})
        return session.scalar(select(EditorialDraft).where(EditorialDraft.story_id == story_id,
            EditorialDraft.target_locale == target_locale).with_for_update())

    def write_payload(self, session, draft, command, request_hash, *, story_id=None, target_locale="sr-Latn",
                      frozen_sources=None, origin="manual", action=None, ai_provenance=None, occurred_at=None):
        """One version-writing path for manual commands and trusted AI acceptance.

        Callers own the transaction, workspace lock and idempotency check. Frozen
        sources/provenance/origin are internal arguments, never public command fields.
        """
        previous = draft.status if draft else None
        if draft is None:
            if command.expected_revision != 0:
                conflict("Creating a workspace requires expected_revision zero.")
            if session.get(Story, story_id) is None:
                raise EditorialCommandError(404, "Persisted story not found.")
            draft = EditorialDraft(story_id=story_id, target_locale=target_locale, current_version_number=1, **self.actor)
            session.add(draft)
            session.flush()
            number = 1
        else:
            if draft.revision != command.expected_revision:
                conflict("Stale editorial revision. Refresh before saving or deciding.")
            if previous not in {"editing", "changes_requested", "approved"}:
                conflict("Reopen rejected drafts before editing; submitted drafts require a review decision.")
            current = self.current(session, draft)
            if origin == "manual" and current and current.payload == command.payload.model_dump(mode="json"):
                raise EditorialCommandError(422, "Payload is unchanged; no revision was created.")
            number = (draft.current_version_number or 0) + 1
        snapshots = frozen_sources if frozen_sources is not None else self.snapshots(session, draft, command.payload)
        version = self.add_version(session, draft, command.payload, number, snapshots, origin=origin)
        if previous is not None:
            self.cas(session, draft, command, "editing", number)
        return self.record(session, draft, version, command, request_hash,
            action or ("create" if previous is None else "save"), previous,
            ai_provenance=ai_provenance, occurred_at=occurred_at)

    def create(self, command):
        request_hash = self.request_hash("create", None, command)
        with self.transaction() as session:
            draft = self.lock_workspace(session, command.story_id, command.target_locale)
            if draft:
                result = self.replay(session, draft, command, request_hash)
                if result:
                    return result
                conflict("A workspace already exists for this story and locale.")
            return self.write_payload(session, None, command, request_hash, story_id=command.story_id,
                target_locale=command.target_locale)

    def execute(self, draft_id, action, command):
        request_hash = self.request_hash(action, draft_id, command)
        with self.transaction() as session:
            draft = session.scalar(select(EditorialDraft).where(EditorialDraft.id == draft_id).with_for_update())
            if draft is None:
                raise EditorialCommandError(404, "Editorial draft not found.")
            result = self.replay(session, draft, command, request_hash)
            if result:
                return result
            if draft.revision != command.expected_revision:
                conflict("Stale editorial revision. Refresh before saving or deciding.")
            previous = draft.status
            version = self.current(session, draft)
            decision = None
            if action == "save":
                return self.write_payload(session, draft, command, request_hash)
            else:
                if version is None or (version.version_number, version.content_hash) != (command.version_number, command.content_hash):
                    conflict("Command must reference this draft's exact current version and content hash.")
                if action == "submit":
                    if previous != "editing":
                        conflict("Only editing drafts can be submitted.")
                    try:
                        PublishingPayload.model_validate(version.payload)
                    except ValidationError:
                        raise EditorialCommandError(422, "Replace the legacy version with a complete publishing payload before submission.") from None
                    target = "in_review"
                elif action == "reopen":
                    if previous not in {"rejected", "changes_requested"}:
                        conflict("Only rejected drafts or requested changes can be reopened.")
                    target = "editing"
                else:
                    if previous != "in_review":
                        conflict("Only the current in-review version can receive a decision.")
                    target = {"approve": "approved", "request_changes": "changes_requested", "reject": "rejected"}[action]
                    decision = EditorialDecision(draft_id=draft.id, version_number=version.version_number,
                        content_hash=version.content_hash, decision=action, reason=command.reason,
                        decided_at=func.pg_catalog.clock_timestamp(), **self.actor)
                    session.add(decision)
                    session.flush()
            self.cas(session, draft, command, target, version.version_number)
            result = self.record(session, draft, version, command, request_hash, action, previous, decision)
            if action == "approve" and not self.effective_approval(session, draft, version):
                conflict("Unpaired legacy decisions require a new content version before approval.")
            return result

    def effective_approval(self, session, draft, version):
        if draft.status != "approved" or version is None:
            return False
        # The current head's committed command is authoritative, not the existence
        # of an earlier approve row. Legacy/unpaired decisions fail closed.
        head = list(session.scalars(select(EditorialEvent).where(EditorialEvent.draft_id == draft.id,
            EditorialEvent.version_number == version.version_number,
            EditorialEvent.details.contains({"result": {"revision": draft.revision}})).limit(2)))
        if len(head) != 1 or head[0].event_type != "draft.approve":
            return False
        event = head[0]
        paired = exists(select(EditorialEvent.id).where(EditorialEvent.draft_id == draft.id,
            EditorialEvent.version_number == version.version_number,
            EditorialEvent.details["decision_id"].as_string() == cast(EditorialDecision.id, String)))
        if session.scalar(select(exists(select(EditorialDecision.id).where(EditorialDecision.draft_id == draft.id,
            EditorialDecision.version_number == version.version_number, ~paired)))):
            return False
        return session.scalar(select(exists(select(EditorialDecision.id).where(EditorialDecision.draft_id == draft.id,
            EditorialDecision.version_number == version.version_number,
            cast(EditorialDecision.id, String) == event.details.get("decision_id"),
            EditorialDecision.decision == "approve", EditorialDecision.content_hash == version.content_hash,
            EditorialDecision.actor_issuer == event.actor_issuer, EditorialDecision.actor_subject == event.actor_subject))))

    def version_read(self, session, version):
        return VersionRead(**{name: getattr(version, name) for name in ("id", "version_number", "payload_schema_version",
            "payload", "content_hash", "origin", "actor_issuer", "actor_subject", "created_at")},
            sources=[SourceSnapshot.model_validate(row) for row in self.sources(session, version.draft_id, version.version_number)])

    def get(self, draft_id=None, *, story_id=None):
        with self.repository.read() as session:
            draft = session.scalar(select(EditorialDraft).where(EditorialDraft.id == draft_id) if draft_id else
                select(EditorialDraft).where(EditorialDraft.story_id == story_id, EditorialDraft.target_locale == "sr-Latn"))
            if draft is None:
                raise EditorialCommandError(404, "Editorial draft not found.")
            version = self.current(session, draft)
            return DraftRead(**{name: getattr(draft, name) for name in ("id", "story_id", "target_locale", "status", "revision", "created_at", "updated_at")},
                current_version=self.version_read(session, version) if version else None,
                effective_approval=self.effective_approval(session, draft, version))

    def history(self, draft_id, kind, limit, offset):
        with self.repository.read() as session:
            if session.get(EditorialDraft, draft_id) is None:
                raise EditorialCommandError(404, "Editorial draft not found.")
            if kind == "versions":
                # Project metadata only: payload/source text never travels from
                # PostgreSQL for the list, regardless of archive size.
                fields = [getattr(EditorialDraftVersion, name) for name in VersionSummary.model_fields]
                rows = session.execute(select(*fields).where(EditorialDraftVersion.draft_id == draft_id)
                    .order_by(EditorialDraftVersion.version_number).limit(limit).offset(offset)).mappings()
                summaries = [VersionSummary.model_validate(row) for row in rows]
                size = 2 + max(0, len(summaries) - 1) + sum(len(row.model_dump_json().encode()) for row in summaries)
                if size > MAX_HISTORY_RESPONSE_BYTES:
                    raise EditorialCommandError(422, "Version history exceeds the 256 KiB response budget; request a smaller limit.")
                return summaries
            rows = session.scalars(select(EditorialEvent).where(EditorialEvent.draft_id == draft_id)
                .order_by(EditorialEvent.occurred_at, EditorialEvent.id).limit(limit).offset(offset))
            return [AuditEvent.model_validate(row) for row in rows]

    def get_version(self, draft_id, version_number):
        with self.repository.read() as session:
            # Count serialized bytes inside PostgreSQL before loading potentially
            # large legacy metadata/evidence into application memory. row_to_json
            # includes more fields than the public version shape; padding covers
            # timestamp serialization and the outer response structure.
            size = session.execute(text("""SELECT pg_catalog.octet_length(pg_catalog.row_to_json(v)::pg_catalog.text) + 1024 +
                coalesce((SELECT pg_catalog.sum(pg_catalog.octet_length(pg_catalog.row_to_json(s)::pg_catalog.text) + 64)
                    FROM public.editorial_version_sources s WHERE s.draft_id = v.draft_id
                    AND s.version_number = v.version_number), 0)
                FROM public.editorial_draft_versions v
                WHERE v.draft_id = :draft_id AND v.version_number = :version_number"""),
                {"draft_id": draft_id, "version_number": version_number}).scalar_one_or_none()
            if size is None:
                raise EditorialCommandError(404, "Editorial version not found.")
            if size > MAX_VERSION_RESPONSE_BYTES:
                raise EditorialCommandError(422, "Editorial version exceeds the 32 MiB detail response budget.")
            version = session.scalar(select(EditorialDraftVersion).where(EditorialDraftVersion.draft_id == draft_id,
                EditorialDraftVersion.version_number == version_number))
            result = self.version_read(session, version)
            if len(result.model_dump_json().encode()) > MAX_VERSION_RESPONSE_BYTES:
                raise EditorialCommandError(422, "Editorial version exceeds the 32 MiB detail response budget.")
            return result

    def story_sources(self, story_id, limit, offset):
        with self.repository.read() as session:
            if session.get(Story, story_id) is None:
                raise EditorialCommandError(404, "Persisted story not found.")
            rows = session.execute(select(CollectedArticle.id.label("article_id"), CollectedArticle.source_id,
                NewsSource.name.label("source_name"), NewsSource.url.label("source_url"), CollectedArticle.external_id,
                CollectedArticle.url.label("original_url"), CollectedArticle.canonical_url,
                CollectedArticle.title, CollectedArticle.excerpt, CollectedArticle.published_at).join(NewsSource,
                NewsSource.id == CollectedArticle.source_id).join(StoryArticle,
                StoryArticle.article_id == CollectedArticle.id).where(StoryArticle.story_id == story_id)
                .order_by(CollectedArticle.id).limit(limit).offset(offset)).mappings()
            return [StorySource(**(dict(row) | {name: safe_content_url(row[name]) for name in
                ("source_url", "original_url", "canonical_url")})) for row in rows]
