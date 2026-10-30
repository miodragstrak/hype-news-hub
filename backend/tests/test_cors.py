import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app


PRODUCTION = "https://hype-news-hub.vercel.app"
PREVIEW = "https://hype-news-hub-git-fix-p0-foundat-3ef0f6-miodrag-straks-projects.vercel.app"
COMMIT_PREVIEW = "https://hype-news-hub-a1b2c3d4e-miodrag-straks-projects.vercel.app"
BRANCH_PREVIEW = "https://hype-news-hub-git-feature-cors--checks-miodrag-straks-projects.vercel.app"
ALLOWED_ORIGINS = [
    "http://localhost:5173", "http://localhost:3000", PRODUCTION,
    PREVIEW, COMMIT_PREVIEW, BRANCH_PREVIEW,
]
DISALLOWED_ORIGINS = [
    "https://unrelated.vercel.app",
    "https://other-project-git-feature-miodrag-straks-projects.vercel.app",
    "https://hype-news-hub-other-git-feature-miodrag-straks-projects.vercel.app",
    "https://hype-news-hub-git-feature-another-team.vercel.app",
    "https://hype-news-hub-git-feature-miodrag-straks-projects.vercel.app.attacker.invalid",
    "https://hype-news-hub-git-feature-miodrag-straks-projectsXvercelYapp",
    "https://hype-news-hub-git-feature-miodrag-straks-projects.vercel.app@attacker.invalid",
    "https://hype-news-hub-git-feature-miodrag-straks-projects.vercel.app/path",
    "https://hype-news-hub-git-feature-miodrag-straks-projects.vercel.app:444",
    "http://hype-news-hub-git-feature-miodrag-straks-projects.vercel.app",
    "https://hype-news-hub.vercel.app.attacker.invalid",
    "https://hype-news-hub-abc12345-miodrag-straks-projects.vercel.app",
    "https://hype-news-hub-abc1234567-miodrag-straks-projects.vercel.app",
    "http://localhost:5174",
    "null",
]


class CORSTests(unittest.TestCase):
    def setUp(self):
        # Test configuration independently of a developer's .env and process env.
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.client = self.make_client(Settings(_env_file=None))

    def make_client(self, settings):
        client = TestClient(create_app(settings))
        self.addCleanup(client.close)
        return client

    def preflight(self, origin, method="GET", client=None):
        return (client or self.client).options("/api/collect", headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type, authorization",
        })

    def assert_allowed(self, response, origin):
        self.assertEqual(response.headers.get("access-control-allow-origin"), origin)
        self.assertEqual(response.headers.get("access-control-allow-credentials"), "true")
        self.assertIn("Origin", {value.strip() for value in response.headers.get("vary", "").split(",")})

    def test_get_allows_localhost_production_and_project_previews(self):
        for origin in ALLOWED_ORIGINS:
            with self.subTest(origin=origin):
                response = self.client.get("/", headers={"Origin": origin})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"name": "Hype News Hub", "status": "running"})
                self.assert_allowed(response, origin)

    def test_options_allows_get_and_post_with_request_headers(self):
        for origin in ALLOWED_ORIGINS:
            for method in ["GET", "POST"]:
                with self.subTest(origin=origin, method=method):
                    response = self.preflight(origin, method)
                    self.assertEqual(response.status_code, 200)
                    self.assert_allowed(response, origin)
                    self.assertIn(method, response.headers["access-control-allow-methods"])
                    headers = {value.strip().lower() for value in response.headers["access-control-allow-headers"].split(",")}
                    self.assertTrue({"content-type", "authorization"} <= headers)

    def test_get_does_not_expose_responses_to_untrusted_origins(self):
        for origin in DISALLOWED_ORIGINS:
            with self.subTest(origin=origin):
                response = self.client.get("/", headers={"Origin": origin})
                # CORS controls browser access, not whether a GET executes.
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("access-control-allow-origin", response.headers)

    def test_options_rejects_untrusted_origins(self):
        for origin in DISALLOWED_ORIGINS:
            with self.subTest(origin=origin):
                response = self.preflight(origin)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn("access-control-allow-origin", response.headers)

    def test_preflight_does_not_execute_collection(self):
        with patch("app.api.routes.collector.collect_articles", new_callable=AsyncMock) as collect:
            self.assertEqual(self.preflight(PREVIEW).status_code, 200)
            self.assertEqual(self.preflight("https://unrelated.vercel.app").status_code, 400)
            collect.assert_not_awaited()

    def test_requests_without_origin_keep_the_existing_contract(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"name": "Hype News Hub", "status": "running"})
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_api_validation_errors_include_cors_without_changing_status(self):
        response = self.client.get("/api/collect?limit_per_source=0", headers={"Origin": PREVIEW})
        self.assertEqual(response.status_code, 422)
        self.assertIsInstance(response.json()["detail"], list)
        self.assert_allowed(response, PREVIEW)

    def test_api_not_found_errors_include_cors(self):
        response = self.client.get("/api/does-not-exist", headers={"Origin": PREVIEW})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Not Found"})
        self.assert_allowed(response, PREVIEW)

    def test_preflight_still_rejects_unsupported_http_methods(self):
        self.assertEqual(self.preflight(PREVIEW, "TRACE").status_code, 400)

    def test_environment_can_replace_the_preview_regex(self):
        custom = "https://hype-news-hub-git-review-only-miodrag-straks-projects.vercel.app"
        with patch.dict(os.environ, {"BACKEND_CORS_ORIGIN_REGEX": (
            r"^https://hype-news-hub-git-review-only-miodrag-straks-projects\.vercel\.app$"
        )}):
            client = self.make_client(Settings(_env_file=None))
        self.assertEqual(self.preflight(custom, client=client).status_code, 200)
        self.assertEqual(self.preflight(PREVIEW, client=client).status_code, 400)
        self.assertEqual(self.preflight(PRODUCTION, client=client).status_code, 200)

    def test_existing_exact_origin_environment_override_remains_supported(self):
        with patch.dict(os.environ, {"BACKEND_CORS_ORIGINS": f" {PRODUCTION}, https://editor.example.invalid, "}):
            client = self.make_client(Settings(_env_file=None))
        self.assertEqual(self.preflight(PRODUCTION, client=client).status_code, 200)
        self.assertEqual(self.preflight("https://editor.example.invalid", client=client).status_code, 200)
        # Adding a regex does not discard an existing Render allowlist.
        self.assertEqual(self.preflight(PREVIEW, client=client).status_code, 200)
        self.assertEqual(self.preflight("https://unrelated.vercel.app", client=client).status_code, 400)

    def test_blank_regex_disables_previews_but_preserves_exact_origins(self):
        with patch.dict(os.environ, {"BACKEND_CORS_ORIGIN_REGEX": "   "}):
            config = Settings(_env_file=None)
            client = self.make_client(config)
        self.assertIsNone(config.backend_cors_origin_regex)
        self.assertEqual(self.preflight(PREVIEW, client=client).status_code, 400)
        for origin in ALLOWED_ORIGINS[:3]:
            self.assertEqual(self.preflight(origin, client=client).status_code, 200)

    def test_explicit_preview_origin_can_be_allowed_with_regex_disabled(self):
        client = self.make_client(Settings(_env_file=None, backend_cors_origins=PREVIEW, backend_cors_origin_regex=None))
        self.assert_allowed(self.preflight(PREVIEW, client=client), PREVIEW)
        self.assertEqual(self.preflight(COMMIT_PREVIEW, client=client).status_code, 400)

    def test_example_environment_loads_the_regex_with_literal_backslashes(self):
        example = Path(__file__).resolve().parents[1] / ".env.example"
        client = self.make_client(Settings(_env_file=example))
        for origin in ALLOWED_ORIGINS:
            self.assertEqual(self.preflight(origin, client=client).status_code, 200)
        for origin in DISALLOWED_ORIGINS:
            self.assertEqual(self.preflight(origin, client=client).status_code, 400)

    def test_wildcard_origins_are_rejected(self):
        for value in ["*", " * ", f"{PRODUCTION}, *"]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Settings(_env_file=None, backend_cors_origins=value)

    def test_invalid_regex_is_rejected_at_settings_load(self):
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, backend_cors_origin_regex="(")
