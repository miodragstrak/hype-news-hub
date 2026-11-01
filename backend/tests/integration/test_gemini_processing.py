"""Real PostgreSQL persistence and editorial isolation; Gemini HTTP is always mocked."""
import asyncio
import json
from unittest.mock import patch
from uuid import UUID, uuid4

from alembic import command
from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.main import create_app
from app.models import AIProcessingRun, CollectedArticle, EditorialDraft, EditorialDraftVersion, EditorialDecision, EditorialEvent
from app.schemas.ai_processing import CreateSuggestion, FrozenSource, GenerationRequest
from app.services.ai_provider import MockSuggestionProvider
from app.services.ai_processing import AIProcessing
from app.core.editorial_security import EditorialPrincipal, EditorialRole
from app.services.gemini_provider import GeminiProvider
from editorial_identity import TestIdentityVerifier
from gemini_fixtures import ScriptedHTTP, TEST_KEY, TEST_MODEL, request, envelope, suggestion
from integration.test_ai_processing import AIProcessingCase, BASE
from tests.integration.test_postgresql import alembic_config


class GeminiProcessingTests(AIProcessingCase):
    def setUp(self):
        super().setUp()
        with self.factory.begin() as session:
            session.get(CollectedArticle,UUID(self.article_id)).content=request().source.content
        self.http=ScriptedHTTP(request())
        def transport(call):
            if call.url.path.endswith(":generateContent"):
                sent=json.loads(json.loads(call.content)["contents"][0]["parts"][0]["text"])
                self.http.req=GenerationRequest(request_id=uuid4(),story_id=UUID(self.story_id),source=FrozenSource(**sent["source"]))
            return self.http(call)
        self.gemini_config=self.runtime_config.model_copy(update={"ai_processing_provider":"gemini", "gemini_model":TEST_MODEL,
            "gemini_api_key":SecretStr(TEST_KEY),"ai_processing_timeout_seconds":2})
        self.gemini=GeminiProvider(self.gemini_config,transport=httpx.MockTransport(transport))
        self.private_app.state.ai_provider=self.gemini
        self.private_app.state.news_repository.config=self.gemini_config

    def publishing_payload(self):
        return dict(headline="Urednički potvrđen naslov",body="Potvrđen tekst na srpskom.",excerpt="Kratak opis.",
            slug="potvrdjen-naslov",categories=["Kultura"],tags=[],seo={"title":"Naslov","description":"Opis"},images=[],
            source_attribution=[{"article_id":self.article_id,"source_id":self.source_id}])

    def accept(self, result, revision=0):
        response=self.private.post(BASE+"/"+result["id"]+"/accept",headers=self.headers(),json=dict(command_id=str(uuid4()),
            story_id=self.story_id,expected_revision=revision,payload=self.publishing_payload(),confirm_acceptance=True))
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_real_provider_provenance_and_frozen_wire_input_usage_survive_restart(self):
        body=self.creation()
        result=self.create(body)
        self.assertEqual((result["status"],result["provenance"]["provider"],result["provenance"]["is_mock"]),("succeeded","gemini",False))
        self.assertEqual(result["processing_metadata"]["usage"]["total_tokens"],200)
        self.assertEqual(result["processing_metadata"]["reported_model_version"],"gemini-fixture-version-001")
        self.assertIsNone(result["processing_metadata"]["estimated_cost"])
        wire=json.loads(self.http.calls[-1].content)
        self.assertEqual(wire["systemInstruction"]["parts"][0]["text"],result["input"]["instructions"])
        self.assertEqual(json.loads(wire["contents"][0]["parts"][0]["text"])["source"],result["input"]["source"])
        self.assertEqual(wire["generationConfig"]["responseJsonSchema"],json.loads(result["input"]["response_schema"]))
        self.assertEqual(self.count(EditorialDraft),0)
        restarted=create_app(self.runtime_config,editorial_identity_verifier=TestIdentityVerifier())
        try:
            with TestClient(restarted) as other:
                self.assertEqual(self.read(result["id"],other),result)
                self.assertEqual(self.create(body,other,expected=200),result)
        finally:restarted.state.news_repository.engine.dispose()
        self.assertEqual(len(self.http.calls),3)
        self.assertNotIn(TEST_KEY,json.dumps(result))

    def test_invalid_references_preserve_usage_but_never_become_suggestions(self):
        for field,value in (("article_id",str(uuid4())),("input_text_hash","0"*64),("excerpt","Invented quotation absent from frozen input")):
            def wrong(call):
                data=suggestion(self.http.req)
                data["source_references"][0][field]=value
                response=envelope(self.http.req)
                response["candidates"][0]["content"]["parts"][0]["text"]=json.dumps(data)
                return httpx.Response(200,json=response)
            self.http.generate=wrong
            result=self.create()
            self.assertEqual((result["status"],result["error_code"],result["output"]),("failed","invalid_provider_output",None))
            self.assertEqual(result["processing_metadata"]["usage"]["total_tokens"],200)
        self.assertEqual(self.count(EditorialDraftVersion),0)

    def test_provider_errors_are_classified_sanitized_and_do_not_fall_back(self):
        for status, code in ((403,"provider_auth"),(429,"provider_throttled"),(503,"provider_unavailable")):
            self.http.generate=lambda call:httpx.Response(status,json={"error":{"message":"sensitive "+TEST_KEY}},headers={"Retry-After":"0"})
            body=self.creation()
            result=self.create(body)
            self.assertEqual((result["status"],result["error_code"],result["output"]),("failed",code,None))
            self.assertFalse(result["provenance"]["is_mock"])
            self.assertNotIn(TEST_KEY,json.dumps(result))
            count=len(self.http.calls)
            self.assertEqual(self.create(body,expected=200),result)
            self.assertEqual(len(self.http.calls),count)

    def test_missing_key_is_unavailable_without_persisting_request_or_breaking_public_routes(self):
        self.private_app.state.ai_provider=GeminiProvider(self.gemini_config.model_copy(update={"gemini_api_key":SecretStr("")}),
            transport=httpx.MockTransport(self.http))
        self.create(expected=503)
        self.assertEqual(self.count(AIProcessingRun),0)
        self.assertEqual(self.http.calls,[])
        self.assertEqual(self.private.get("/api/stories").status_code,200)

    def test_generated_urls_cannot_introduce_unfrozen_citations(self):
        for url,expected in (("https://invented.invalid/news","failed"),
            ("HTTPS://invented.invalid/news","failed"),("Http://invented.invalid/news","failed"),
            ("hTTpS://invented.invalid/news","failed"),("https://source.invalid/item","succeeded")):
            def generate(call):
                data=envelope(self.http.req)
                wire=suggestion(self.http.req)
                wire["body"] += " Izvor: "+url
                data["candidates"][0]["content"]["parts"][0]["text"]=json.dumps(wire)
                return httpx.Response(200,json=data)
            self.http.generate=generate
            result=self.create()
            self.assertEqual(result["status"],expected)
            self.assertEqual(result["processing_metadata"]["usage"]["total_tokens"],200)

    def test_frozen_url_citations_preserve_case_and_opaque_bytes(self):
        frozen_urls = [scheme + "://source.invalid/CasePath?opaque=%FF&Label=AbC#Section"
            for scheme in ("https", "HTTPS", "Http", "hTTpS")]
        with self.factory.begin() as session:
            article = session.get(CollectedArticle, UUID(self.article_id))
            article.content += "\n" + "\n".join(frozen_urls)
        changed_urls = [frozen_urls[0].replace("CasePath", "casepath"),
            frozen_urls[0].replace("%FF", "%ff"), frozen_urls[0].replace("AbC", "abc"),
            frozen_urls[0].replace("#Section", "#section")]
        for url in frozen_urls + changed_urls:
            def generate(call):
                data = envelope(self.http.req)
                wire = suggestion(self.http.req)
                wire["body"] += " Izvor: " + url
                data["candidates"][0]["content"]["parts"][0]["text"] = json.dumps(wire)
                return httpx.Response(200, json=data)
            self.http.generate = generate
            result = self.create()
            self.assertEqual(result["status"], "succeeded" if url in frozen_urls else "failed")
            if result["output"]:
                self.assertTrue(result["output"]["body"].endswith(url))
            else:
                self.assertEqual(result["error_code"], "invalid_provider_output")

    def test_refusal_keeps_available_usage_and_creates_no_editorial_state(self):
        self.http.generate=lambda call:httpx.Response(200,json=envelope(self.http.req,candidates=[],promptFeedback={"blockReason":"SAFETY"}))
        result=self.create()
        self.assertEqual((result["status"],result["error_code"]),("failed","provider_refused"))
        self.assertEqual(result["processing_metadata"]["usage"]["total_tokens"],200)
        self.assertEqual((self.count(EditorialDraft),self.count(EditorialEvent)),(0,0))

    def test_ambiguous_timeout_is_not_retried_and_cost_stays_unknown(self):
        def timeout(call):raise httpx.ReadTimeout("sensitive timeout",request=call)
        self.http.generate=timeout
        body=self.creation()
        result=self.create(body)
        self.assertEqual((result["status"],result["error_code"]),("failed","provider_timeout"))
        self.assertEqual(result["processing_metadata"]["generation_outcome"],"unknown")
        self.assertIsNone(result["processing_metadata"]["usage"])
        self.assertIsNone(result["processing_metadata"]["estimated_cost"])
        self.create(body,expected=200)
        self.assertEqual(len(self.http.calls),3)

    def test_service_and_adapter_deadlines_preserve_counted_metadata_and_recovery(self):
        # Expire a chosen deadline only after deterministic preflight/counting.
        # No sleeps or upstream timing decide which cancellation path is tested.
        real_timeout = asyncio.timeout
        for owner in ("service", "adapter"):
            deadlines, calls = [], []

            def capture_timeout(delay):
                context = real_timeout(delay)
                deadlines.append(context)
                return context

            async def transport(call):
                calls.append(call)
                if call.url.path.endswith(":generateContent"):
                    self.assertEqual(len(deadlines), 2)
                    deadlines[0 if owner == "service" else 1].reschedule(asyncio.get_running_loop().time())
                    await asyncio.Future()
                return self.http(call)

            provider = GeminiProvider(self.gemini_config, transport=httpx.MockTransport(transport))
            principal = EditorialPrincipal("urn:hnh:test", "test-editor", frozenset({EditorialRole.EDITOR}))
            processor = AIProcessing(self.private_app.state.news_repository, principal, provider)
            body = self.creation()
            with patch("app.services.ai_processing.asyncio.timeout", side_effect=capture_timeout):
                result, created = asyncio.run(processor.generate(CreateSuggestion(**body)))
            self.assertTrue(created)
            self.assertEqual((result.status, result.error_code), ("failed", "provider_timeout"))
            metadata = result.processing_metadata
            self.assertEqual(metadata.counted_input_tokens, 123)
            self.assertEqual(metadata.model_metadata_version, "001")
            self.assertEqual((metadata.http_attempts, metadata.generation_attempts), (3, 1))
            self.assertEqual(metadata.generation_outcome, "unknown")
            self.assertIsNone(metadata.usage)
            self.assertIsNone(metadata.estimated_cost)
            self.assertEqual(metadata.cost_status, "unknown")
            self.assertEqual(len(calls), 3)
            # A fresh app with processing disabled recovers the sealed receipt.
            restarted = create_app(self.runtime_config, editorial_identity_verifier=TestIdentityVerifier())
            try:
                with TestClient(restarted) as client:
                    saved = self.read(str(result.id), client)
                    self.assertEqual(saved["processing_metadata"], metadata.model_dump(mode="json"))
                    self.assertEqual(self.create(body, client, expected=200), saved)
            finally:
                restarted.state.news_repository.engine.dispose()
            self.assertEqual(len(calls), 3)

    def test_cancelled_generation_seals_known_metadata_and_replays_without_dispatch(self):
        dispatched, calls = None, []

        async def transport(call):
            calls.append(call)
            if call.url.path.endswith(":generateContent"):
                dispatched.set()
                await asyncio.Future()
            return self.http(call)

        provider = GeminiProvider(self.gemini_config, transport=httpx.MockTransport(transport))
        principal = EditorialPrincipal("urn:hnh:test", "test-editor", frozenset({EditorialRole.EDITOR}))
        processor = AIProcessing(self.private_app.state.news_repository, principal, provider)
        body = self.creation()

        async def cancel_after_dispatch():
            nonlocal dispatched
            dispatched = asyncio.Event()
            task = asyncio.create_task(processor.generate(CreateSuggestion(**body)))
            await dispatched.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        asyncio.run(cancel_after_dispatch())
        with self.factory() as session:
            run = session.scalar(select(AIProcessingRun))
            identity = str(run.id)
        result = self.read(identity)
        self.assertEqual((result["status"], result["error_code"]), ("interrupted", "process_interrupted"))
        metadata = result["processing_metadata"]
        self.assertEqual(metadata["counted_input_tokens"], 123)
        self.assertEqual(metadata["model_metadata_version"], "001")
        self.assertEqual((metadata["http_attempts"], metadata["generation_attempts"]), (3, 1))
        self.assertEqual(metadata["generation_outcome"], "unknown")
        self.assertIsNone(metadata["usage"])
        self.assertIsNone(metadata["estimated_cost"])
        self.assertEqual(metadata["cost_status"], "unknown")
        self.assertEqual(self.create(body, expected=200), result)
        self.assertEqual(len(calls), 3)
        self.assertEqual([event["action"] for event in result["events"]],
            ["generation.requested", "generation.interrupted"])

    def test_acceptance_preserves_accounting_and_never_approves_or_refreshes_evidence(self):
        result=self.create()
        accepted=self.accept(result)
        row=self.private.get("/api/editorial/drafts/"+accepted["draft_id"],headers=self.headers("reader")).json()
        self.assertFalse(row["effective_approval"])
        with self.factory() as session:
            event=session.scalar(select(EditorialEvent))
            self.assertEqual(event.details["ai_provenance"]["processing_metadata"],result["processing_metadata"])
        current=accepted
        for action,role in (("submit","editor"),("approve","reviewer")):
            response=self.private.post("/api/editorial/drafts/"+current["draft_id"]+"/"+action,headers=self.headers(role),
                json=dict(command_id=str(uuid4()),expected_revision=current["revision"],version_number=current["version_number"],content_hash=current["content_hash"]))
            self.assertEqual(response.status_code,200,response.text)
            current=response.json()
        before=self.private.get("/api/editorial/drafts/"+current["draft_id"],headers=self.headers("reader")).json()
        self.assertTrue(before["effective_approval"])
        second=self.create()
        self.assertEqual(self.private.get("/api/editorial/drafts/"+current["draft_id"],headers=self.headers("reader")).json(),before)
        next_receipt=self.accept(second,current["revision"])
        self.assertFalse(self.private.get("/api/editorial/drafts/"+next_receipt["draft_id"],headers=self.headers("reader")).json()["effective_approval"])
        self.assertEqual(self.count(EditorialDecision),1)
        self.assertEqual(self.read(result["id"])["processing_metadata"],result["processing_metadata"])

    def test_accounting_is_immutable_and_downgrade_refuses_gemini_history(self):
        result=self.create()
        with self.assertRaises(SQLAlchemyError),self.private_app.state.news_repository.engine.begin() as conn:
            conn.execute(text("UPDATE public.ai_processing_runs SET status='rejected',revision=3,rejected_at=clock_timestamp(),processing_metadata='{}'::jsonb"))
        with self.assertRaises(SQLAlchemyError),self.engine.begin() as conn:
            command.downgrade(alembic_config(conn),"20261101_05")
        self.assertEqual(self.read(result["id"]),result)
        with self.engine.connect() as conn:self.assertEqual(conn.scalar(text("SELECT version_num FROM public.alembic_version")),"20261101_06")

    def test_populated_legacy_mock_upgrade_retains_hashes_and_payload_shapes(self):
        self.private_app.state.ai_provider=MockSuggestionProvider()
        result=self.create()
        self.assertEqual(set(result["input"]),{"request_id","story_id","mode","target_locale","prompt_version","source"})
        with self.engine.begin() as conn:
            config=alembic_config(conn)
            command.downgrade(config,"20261101_05")
            old=conn.execute(text("SELECT input_payload::text,input_hash,output::text,output_hash FROM public.ai_processing_runs")).one()
            command.upgrade(config,"head")
            new=conn.execute(text("SELECT input_payload::text,input_hash,output::text,output_hash FROM public.ai_processing_runs")).one()
            self.assertEqual(old,new)
            command.check(config)
        self.assertEqual(self.read(result["id"]),result)
