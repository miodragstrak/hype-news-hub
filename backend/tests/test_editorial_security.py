import unittest
from unittest.mock import patch, sentinel

from fastapi import Depends
from fastapi.testclient import TestClient

from app.api.editorial_security import require_editorial_permission
from app.core.config import Settings
from app.core.editorial_security import EditorialPermission, EditorialPrincipal, EditorialRole
from app.main import create_app
from editorial_identity import TestIdentityVerifier


class EditorialSecurityTests(unittest.TestCase):
    def setUp(self):
        self.verifier = TestIdentityVerifier()
        self.application = create_app(Settings(_env_file=None, news_storage_backend="memory"),
                                      editorial_identity_verifier=self.verifier)
        for permission in EditorialPermission:
            # Permission probes exist only on this test application.
            def endpoint(access=Depends(require_editorial_permission(permission))):
                return {"authorized": True}
            self.application.add_api_route("/_test/" + permission.value.split(":")[1], endpoint)
        self.client = TestClient(self.application)
        self.addCleanup(self.client.close)

    def headers(self, role):
        return {"Authorization": "Bearer fixture-" + role}

    def test_missing_basic_and_empty_credentials_never_invoke_verifier_or_database(self):
        with patch("app.api.editorial_security.get_editorial_database") as database:
            for headers in ({}, {"Authorization": "Basic fixture-administrator"}, {"Authorization": "Bearer"}):
                response = self.client.get("/api/editorial/capabilities", headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")
            database.assert_not_called()
        self.assertEqual(self.verifier.calls, [])

    def test_invalid_expired_and_forged_credentials_are_sanitized(self):
        for token in ("expired", "forged.signature", "{roles:administrator}"):
            response = self.client.get("/api/editorial/capabilities", headers={"Authorization": "Bearer " + token})
            self.assertEqual(response.status_code, 401)
            self.assertNotIn("sensitive", response.text)
            self.assertNotIn(token, response.text)

    def test_verification_failures_and_invalid_provider_return_fail_closed(self):
        with patch("app.api.editorial_security.get_editorial_database") as database:
            for token in ("unavailable", "broken", "wrong-return"):
                response = self.client.get("/api/editorial/capabilities", headers=self.headers(token))
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("sensitive", response.text)
                self.assertNotIn("administrator", response.text)
            database.assert_not_called()

    def test_role_matrix_is_enforced_in_dependencies(self):
        expected = {
            "reader": {"read"}, "editor": {"read", "edit", "submit"}, "reviewer": {"read", "review"},
            "publisher": {"read", "deliver"}, "administrator": {"read", "edit", "submit", "review", "deliver", "administer"},
            "no-roles": set(),
        }
        with patch("app.api.editorial_security.get_editorial_database", return_value=sentinel.repository) as database:
            for role, allowed in expected.items():
                for permission in EditorialPermission:
                    action = permission.value.split(":")[1]
                    database.reset_mock()
                    response = self.client.get("/_test/" + action, headers=self.headers(role))
                    with self.subTest(role=role, action=action):
                        self.assertEqual(response.status_code, 200 if action in allowed else 403)
                        self.assertEqual(database.call_count, int(action in allowed))

    def test_caller_roles_actor_ids_and_query_claims_cannot_escalate(self):
        with patch("app.api.editorial_security.get_editorial_database") as database:
            response = self.client.get("/_test/review?roles=administrator&actor_id=reviewer", headers={
                **self.headers("editor"), "X-Role": "administrator", "X-User": "admin", "X-Actor-Id": "reviewer",
            })
            self.assertEqual(response.status_code, 403)
            response = self.client.request("GET", "/_test/review", headers=self.headers("editor"),
                                           json={"roles": ["administrator"], "actor_id": "reviewer"})
            self.assertEqual(response.status_code, 403)
            database.assert_not_called()

    def test_verified_identity_cannot_activate_editorial_operations_in_memory_mode(self):
        for action in ("read", "edit", "submit", "review", "deliver", "administer"):
            response = self.client.get("/_test/" + action, headers=self.headers("administrator"))
            self.assertEqual(response.status_code, 503)
            self.assertIn("require PostgreSQL", response.json()["detail"])
        self.assertEqual(self.client.get("/api/stories").status_code, 200)
        self.assertEqual(self.client.get("/api/editorial-queue").status_code, 200)

    def test_default_application_never_accepts_test_identity_or_development_claims(self):
        for environment in ("development", "test", "production"):
            application = create_app(Settings(_env_file=None, app_env=environment, news_storage_backend="memory"))
            with TestClient(application) as client:
                response = client.get("/api/editorial/capabilities", headers={
                    **self.headers("administrator"), "X-Editorial-Test-Identity": "administrator",
                })
                self.assertEqual(response.status_code, 503)

    def test_postgres_missing_credentials_does_not_fall_back_to_memory(self):
        application = create_app(Settings(_env_file=None, news_storage_backend="postgres", postgres_password=""),
                                 editorial_identity_verifier=self.verifier)
        with TestClient(application) as client:
            response = client.get("/api/editorial/capabilities", headers=self.headers("reader"))
            self.assertEqual(response.status_code, 503)
            self.assertIn("No memory fallback", response.text)

    def test_capabilities_return_verified_roles_and_authorized_command_availability(self):
        with patch("app.api.editorial_security.get_editorial_database", return_value=sentinel.repository):
            response = self.client.get("/api/editorial/capabilities", headers=self.headers("reviewer"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.json(), {
            "roles": ["reviewer"], "permissions": ["editorial:read", "editorial:review"],
            "storage": "postgres", "commands_enabled": True, "ai_generation_enabled": False,
        })

    def test_production_router_protects_editorial_commands_and_has_no_test_endpoints(self):
        schema = create_app(Settings(_env_file=None)).openapi()
        self.assertEqual(schema["paths"]["/api/editorial/capabilities"]["get"]["security"], [{"EditorialBearer": []}])
        self.assertTrue(all(not path.startswith("/_test") for path in schema["paths"]))
        self.assertEqual(set(schema["paths"]["/api/editorial/capabilities"]), {"get"})
        for path, operations in schema["paths"].items():
            if path.startswith("/api/editorial/drafts"):
                for operation in operations.values():
                    self.assertEqual(operation["security"], [{"EditorialBearer": []}])


class EditorialPrincipalTests(unittest.TestCase):
    def test_unmapped_roles_and_mutable_claims_are_rejected(self):
        for roles in ([EditorialRole.READER], frozenset({"administrator"})):
            with self.assertRaises(ValueError):
                EditorialPrincipal("issuer", "subject", roles)
        for identity in ("", " ", "line\nbreak"):
            with self.assertRaises(ValueError):
                EditorialPrincipal(identity, "subject", frozenset())
