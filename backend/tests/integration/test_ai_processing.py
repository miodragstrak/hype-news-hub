"""Real PostgreSQL requests under the restricted runtime identity; no live providers."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import threading
from unittest.mock import patch
from uuid import UUID, uuid4

from alembic import command as alembic_command
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.main import create_app
from app.core.config import Settings
from app.database.runtime_security import provision_runtime_role
from app.models import AIProcessingEvent, AIProcessingRun, CollectedArticle, EditorialDraft, EditorialDraftVersion, EditorialEvent, NewsSource
from app.schemas.ai_processing import CreateSuggestion, MOCK_WARNING, MAX_OUTPUT_BYTES
from app.services.ai_processing import AIProcessing
from app.services.ai_provider import MockSuggestionProvider
from app.core.editorial_security import EditorialPrincipal, EditorialRole
from editorial_identity import TestIdentityVerifier
from integration.test_persistent_collection import PersistentCollectionCase, post, source
from tests.integration.test_postgresql import alembic_config

BASE = "/api/editorial/ai/suggestions"


class ControlledProvider(MockSuggestionProvider):
    def __init__(self, transform=None):
        self.calls = []
        self.transform = transform

    async def generate(self, request):
        self.calls.append(request)
        result = await super().generate(request)
        return self.transform(result, request) if self.transform else result


class AIProcessingCase(PersistentCollectionCase):
    def setUp(self):
        super().setUp()
        response = self.collect([source(posts=[post(language="sr-Cyrl")])])
        self.story_id = response.json()["stories"][0]["id"]
        with self.factory() as session:
            article = session.scalar(select(CollectedArticle))
            self.article_id, self.source_id = str(article.id), str(article.source_id)
        self.provider = ControlledProvider()
        self.private_app = create_app(self.runtime_config, editorial_identity_verifier=TestIdentityVerifier(), ai_provider=self.provider)
        self.private = TestClient(self.private_app)

    def tearDown(self):
        self.private.close()
        if "engine" in self.private_app.state.news_repository.__dict__:
            self.private_app.state.news_repository.engine.dispose()
        with self.engine.begin() as connection:
            connection.execute(text("TRUNCATE public.ai_processing_events, public.ai_processing_runs, public.editorial_events, "
                "public.editorial_decisions, public.editorial_version_sources, public.editorial_draft_versions, public.editorial_drafts"))
        super().tearDown()

    def headers(self, role="editor"):
        return {"Authorization": "Bearer fixture-" + role}

    def creation(self, **changes):
        return dict(command_id=str(uuid4()), story_id=self.story_id, article_id=self.article_id,
                    source_id=self.source_id, mode="translation", target_locale="sr-Latn") | changes

    def create(self, body=None, client=None, expected=201):
        response = (client or self.private).post(BASE, json=body or self.creation(), headers=self.headers())
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def read(self, identity, client=None):
        response = (client or self.private).get(f"{BASE}/{identity}", headers=self.headers("reader"))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return response.json()


class AIProcessingIntegrationTests(AIProcessingCase):

    def test_success_persists_exact_provider_input_and_survives_new_application(self):
        body = self.creation()
        result = self.create(body)
        self.assertEqual((result["status"], result["revision"]), ("succeeded", 2))
        self.assertEqual(result["input"], json.loads(self.provider.calls[0].model_dump_json()))
        self.assertEqual(result["input"]["source"]["language"], "sr-Cyrl")
        self.assertEqual(result["input"]["source"]["input_text_hash"], hashlib.sha256(
            result["input"]["source"]["input_text"].encode()).hexdigest())
        self.assertEqual([e["action"] for e in result["events"]], ["generation.requested", "generation.succeeded"])
        self.assertIn(MOCK_WARNING, result["output"]["warnings"])
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT input_payload::text, output::text FROM public.ai_processing_runs WHERE id=:id"),
                                     {"id": UUID(result["id"])}).one()
            self.assertEqual(result["input_hash"], hashlib.sha256(row[0].encode()).hexdigest())
            self.assertEqual(result["output_hash"], hashlib.sha256(row[1].encode()).hexdigest())
        restarted = create_app(self.runtime_config, editorial_identity_verifier=TestIdentityVerifier())
        try:
            with TestClient(restarted) as other:
                self.assertEqual(self.read(result["id"], other), result)
                self.assertEqual(self.create(body, other, expected=200), result)
        finally:
            restarted.state.news_repository.engine.dispose()
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual((self.count(AIProcessingRun), self.count(AIProcessingEvent)), (1, 2))

    def test_duplicate_commands_and_changed_payload_or_identity_conflict(self):
        body = self.creation()
        first = self.create(body)
        self.assertEqual(self.create(body, expected=200), first)
        for changed in (body | {"article_id": str(uuid4())}, body | {"story_id": str(uuid4())}):
            self.create(changed, expected=409)
        response = self.private.post(BASE, json=body, headers=self.headers("administrator"))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.provider.calls), 1)

    def test_missing_mismatched_cross_story_and_duplicate_external_ids(self):
        self.collect([source("second", posts=[post(title="Unrelated national parliamentary budget", url="https://second.invalid/item")])])
        with self.factory() as session:
            other = session.scalar(select(CollectedArticle).where(CollectedArticle.id != UUID(self.article_id)))
            self.assertEqual(other.external_id, "1")
            invalid = [self.creation(story_id=str(uuid4())), self.creation(article_id=str(uuid4())),
                       self.creation(source_id=str(uuid4())), self.creation(article_id=str(other.id), source_id=str(other.source_id))]
        for body in invalid:
            self.create(body, expected=422)
        self.assertEqual((self.count(AIProcessingRun), self.count(AIProcessingEvent)), (0, 0))
        self.assertEqual(self.provider.calls, [])

    def test_frozen_evidence_is_not_changed_by_recollection(self):
        first = self.create()
        self.collect([source(posts=[post(title="Changed title", content="Changed upstream text", language="en")])])
        self.assertEqual(self.read(first["id"]), first)
        second = self.create()
        self.assertNotEqual(second["input_hash"], first["input_hash"])
        self.assertEqual(second["input"]["source"]["content"], "Changed upstream text")

    def test_raw_original_unicode_and_line_endings_are_frozen_without_rewriting(self):
        original = "Тачан текст.\r\n\nČćšžđ\tUnicode 東京."
        # Collection normalization is independently tested; freeze exactly the
        # persisted value, including valid text not present in normalized feeds.
        with self.factory.begin() as session:
            session.get(CollectedArticle, UUID(self.article_id)).content = original
            session.get(CollectedArticle, UUID(self.article_id)).language = None
            session.get(NewsSource, UUID(self.source_id)).language = "sr-Cyrl"
        result = self.create()
        self.assertEqual(result["input"]["source"]["content"], original)
        self.assertTrue(result["input"]["source"]["input_text"].endswith(original))
        self.assertIsNone(result["input"]["source"]["language"])
        self.assertEqual(result["input"]["source"]["source_language"], "sr-Cyrl")

    def test_oversized_input_and_output_rejected_without_silent_truncation(self):
        with self.factory.begin() as session:
            session.get(CollectedArticle, UUID(self.article_id)).content = "č" * 40_000
        self.create(expected=422)
        self.assertEqual(self.count(AIProcessingRun), 0)
        with self.factory.begin() as session:
            session.get(CollectedArticle, UUID(self.article_id)).content = "Original body"
        self.provider.transform = lambda result, request: result.model_dump(mode="json") | {"body": "x" * (MAX_OUTPUT_BYTES + 1)}
        result = self.create()
        self.assertEqual((result["status"], result["error_code"], result["output"]), ("failed", "invalid_provider_output", None))

    def test_invalid_output_or_fabricated_references_are_not_persisted_as_suggestions(self):
        def changed_reference(result, request):
            data = result.model_dump(mode="json")
            data["source_references"][0]["article_id"] = str(uuid4())
            return data
        def invented_quote(result, request):
            data = result.model_dump(mode="json")
            data["source_references"][0]["excerpt"] = "Quotation that is absent from source"
            return data
        for transform in (changed_reference, invented_quote,
            lambda result, request: result.model_dump(mode="json") | {"body": "<script>alert(1)</script>"},
            lambda result, request: result.model_dump(mode="json") | {"body": "Ћирилица"},
            lambda result, request: result.model_dump(mode="json") | {"headline": float("nan")},
            lambda result, request: result.model_dump(mode="json") | {"warnings": []},
            lambda result, request: result.model_dump(mode="json") | {"warnings": ["Nedostaje obavezna demo oznaka."]},
            lambda result, request: {"sensitive": "do-not-reflect-provider-output"}):
            self.provider.transform = transform
            result = self.create()
            self.assertEqual((result["status"], result["error_code"], result["output"]), ("failed", "invalid_provider_output", None))
            self.assertNotIn("do-not-reflect", json.dumps(result))

    def test_malformed_commands_write_no_requests_or_editorial_history(self):
        for body, content_type, status in ((b'{"headline": NaN}', "application/json", 400),
            (b'{"headline":"\\ud800"}', "application/json", 400), (b'\xff', "application/octet-stream", 415),
            (b'\xff', "application/json", 400)):
            response = self.private.post(BASE, content=body, headers=self.headers() | {"Content-Type": content_type})
            self.assertEqual(response.status_code, status, response.text)
        self.assertEqual((self.count(AIProcessingRun), self.count(AIProcessingEvent), self.count(EditorialEvent)), (0, 0, 0))

    def test_provider_failure_timeout_and_safe_retry(self):
        def broken(result, request):
            raise RuntimeError("sensitive provider secret")
        self.provider.transform = broken
        body = self.creation()
        first = self.create(body)
        self.assertEqual((first["status"], first["error_code"]), ("failed", "provider_failure"))
        self.assertNotIn("sensitive", json.dumps(first))
        self.assertEqual(self.create(body, expected=200), first)
        self.assertEqual(len(self.provider.calls), 1)
        async def timeout(request):
            await asyncio.Future()
        self.private_app.state.ai_provider = ControlledProvider()
        self.private_app.state.ai_provider.generate = timeout
        self.private_app.state.news_repository.config = self.runtime_config.model_copy(update={"ai_processing_timeout_seconds": 0.02})
        timed = self.create()
        self.assertEqual((timed["status"], timed["error_code"]), ("failed", "provider_timeout"))
        self.private_app.state.ai_provider = self.provider
        self.provider.transform = None
        self.assertEqual(self.create()["status"], "succeeded")

    def test_rejection_is_idempotent_version_checked_and_preserves_evidence(self):
        first = self.create()
        body = dict(command_id=str(uuid4()), expected_revision=1, reason="Predlog nije upotrebljiv.")
        path = f"{BASE}/{first['id']}/reject"
        self.assertEqual(self.private.post(path, json=body, headers=self.headers()).status_code, 409)
        body["expected_revision"] = 2
        response = self.private.post(path, json=body, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual((result["status"], result["revision"]), ("rejected", 3))
        self.assertEqual((result["input"], result["output"], result["output_hash"]), (first["input"], first["output"], first["output_hash"]))
        self.assertEqual(self.private.post(path, json=body, headers=self.headers()).json(), result)
        self.assertEqual(self.private.post(path, json=body | {"reason": "Drugi razlog"}, headers=self.headers()).status_code, 409)
        self.assertEqual(self.count(AIProcessingEvent), 3)

    def test_authorization_matrix_for_all_endpoints(self):
        result = self.create()
        for role in ("reader", "editor", "reviewer", "publisher", "administrator", "no-roles"):
            can_read, can_edit = role != "no-roles", role in {"editor", "administrator"}
            headers = self.headers(role)
            for url in (BASE + "?story_id=" + self.story_id, BASE + "/" + result["id"]):
                self.assertEqual(self.private.get(url, headers=headers).status_code, 200 if can_read else 403)
            self.assertEqual(self.private.post(BASE, json=self.creation(), headers=headers).status_code, 201 if can_edit else 403)
            rejection = dict(command_id=str(uuid4()), expected_revision=2, reason="Razlog")
            # Stale revision avoids changing state while exercising permission boundaries.
            rejection["expected_revision"] = 1
            self.assertEqual(self.private.post(BASE + "/" + result["id"] + "/reject", json=rejection,
                headers=headers).status_code, 409 if can_edit else 403)
        self.assertEqual(self.private.get(BASE + "/" + result["id"]).status_code, 401)
        forged = self.creation() | {"actor_subject": "administrator"}
        self.assertEqual(self.private.post(BASE, json=forged, headers=self.headers()).status_code, 422)

    def test_disabled_provider_does_not_create_mock_or_request_rows(self):
        self.private_app.state.ai_provider = None
        self.create(expected=503)
        self.assertEqual(self.count(AIProcessingRun), 0)

    def test_list_is_paginated_lightweight_and_bounded(self):
        for _ in range(3):
            self.create()
        url = BASE + "?story_id=" + self.story_id
        first = self.private.get(url + "&limit=2", headers=self.headers("reader")).json()
        second = self.private.get(url + "&limit=2&offset=2", headers=self.headers("reader")).json()
        self.assertEqual((len(first), len(second)), (2, 1))
        self.assertEqual(len({row["id"] for row in first + second}), 3)
        self.assertFalse({"input", "output", "events"} & first[0].keys())
        statements = []
        def capture(conn, cursor, statement, *args):
            if "FROM public.ai_processing_runs" in statement:
                statements.append(statement)
        engine = self.private_app.state.news_repository.engine
        event.listen(engine, "before_cursor_execute", capture)
        try:
            self.private.get(url, headers=self.headers("reader"))
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        self.assertEqual(len(statements), 1)
        self.assertNotIn("input_payload", statements[0])
        self.assertNotIn("ai_processing_runs.output,", statements[0])
        for suffix in ("&limit=51", "&limit=0", "&offset=-1", "&offset=1000001"):
            self.assertEqual(self.private.get(url + suffix, headers=self.headers("reader")).status_code, 422)

    def test_concurrent_independent_applications_execute_generation_once(self):
        entered, release = threading.Event(), threading.Event()
        original = self.provider.generate
        async def delayed(request):
            entered.set()
            await asyncio.to_thread(release.wait, 10)
            return await original(request)
        self.provider.generate = delayed
        other_app = create_app(self.runtime_config, editorial_identity_verifier=TestIdentityVerifier(), ai_provider=self.provider)
        body = self.creation()
        try:
            with TestClient(other_app) as other, ThreadPoolExecutor() as pool:
                pending = pool.submit(self.private.post, BASE, json=body, headers=self.headers())
                self.assertTrue(entered.wait(10))
                duplicate = other.post(BASE, json=body, headers=self.headers())
                self.assertEqual(duplicate.status_code, 202, duplicate.text)
                release.set()
                completed = pending.result(15)
                self.assertEqual(completed.status_code, 201, completed.text)
                self.assertEqual(completed.json()["id"], duplicate.json()["id"])
        finally:
            release.set()
            other_app.state.news_repository.engine.dispose()
        self.assertEqual((len(self.provider.calls), self.count(AIProcessingRun), self.count(AIProcessingEvent)), (1, 1, 2))

    def test_crash_reservation_recovery_never_reexecutes_or_restores_late_output(self):
        principal = EditorialPrincipal("urn:hnh:test", "test-editor", frozenset({EditorialRole.EDITOR}))
        repository = self.private_app.state.news_repository
        processor = AIProcessing(repository, principal, self.provider)
        body = self.creation()
        # Commit just the reservation, simulating termination before provider completion.
        # Past capture time creates an expired lease without mutating immutable DB fields.
        class PastClock:
            @staticmethod
            def now(tz):
                return datetime.now(tz) - timedelta(minutes=1)
        with patch("app.services.ai_processing.datetime", PastClock):
            reserved, request = processor.reserve(CreateSuggestion(**body))
        self.assertEqual(reserved.status, "processing")
        self.assertTrue(self.read(str(reserved.id))["recovery_required"])
        recovered = self.create(body, expected=200)
        self.assertEqual((recovered["status"], recovered["error_code"]), ("interrupted", "process_interrupted"))
        self.assertEqual(self.provider.calls, [])
        late = asyncio.run(self.provider.generate(request)).model_dump(mode="json")
        self.assertEqual(processor.finish(reserved.id, output=late).status, "interrupted")
        self.assertEqual(self.count(AIProcessingEvent), 2)

    def test_no_database_transaction_is_held_during_provider_and_failure_rolls_back(self):
        def inspect_provider(result, request):
            self.assertEqual(self.private_app.state.news_repository.engine.pool.checkedout(), 0)
            with self.factory() as session:
                self.assertEqual(session.get(AIProcessingRun, request.request_id).status, "processing")
                self.assertEqual(session.get(CollectedArticle, UUID(self.article_id)).content, "Original source body")
            return result
        self.provider.transform = inspect_provider
        self.assertEqual(self.create()["status"], "succeeded")
        original_event = AIProcessing.event
        def fail_event(processor, session, run, action, **kwargs):
            if action == "generation.succeeded":
                raise RuntimeError("injected transaction failure")
            return original_event(processor, session, run, action, **kwargs)
        body = self.creation()
        with patch.object(AIProcessing, "event", fail_event), TestClient(self.private_app, raise_server_exceptions=False) as client:
            response = client.post(BASE, json=body, headers=self.headers())
            self.assertEqual(response.status_code, 500)
        with self.factory() as session:
            run = session.scalar(select(AIProcessingRun).where(AIProcessingRun.command_id == UUID(body["command_id"])))
            self.assertEqual((run.status, run.output, run.revision), ("processing", None, 1))

    def test_runtime_and_owner_cannot_mutate_committed_input_results_or_events(self):
        result = self.create()
        statements = ["UPDATE public.ai_processing_runs SET input_payload = '{}'::jsonb, revision = revision + 1",
            "UPDATE public.ai_processing_runs SET output = '{}'::jsonb, revision = revision + 1",
            "UPDATE public.ai_processing_events SET reason = 'tampered'",
            "DELETE FROM public.ai_processing_events", "DELETE FROM public.ai_processing_runs"]
        for engine in (self.engine, self.private_app.state.news_repository.engine):
            for statement in statements:
                with self.subTest(statement=statement, owner=engine is self.engine), self.assertRaises(SQLAlchemyError):
                    with engine.begin() as connection:
                        connection.execute(text(statement))
        with self.assertRaises(SQLAlchemyError), self.private_app.state.news_repository.engine.begin() as connection:
            connection.execute(text("TRUNCATE public.ai_processing_events, public.ai_processing_runs"))
        self.assertEqual(self.read(result["id"]), result)

    def test_missing_atomic_event_is_rejected_at_commit(self):
        # Construct a valid reservation through production code, then attempt a
        # valid state change without its required history event as owner.
        principal = EditorialPrincipal("urn:hnh:test", "test-editor", frozenset({EditorialRole.EDITOR}))
        reserved, _ = AIProcessing(self.private_app.state.news_repository, principal, self.provider).reserve(CreateSuggestion(**self.creation()))
        with self.assertRaises(SQLAlchemyError), self.engine.begin() as connection:
            connection.execute(text("UPDATE public.ai_processing_runs SET status='failed',revision=2, "
                "error_code='provider_failure',completed_at=now() WHERE id=:id"), {"id": reserved.id})
        self.assertEqual(self.read(str(reserved.id))["status"], "processing")

    def test_generation_and_rejection_do_not_mutate_editorial_approval_or_public_data(self):
        payload = dict(headline="Urednički naslov", body="Tekst uredničkog članka.", excerpt="Kratak opis.",
            slug="urednicki-naslov", categories=["Zabava"], tags=[], seo={"title": "Naslov", "description": "Opis"}, images=[],
            source_attribution=[{"article_id": self.article_id, "source_id": self.source_id}])
        drafts = "/api/editorial/drafts"
        created = self.private.post(drafts, headers=self.headers(), json=dict(command_id=str(uuid4()), expected_revision=0,
            story_id=self.story_id, target_locale="sr-Latn", payload=payload)).json()
        def transition(state, action, role):
            response = self.private.post(f"{drafts}/{created['draft_id']}/{action}", headers=self.headers(role),
                json={"command_id": str(uuid4()), "expected_revision": state["revision"],
                    "version_number": state["version_number"], "content_hash": state["content_hash"]})
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()
        submitted = transition(created, "submit", "editor")
        transition(submitted, "approve", "reviewer")
        before = self.private.get(drafts + "/" + created["draft_id"], headers=self.headers("reader")).json()
        stories_before = self.client.get("/api/stories").json()
        suggestion = self.create()
        self.private.post(f"{BASE}/{suggestion['id']}/reject", headers=self.headers(),
            json=dict(command_id=str(uuid4()), expected_revision=2, reason="Demonstracioni predlog."))
        self.assertEqual(self.private.get(drafts + "/" + created["draft_id"], headers=self.headers("reader")).json(), before)
        self.assertTrue(before["effective_approval"])
        self.assertEqual((self.count(EditorialDraft), self.count(EditorialDraftVersion), self.count(EditorialEvent)), (1, 1, 3))
        self.assertEqual(self.client.get("/api/stories").json(), stories_before)
        for public in ("/api/stories", "/api/editorial-queue", "/api/editorial-stories/" + self.story_id):
            self.assertNotIn(suggestion["id"], self.client.get(public).text)


    def _recovery_reservation(self, expired=False):
        processor = AIProcessing(self.private_app.state.news_repository,
            EditorialPrincipal("urn:hnh:test", "test-editor", frozenset({EditorialRole.EDITOR})), self.provider)
        body = self.creation()
        class CaptureClock:
            @staticmethod
            def now(tz): return datetime.now(tz) - timedelta(minutes=1 if expired else 0)
        with patch("app.services.ai_processing.datetime", CaptureClock):
            reserved, _ = processor.reserve(CreateSuggestion(**body))
        return body, str(reserved.id)

    def test_persisted_command_recovery_survives_restart_without_current_source_or_provider(self):
        body, identity = self._recovery_reservation()
        detail = self.private.get(BASE+"/"+identity, headers=self.headers()).json()
        self.assertEqual(detail["recovery_command"],body)
        frozen = detail["input"]
        self.collect([source(posts=[post(title="Refreshed title",content="New source content")])])
        restarted = create_app(self.runtime_config, editorial_identity_verifier=TestIdentityVerifier())
        restarted.state.ai_provider = None
        restarted.state.news_repository.config = self.runtime_config.model_copy(update={"ai_daily_generation_limit":0})
        try:
            with TestClient(restarted) as client:
                for _ in range(2):
                    response = client.post(BASE+"/"+identity+"/recover",json=detail["recovery_command"],headers=self.headers())
                    self.assertEqual(response.status_code,202,response.text)
                    self.assertEqual(response.json()["input"],frozen)
                    self.assertEqual(response.json()["recovery_command"],body)
        finally: restarted.state.news_repository.engine.dispose()
        self.assertEqual((self.count(AIProcessingRun),self.count(AIProcessingEvent)),(1,1))
        self.assertEqual(self.provider.calls,[])

    def test_concurrent_expired_recovery_seals_one_interruption_after_restart(self):
        body, identity = self._recovery_reservation(expired=True)
        restarted = create_app(self.runtime_config, editorial_identity_verifier=TestIdentityVerifier())
        try:
            with TestClient(restarted) as client, ThreadPoolExecutor(max_workers=2) as pool:
                def recover(target): return target.post(BASE+"/"+identity+"/recover",json=body,headers=self.headers())
                first,second = list(pool.map(recover,[self.private,client]))
                self.assertEqual((first.status_code,second.status_code),(200,200))
                self.assertEqual(first.json(),second.json())
                self.assertEqual((first.json()["status"],first.json()["error_code"]),("interrupted","process_interrupted"))
        finally: restarted.state.news_repository.engine.dispose()
        self.assertEqual((self.count(AIProcessingRun),self.count(AIProcessingEvent)),(1,2))
        self.assertEqual(self.provider.calls,[])

    def test_strict_recovery_missing_mismatched_and_unauthorized_never_reserves(self):
        response = self.private.post(BASE+"/"+str(uuid4())+"/recover",json=self.creation(),headers=self.headers())
        self.assertEqual(response.status_code,404)
        self.assertEqual(self.count(AIProcessingRun),0)
        body,identity = self._recovery_reservation()
        for path,command,expected in ((str(uuid4()),body,409), (identity,body|{"command_id":str(uuid4())},404),
                                     (identity,body|{"article_id":str(uuid4())},409)):
            response=self.private.post(BASE+"/"+path+"/recover",json=command,headers=self.headers())
            self.assertEqual(response.status_code,expected,response.text)
        self.private_app.state.editorial_identity_verifier.identities["fixture-other-editor"] = EditorialPrincipal(
            "urn:hnh:test", "other-editor", frozenset({EditorialRole.EDITOR}))
        for headers,expected in (({},401),(self.headers("reader"),403),(self.headers("administrator"),409),
                                 ({"Authorization":"Bearer fixture-other-editor"},409)):
            response=self.private.post(BASE+"/"+identity+"/recover",json=body,headers=headers)
            self.assertEqual(response.status_code,expected,response.text)
        self.assertIsNone(self.private.get(BASE+"/"+identity,headers=self.headers("reader")).json()["recovery_command"])
        self.assertIsNone(self.private.get(BASE+"/"+identity,headers=self.headers("administrator")).json()["recovery_command"])
        self.assertEqual((self.count(AIProcessingRun),self.count(AIProcessingEvent)),(1,1))
        self.assertEqual(self.provider.calls,[])

    def test_lost_completed_response_recovered_without_creating_a_second_version_or_run(self):
        body=self.creation(); first=self.create(body)
        response=self.private.post(BASE+"/"+first["id"]+"/recover",json=body,headers=self.headers())
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),first)
        self.assertEqual((len(self.provider.calls),self.count(AIProcessingRun),self.count(AIProcessingEvent)),(1,1,2))
        self.assertEqual((self.count(EditorialDraft),self.count(EditorialDraftVersion)),(0,0))


class AISuggestionMigrationTests(PersistentCollectionCase):
    def tearDown(self):
        with self.engine.begin() as connection:
            connection.execute(text("TRUNCATE public.ai_processing_events, public.ai_processing_runs, public.editorial_events, "
                "public.editorial_decisions, public.editorial_version_sources, public.editorial_draft_versions, public.editorial_drafts"))
        super().tearDown()

    def test_populated_17a_upgrade_downgrade_and_reupgrade_preserves_collection_and_editorial(self):
        self.collect([source(posts=[post()])])
        with self.factory() as session:
            article = session.scalar(select(CollectedArticle))
            article_id, source_id = str(article.id), str(article.source_id)
        story_id = self.client.get("/api/stories").json()["stories"][0]["id"]
        private_app = create_app(self.runtime_config, editorial_identity_verifier=TestIdentityVerifier(), ai_provider=MockSuggestionProvider())
        headers = {"Authorization": "Bearer fixture-editor"}
        try:
            with TestClient(private_app) as client:
                payload = dict(headline="Sačuvani naslov", body="Sačuvani urednički tekst.", excerpt="Opis.", slug="sacuvani-naslov",
                    categories=["Region"], tags=[], seo={"title": "Naslov", "description": "Opis"}, images=[],
                    source_attribution=[{"article_id": article_id, "source_id": source_id}])
                response = client.post("/api/editorial/drafts", headers=headers, json=dict(command_id=str(uuid4()),
                    expected_revision=0, story_id=story_id, target_locale="sr-Latn", payload=payload))
                self.assertEqual(response.status_code, 201, response.text)
                created = response.json()
                for action in ("submit", "approve"):
                    response = client.post(f"/api/editorial/drafts/{created['draft_id']}/{action}",
                        headers={"Authorization": "Bearer fixture-reviewer"} if action == "approve" else headers,
                        json=dict(command_id=str(uuid4()), expected_revision=created["revision"],
                            version_number=created["version_number"], content_hash=created["content_hash"]))
                    self.assertEqual(response.status_code, 200, response.text)
                    created = response.json()
                response = client.post(BASE, headers=headers, json=dict(command_id=str(uuid4()), story_id=story_id,
                    article_id=article_id, source_id=source_id))
                self.assertEqual(response.status_code, 201, response.text)
        finally:
            private_app.state.news_repository.engine.dispose()
        names = ("news_sources", "collected_articles", "stories", "story_articles", "editorial_drafts",
                 "editorial_draft_versions", "editorial_version_sources", "editorial_decisions", "editorial_events")
        def snapshot(connection):
            return {name: connection.scalar(text(f"SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text) FROM public.{name} t")) for name in names}
        with self.engine.begin() as connection:
            config = alembic_config(connection)
            before = snapshot(connection)
            alembic_command.downgrade(config, "20261030_03")
            self.assertEqual(snapshot(connection), before)
            alembic_command.upgrade(config, "20261101_06")
            self.assertEqual(snapshot(connection), before)
            self.assertEqual(connection.scalar(text("SELECT count(*) FROM public.ai_processing_runs")), 0)
            alembic_command.check(config)
        provision_runtime_role(Settings(_env_file=None), self.role, self.runtime_config.postgres_password.get_secret_value())
