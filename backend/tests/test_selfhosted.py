import os
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.selfhosted import create_selfhosted_app
from app.selfhosted_config import load_database_secrets


def selfhosted_settings(**overrides):
    values = dict(app_env="production", news_storage_backend="postgres", postgres_password=secrets.token_hex(32),
                  backend_cors_origins="https://news.example.invalid", backend_cors_origin_regex=None,
                  ai_processing_provider="disabled")
    return Settings(_env_file=None, **(values | overrides))


class SelfhostedTests(unittest.TestCase):
    def setUp(self):
        clean = patch.dict(os.environ, {}, clear=True)
        clean.start()
        self.addCleanup(clean.stop)

    def test_gate_denies_all_application_paths_without_database_access(self):
        with patch("app.api.readiness.check_database") as database, TestClient(create_selfhosted_app(selfhosted_settings()), base_url="https://news.example.invalid") as client:
            for path in ["/api/collect", "/api/stories", "/api/discovery", "/api/editorial/capabilities",
                         "/api/editorial/drafts", "/api/editorial/ai/suggestions", "/docs", "/openapi.json"]:
                for method in ["GET", "POST", "OPTIONS"]:
                    response = client.request(method, path)
                    self.assertEqual(response.status_code, 503, (method, path))
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
            database.assert_not_called()
            self.assertEqual(client.get("/").status_code, 200)
            ready = client.get("/ready")
            self.assertEqual(ready.json(), {"status": "ready", "scope": "infrastructure", "editorial_access": "blocked"})

    def test_readiness_does_not_disclose_exception_or_secret(self):
        sensitive = secrets.token_hex(32)
        with patch("app.api.readiness.check_database", side_effect=RuntimeError(sensitive)), TestClient(create_selfhosted_app(selfhosted_settings()), base_url="https://news.example.invalid") as client:
            result = client.get("/ready")
            self.assertEqual(result.status_code, 503)
            self.assertEqual(result.json(), {"status": "not_ready", "scope": "infrastructure"})
            self.assertNotIn(sensitive, result.text)

    def test_selfhosted_configuration_fails_closed(self):
        for override in [dict(news_storage_backend="memory"), dict(app_env="development"), dict(postgres_password=""),
                         dict(ai_processing_provider="mock"), dict(ai_processing_provider="gemini"),
                         dict(backend_cors_origin_regex=".*"), dict(backend_cors_origins="http://news.example.invalid"),
                         dict(backend_cors_origins="https://one.invalid,https://two.invalid"),
                         dict(backend_cors_origins="https://news.example.invalid/api"),
                         dict(backend_cors_origins="https://user:password@news.example.invalid")]:
            with self.subTest(override=override), self.assertRaises(ValueError):
                create_selfhosted_app(selfhosted_settings(**override))

    def test_normal_memory_app_remains_available_and_has_no_new_health_contract(self):
        with TestClient(create_app(Settings(_env_file=None))) as client:
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/ready").status_code, 404)
            self.assertEqual(client.get("/api/editorial/capabilities").status_code, 401)
        self.assertNotIn("/ready", create_app(Settings(_env_file=None)).openapi()["paths"])

    def test_file_secret_loading_preserves_password_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "password"
            value = " " + secrets.token_hex(32) + " \t"
            path.write_text(value + "\n", encoding="utf8")
            os.environ["POSTGRES_PASSWORD_FILE"] = str(path)
            load_database_secrets()
            self.assertEqual(os.environ["POSTGRES_PASSWORD"], value)
            with self.assertRaises(ValueError):
                load_database_secrets()  # Ambiguous environment + file is rejected.

    def test_missing_empty_or_oversized_files_fail_without_reflecting_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-name"
            for content in [None, b"", b"a" * 4097, b"\xff", b"secret\x00invalid"]:
                if content is not None:
                    path.write_bytes(content)
                os.environ["POSTGRES_PASSWORD_FILE"] = str(path)
                with self.assertRaises(ValueError) as result:
                    load_database_secrets()
                self.assertNotIn(str(path), str(result.exception))

    def test_gemini_opt_in_requires_authentication_and_conservative_local_configuration(self):
        from app.selfhosted import validate_selfhosted_ai
        valid = selfhosted_settings(auth_enabled=True, ai_processing_provider="gemini",
            gemini_model="gemini-fixture-model", gemini_api_key="fixture-key-only", ai_daily_generation_limit=3,
            ai_processing_timeout_seconds=30)
        validate_selfhosted_ai(valid)  # No network or database needed for configuration validation.
        for changes in ({"auth_enabled":False}, {"ai_daily_generation_limit":0}, {"gemini_safe_retries":1},
                        {"gemini_max_input_tokens":4097}, {"gemini_max_output_tokens":2049},
                        {"gemini_model":""}, {"ai_processing_provider":"mock"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_selfhosted_ai(valid.model_copy(update=changes))
        self.assertEqual(Settings(_env_file=None).ai_processing_provider, "disabled")

    def test_optional_gemini_secret_is_file_only_and_not_loaded_when_disabled(self):
        from app.selfhosted_config import load_gemini_secret
        load_gemini_secret()
        self.assertNotIn("GEMINI_API_KEY", os.environ)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test-key"; path.write_text("fixture-key-only\n")
            os.environ.update(AI_PROCESSING_PROVIDER="gemini", GEMINI_API_KEY_FILE=str(path))
            load_gemini_secret()
            self.assertEqual(os.environ["GEMINI_API_KEY"], "fixture-key-only")
            with self.assertRaises(ValueError): load_gemini_secret()

    def test_valid_opt_in_still_denies_anonymous_generation_without_contacting_provider(self):
        settings = selfhosted_settings(auth_enabled=True, auth_trusted_proxy_ips="127.0.0.1", ai_processing_provider="gemini",
            gemini_model="gemini-fixture-model", gemini_api_key="fixture-key-only", ai_processing_timeout_seconds=30)
        with patch("httpx.AsyncClient.send", side_effect=AssertionError("No provider HTTP permitted")), \
                TestClient(create_selfhosted_app(settings), base_url="https://news.example.invalid") as client:
            self.assertEqual(client.post("/api/editorial/ai/suggestions",json={}).status_code,401)
