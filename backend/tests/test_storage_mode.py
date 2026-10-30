import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.services.article_identity import canonicalize_url, identity_hash
from app.services.story_matcher import publication_times_eligible


class StorageModeTests(unittest.TestCase):
    def test_memory_is_default_and_does_not_construct_a_database_engine(self):
        with patch("app.repositories.news_repository.create_database_engine", side_effect=AssertionError("DB access")):
            with TestClient(create_app(Settings(_env_file=None, postgres_password=""))) as client:
                self.assertEqual(client.get("/api/stories").status_code, 200)
                self.assertEqual(client.get("/api/editorial-queue").headers["X-News-Storage"], "memory")

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, news_storage_backend="auto")

    def test_postgres_missing_credentials_is_503_without_memory_fallback(self):
        application = create_app(Settings(_env_file=None, news_storage_backend="postgres", postgres_password=""))
        with TestClient(application) as client:
            for path in ("/api/stories", "/api/editorial-queue", "/api/collect", "/api/editorial-stories/missing"):
                response = client.get(path)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.headers["X-Collection-State"], "unavailable")
                self.assertIn("No memory fallback", response.json()["detail"])


class URLIdentityTests(unittest.TestCase):
    def test_opaque_query_bytes_remain_distinct(self):
        values = ["%FF", "%FE", "%EF%BF%BD", "+", "%20", "%2B"]
        urls = [canonicalize_url("https://example.com/?id=" + value) for value in values]
        self.assertEqual(len(set(urls)), len(values))
        self.assertEqual(urls[0], "https://example.com/?id=%FF")
        self.assertEqual(canonicalize_url("https://example.com/?id=%ff&%75tm_source=%FE&item=2"), "https://example.com/?id=%FF&item=2")

    def test_malformed_percent_escapes_are_rejected_without_replacement(self):
        for suffix in ("/%", "/%G0", "/%0", "/?id=%", "/?id=%XZ", "/?utm_source=%Z1"):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                canonicalize_url("https://example.com" + suffix)
        for url in ("https://example%.com/item", "https://example.com/item#%G0", "https://example.com/a\nb"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                canonicalize_url(url)

    def test_unicode_urls_and_utf8_percent_bytes_share_lossless_identity(self):
        literal = "https://primer.rs/vest/čć?ime=Đorđe&ime=Željko"
        encoded = "https://primer.rs/vest/%c4%8d%c4%87?ime=%c4%90or%c4%91e&ime=%c5%bdeljko"
        self.assertEqual(canonicalize_url(literal), canonicalize_url(encoded))
        self.assertEqual(canonicalize_url(canonicalize_url(literal)), canonicalize_url(literal))

    def test_tracking_fragment_default_port_and_slash_are_normalized(self):
        self.assertEqual(canonicalize_url("HTTPS://EXAMPLE.COM:443/a/%7eb/?utm_source=x&item=1#section"), "https://example.com/a/~b?item=1")

    def test_meaningful_queries_path_case_http_and_www_are_preserved(self):
        values = ["https://example.com/Path?p=1", "https://example.com/path?p=1",
                  "https://example.com/Path?p=2", "http://example.com/Path?p=1", "https://www.example.com/Path?p=1"]
        self.assertEqual(len({canonicalize_url(value) for value in values}), len(values))
        self.assertEqual(canonicalize_url("https://example.com/?b=2&a=1&a=3"), "https://example.com/?b=2&a=1&a=3")

    def test_invalid_or_credential_urls_are_rejected(self):
        for url in ("", "/relative", "file:///secret", "https://user:password@example.com", "https://example.com:bad"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                canonicalize_url(url)

    def test_hash_is_bounded_and_retains_unicode_identity(self):
        self.assertEqual(len(identity_hash("vest ć" * 10000)), 64)
        self.assertNotEqual(identity_hash("ć"), identity_hash("c"))


class TemporalEligibilityTests(unittest.TestCase):
    def test_timestamps_require_known_timezone_and_respect_configured_boundary(self):
        start = datetime(2026, 10, 30, tzinfo=timezone.utc)
        self.assertTrue(publication_times_eligible(start, start + timedelta(hours=48), 48))
        self.assertFalse(publication_times_eligible(start, start + timedelta(hours=48, seconds=1), 48))
        self.assertFalse(publication_times_eligible(start, start + timedelta(hours=25), 24))
        self.assertFalse(publication_times_eligible(None, start, 48))
        self.assertFalse(publication_times_eligible(start, start.replace(tzinfo=None), 48))

    def test_gap_configuration_rejects_unbounded_or_invalid_values(self):
        for value in (0, -1, float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Settings(_env_file=None, story_match_max_gap_hours=value)
