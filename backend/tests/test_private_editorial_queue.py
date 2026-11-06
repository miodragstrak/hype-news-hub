"""Private queue fail-closed boundaries without PostgreSQL or provider calls."""
import unittest

from editorial_identity import TestIdentityVerifier
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


class PrivateQueueBoundaryTests(unittest.TestCase):
    def test_unconfigured_identity_and_memory_storage_fail_closed(self):
        config = Settings(_env_file=None, news_storage_backend="memory")
        for verifier in (None, TestIdentityVerifier()):
            with TestClient(create_app(config, editorial_identity_verifier=verifier)) as client:
                self.assertEqual(client.get("/api/editorial/queue").status_code, 401)
                self.assertEqual(client.get("/api/editorial/queue", headers={"Authorization": "Bearer fixture-reader"}).status_code, 503)
                # Public/demo collection projection keeps its previous contract.
                self.assertEqual(client.get("/api/editorial-queue").status_code, 200)

    def test_openapi_separates_public_and_private_contracts(self):
        schema = create_app(Settings(_env_file=None)).openapi()
        private = schema["paths"]["/api/editorial/queue"]["get"]
        public = schema["paths"]["/api/editorial-queue"]["get"]
        self.assertEqual(private["security"], [{"EditorialBearer": []}])
        self.assertNotIn("security", public)
        self.assertEqual(public["responses"]["200"]["content"]["application/json"]["schema"],
                         {"$ref": "#/components/schemas/EditorialQueueResponse"})
        fields = schema["components"]["schemas"]["QueueAIStatus"]["properties"]
        self.assertEqual(set(fields), {"has_suggestion", "latest_suggestion_id", "status", "created_at", "completed_at", "recovery_required"})
