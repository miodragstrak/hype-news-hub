from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, patch, sentinel
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.schemas.editorial_commands import PublishingPayload
from editorial_identity import TestIdentityVerifier


class EditorialPayloadTests(unittest.TestCase):
    def setUp(self):
        self.article, self.source = str(uuid4()), str(uuid4())
        self.payload = dict(headline="Naslov čćšžđ", body="Prvi pasus.\n\nDrugi pasus.", excerpt="Kratak opis.",
            slug="naslov-clanka", categories=["Zabava"], tags=[], seo={"title":"Naslov", "description":"Opis"}, images=[],
            source_attribution=[{"article_id":self.article,"source_id":self.source}])

    def test_complete_latin_plain_text_payload_and_image_attribution(self):
        self.payload["images"]=[{"url":"https://media.example/photo.jpg", "alt":"Fotografija događaja", "credit":"Foto: Izvor", "source_article_id":self.article}]
        self.assertEqual(PublishingPayload.model_validate(self.payload).headline,"Naslov čćšžđ")

    def test_every_publishing_field_is_required(self):
        for name in self.payload:
            payload=deepcopy(self.payload)
            del payload[name]
            with self.subTest(field=name),self.assertRaises(ValidationError):
                PublishingPayload.model_validate(payload)

    def test_unsafe_or_incomplete_content_is_rejected(self):
        for fields in [{"headline":" "},{"body":"<script>alert(1)</script>"},{"body":"<img src=x onerror=alert(1)>"},
            {"body":"&#x3c;script&#x3e;"}, {"excerpt":"Ћирилица"}, {"body":"nul\x00byte"}, {"body":"x"*100001},
            {"slug":"bad/slug"},{"slug":"Јavascript"},{"categories":[]},{"categories":["Zabava","zabava"]},
            {"tags":["Music","music"]},{"source_attribution":[]},{"source_attribution":[{"external_id":"123"}]},
            {"actor_id":"administrator"}]:
            # Encoded text is ordinary plain text; it must never be decoded into HTML.
            if fields.get("body")=="&#x3c;script&#x3e;":
                self.assertEqual(PublishingPayload.model_validate(self.payload|fields).body,fields["body"])
                continue
            with self.subTest(fields=list(fields)),self.assertRaises(ValidationError):
                PublishingPayload.model_validate(self.payload|fields)

    def test_image_schemes_credentials_and_cross_article_references_are_rejected(self):
        image={"url":"https://media.example/p.jpg","alt":"Foto","credit":"Izvor","source_article_id":self.article}
        for changes in [{"url":"javascript:alert(1)"},{"url":"file:///etc/passwd"},{"url":"https://u:p@example.com/image"},
            {"url":"http://127.0.0.1/x"},{"url":"https://localhost/x"},{"url":"http://[::1]/x"},
            {"source_article_id":str(uuid4())},{"credit":" "}]:
            with self.subTest(changes=changes),self.assertRaises(ValidationError):
                PublishingPayload.model_validate(self.payload|{"images":[image|changes]})

    def test_duplicate_source_uuid_is_rejected(self):
        with self.assertRaises(ValidationError):
            PublishingPayload.model_validate(self.payload|{"source_attribution":self.payload["source_attribution"]*2})


class EditorialCommandBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.application=create_app(Settings(_env_file=None),editorial_identity_verifier=TestIdentityVerifier())
        self.client=TestClient(self.application)
        self.addCleanup(self.client.close)
        self.identifier=str(uuid4())

    def test_every_private_route_is_authenticated_and_memory_mode_fails_closed(self):
        paths=self.application.openapi()["paths"]
        for path,operations in paths.items():
            if not path.startswith(("/api/editorial/drafts", "/api/editorial/stories/")):
                continue
            url=path.replace("{draft_id}",self.identifier).replace("{story_id}",self.identifier).replace("{version_number}","1")
            if path=="/api/editorial/drafts":
                url+="?story_id="+self.identifier
            for method in operations:
                for headers,expected in [({},401),({"Authorization":"Bearer fixture-administrator"},503)]:
                    response=self.client.request(method,url,json={},headers=headers)
                    with self.subTest(path=path,method=method,expected=expected):
                        self.assertEqual(response.status_code,expected,response.text)
                        self.assertNotIn("password",response.text.lower())
        self.assertEqual(self.client.get("/api/stories").status_code,200)

    def test_default_verifier_never_authorizes_commands_with_test_token(self):
        app=create_app(Settings(_env_file=None,app_env="production"))
        with TestClient(app) as client:
            response=client.post("/api/editorial/drafts",json={},headers={"Authorization":"Bearer fixture-administrator"})
            self.assertEqual(response.status_code,503)

    def test_oversized_command_is_rejected_before_parsing_with_cors_and_no_store(self):
        response=self.client.post("/api/editorial/drafts",content=b"x"*(1024*1024+1),
            headers={"Content-Type":"application/json","Origin":"http://localhost:5173"})
        self.assertEqual(response.status_code,413,response.text)
        self.assertEqual(response.headers["cache-control"],"no-store")
        self.assertEqual(response.headers["access-control-allow-origin"],"http://localhost:5173")

    def test_streamed_commands_cannot_bypass_body_limit(self):
        def body():
            for _ in range(17):
                yield b"x"*65536
        response=self.client.post("/api/editorial/drafts",content=body(),headers={"Content-Type":"application/json"})
        self.assertEqual(response.status_code,413)

    def test_strict_json_rejections_are_safe_before_database_access(self):
        cases=[(b'{"headline": NaN}',400),(b'{"value": Infinity}',400),
            (b'{"value": -Infinity}',400),(b'{"value":1e400}',400),
            (b'{"value":"\\ud800"}',400),(b'{"\\udfff":"key"}',400),
            (b'\xff',400),(b'\xe2\x82',400),(b'{',400),(b'',400),
            (b'['*2000+b'0'+b']'*2000,400)]
        with patch("app.api.editorial_security.get_editorial_database") as database:
            for content,status in cases:
                with self.subTest(content=repr(content[:30])):
                    response=self.client.post("/api/editorial/drafts",content=content,
                        headers={"Content-Type":"application/json","Authorization":"Bearer fixture-editor", "Origin":"http://localhost:5173"})
                    self.assertEqual(response.status_code,status,response.text)
                    self.assertEqual(response.json(),{"detail":"Malformed editorial JSON: use valid UTF-8 and finite numbers."})
                    self.assertEqual(response.headers["cache-control"],"no-store")
                    self.assertEqual(response.headers["access-control-allow-origin"],"http://localhost:5173")
            database.assert_not_called()

    def test_unsupported_media_types_and_charsets_return_415(self):
        for content_type in ("application/octet-stream","text/plain","application/xml", "application/json; charset=utf-16", 'application/json; charset = "latin-1"'):
            with self.subTest(content_type=content_type):
                response=self.client.post("/api/editorial/drafts",content=b'\xff',headers={"Content-Type":content_type})
                self.assertEqual(response.status_code,415,response.text)
                self.assertEqual(response.json(),{"detail":"Editorial commands require UTF-8 JSON content."})
                self.assertEqual(response.headers["cache-control"],"no-store")

    def test_private_field_errors_never_reflect_input_or_exception_context(self):
        with patch("app.api.editorial_security.get_editorial_database",return_value=sentinel.repository):
            response=self.client.post("/api/editorial/drafts",json={"private-token":"sensitive-input"},
                headers={"Authorization":"Bearer fixture-editor"})
            self.assertEqual(response.status_code,422)
            self.assertEqual(response.json(),{"detail":"Invalid editorial request."})
            self.assertEqual(response.headers["cache-control"],"no-store")
            self.assertNotIn("sensitive-input",response.text)
            self.assertNotIn("private-token",response.text)
            response=self.client.get(f"/api/editorial/drafts/{self.identifier}/versions?limit=NaN",
                headers={"Authorization":"Bearer fixture-reader"})
            self.assertEqual(response.status_code,422)
            self.assertEqual(response.json(),{"detail":"Invalid editorial request."})

    def test_public_validation_error_contract_is_unchanged(self):
        with patch("app.api.routes.collector.collect_articles",new=AsyncMock()) as collector:
            response=self.client.get("/api/collect?limit_per_source=0")
            collector.assert_not_awaited()
        self.assertEqual(response.status_code,422)
        self.assertIsInstance(response.json()["detail"],list)

    def test_openapi_summary_detail_and_safe_error_contracts(self):
        schema=self.application.openapi();models=schema["components"]["schemas"]
        props=models["VersionSummary"]["properties"]
        self.assertFalse({"payload","sources","input_text"}&props.keys())
        self.assertTrue({"version_number","content_hash","actor_issuer","actor_subject","created_at","source_count"}<=props.keys())
        listing=schema["paths"]["/api/editorial/drafts/{draft_id}/versions"]["get"]
        self.assertEqual(listing["responses"]["200"]["content"]["application/json"]["schema"]["items"]["$ref"],"#/components/schemas/VersionSummary")
        detail=schema["paths"]["/api/editorial/drafts/{draft_id}/versions/{version_number}"]["get"]
        self.assertEqual(detail["security"],[{"EditorialBearer":[]}])
        self.assertEqual(detail["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],"#/components/schemas/VersionRead")
        self.assertTrue({"payload","sources"}<=models["VersionRead"]["properties"].keys())
        for status in ("400","415","422"):
            self.assertEqual(listing["responses"][status]["content"]["application/json"]["schema"]["$ref"],"#/components/schemas/EditorialAPIError")
