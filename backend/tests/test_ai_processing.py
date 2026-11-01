import asyncio
from datetime import datetime, timezone
import hashlib
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.schemas.ai_processing import AcceptSuggestion, CreateSuggestion, FrozenSource, GenerationRequest, MOCK_WARNING, RejectSuggestion
from app.services.ai_provider import MockSuggestionProvider
from editorial_identity import TestIdentityVerifier

BASE = "/api/editorial/ai/suggestions"


class AIProcessingTests(unittest.TestCase):
    def test_mock_is_deterministic_and_explicitly_not_translation(self):
        original = "Изворни текст.\r\n\nČćšžđ — original text."
        request = GenerationRequest(request_id=uuid4(), story_id=uuid4(), source=FrozenSource(
            article_id=uuid4(), source_id=uuid4(), source_name="Portal", source_url="https://source.invalid",
            external_id="123", original_url="https://source.invalid/post", canonical_url=None,
            language="sr-Cyrl", published_at=None, title=original, excerpt="", content=None,
            input_text=original, input_text_hash=hashlib.sha256(original.encode()).hexdigest(),
            captured_at=datetime.now(timezone.utc)))
        provider = MockSuggestionProvider()
        first = asyncio.run(provider.generate(request))
        self.assertEqual(first, asyncio.run(provider.generate(request)))
        self.assertTrue(first.provenance.is_mock)
        self.assertIn(MOCK_WARNING, first.warnings)
        self.assertEqual(first.source_references[0].excerpt, original)
        self.assertIn("nije prevod", first.headline)
        with self.assertRaises(ValidationError):
            request.source.input_text = "changed"

    def test_only_mock_opt_in_is_available_and_defaults_are_disabled(self):
        config = Settings(_env_file=None)
        self.assertEqual(config.ai_processing_provider, "disabled")
        self.assertIsNone(create_app(config).state.ai_provider)
        self.assertIsInstance(create_app(config.model_copy(update={"ai_processing_provider": "mock"})).state.ai_provider,
                              MockSuggestionProvider)
        for value in ("openai", "unknown"):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None, ai_processing_provider=value)
        for value in (0, 31, float("nan"), float("inf")):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None, ai_processing_timeout_seconds=value)

    def test_unconfigured_identity_and_memory_mode_fail_closed_public_routes_work(self):
        body = dict(command_id=str(uuid4()), story_id=str(uuid4()), article_id=str(uuid4()), source_id=str(uuid4()))
        for verifier in (None, TestIdentityVerifier()):
            app = create_app(Settings(_env_file=None, ai_processing_provider="mock"), editorial_identity_verifier=verifier)
            with TestClient(app) as client:
                self.assertEqual(client.post(BASE, json=body).status_code, 401)
                self.assertEqual(client.post(BASE, json=body, headers={"Authorization": "Bearer fixture-editor"}).status_code, 503)
                self.assertEqual(client.get(BASE, params={"story_id": body["story_id"]},
                    headers={"Authorization": "Bearer fixture-reader"}).status_code, 503)
                for public in ("/", "/api/stories", "/api/editorial-queue"):
                    self.assertEqual(client.get(public).status_code, 200)

    def test_command_schema_rejects_client_roles_extra_sources_and_unsupported_modes(self):
        base = dict(command_id=uuid4(), story_id=uuid4(), article_id=uuid4(), source_id=uuid4())
        for change in ({"actor_subject": "admin"}, {"roles": ["administrator"]}, {"mode": "synthesis"},
                       {"target_locale": "en"}, {"sources": []}):
            with self.assertRaises(ValidationError):
                CreateSuggestion(**(base | change))
        for revision in (0, True, "2"):
            with self.assertRaises(ValidationError):
                RejectSuggestion(command_id=uuid4(), expected_revision=revision, reason="Razlog")

    def test_ai_routes_share_safe_json_body_boundary(self):
        with TestClient(create_app(Settings(_env_file=None))) as client:
            cases = [(b'{"headline": NaN}', "application/json", 400),
                     (b'{"headline":"\\ud800"}', "application/json", 400),
                     (b'\xff', "application/octet-stream", 415),
                     (b'\xff', "application/json", 400),
                     (b'{}', 'application/json; charset=latin-1', 415),
                     (b'x' * (1024 * 1024 + 1), 'application/json', 413)]
            for path in (BASE, BASE + "/" + str(uuid4()) + "/reject", BASE + "/" + str(uuid4()) + "/accept"):
                for content, media, status in cases:
                    response = client.post(path, content=content, headers={"Content-Type": media})
                    self.assertEqual(response.status_code, status, response.text)
                    self.assertEqual(response.headers["cache-control"], "no-store")
                    self.assertNotIn("Traceback", response.text)

    def test_openapi_is_private_bounded_and_acceptance_uses_existing_receipt(self):
        schema = create_app(Settings(_env_file=None)).openapi()
        for path, operations in schema["paths"].items():
            if not path.startswith(BASE):
                continue
            for contract in operations.values():
                self.assertEqual(contract["security"], [{"EditorialBearer": []}])
        summary = schema["components"]["schemas"]["SuggestionSummary"]["properties"]
        self.assertFalse({"input", "output", "events"} & summary.keys())
        parameters = {p["name"]: p["schema"] for p in schema["paths"][BASE]["get"]["parameters"]}
        self.assertEqual((parameters["limit"]["default"], parameters["limit"]["maximum"]), (20, 50))
        contract = schema["paths"][BASE + "/{suggestion_id}/accept"]["post"]
        self.assertEqual(contract["responses"]["200"]["content"]["application/json"]["schema"]["$ref"], "#/components/schemas/CommandResult")
        fields = schema["components"]["schemas"]["AcceptSuggestion"]
        self.assertEqual(set(fields["required"]), {"command_id", "story_id", "expected_revision", "payload", "confirm_acceptance"})
        self.assertIs(fields["properties"]["confirm_acceptance"]["const"], True)

    def test_acceptance_requires_verified_identity_and_postgresql_even_when_mock_enabled(self):
        article_id, source_id = uuid4(), uuid4()
        payload = dict(headline="Potvrđen naslov", body="Potvrđen tekst.", excerpt="Kratak opis.", slug="potvrdjen-naslov",
            categories=["Region"], tags=[], seo={"title":"Naslov", "description":"Opis"}, images=[],
            source_attribution=[{"article_id":str(article_id), "source_id":str(source_id)}])
        body = dict(command_id=str(uuid4()), story_id=str(uuid4()), expected_revision=0, payload=payload, confirm_acceptance=True)
        for verifier in (None, TestIdentityVerifier()):
            app = create_app(Settings(_env_file=None, ai_processing_provider="mock"), editorial_identity_verifier=verifier)
            with TestClient(app) as client:
                path = BASE + "/" + str(uuid4()) + "/accept"
                self.assertEqual(client.post(path, json=body).status_code, 401)
                self.assertEqual(client.post(path, json=body, headers={"Authorization":"Bearer fixture-editor"}).status_code, 503)
                self.assertEqual(client.get("/api/stories").status_code, 200)
