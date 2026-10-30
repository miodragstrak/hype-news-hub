import copy
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import httpx

from app.config.sources import HYPE_SOURCES, configured_diagnostic_source
from app.connectors.errors import SourceFetchError
from app.connectors.http_client import PublicHTTPTransport, PublicNetworkBackend, SourceHTTPClient
from app.connectors.wordpress import WordPressConnector
from app.core.config import Settings
from app.main import create_app
from app.services.collector import collect_articles
from app.services.source_collection import normalize_source_batch
from app.services.source_discovery_service import discover_sources
from app.services.story_service import get_latest_stories, set_latest_stories
from test_source_http import WireBackend, json_response

SERBIA = "https://hypetv.rs"
PRODUCTION = "https://www.hypeproduction.rs"


def wp_post(base=SERBIA, key=42):
    return {
        "id": key, "type": "post", "link": f"{base}/article-{key}/", "date_gmt": "2026-10-30T12:00:00",
        "title": {"rendered": "A &amp; B"}, "excerpt": {"rendered": "<p>Original excerpt</p>"},
        "content": {"rendered": "<p>Full <strong>source content</strong></p><script>untrusted()</script>"},
        "_embedded": {"wp:featuredmedia": [{"source_url": "https://media.invalid/image.jpg"}],
                      "wp:term": [[{"taxonomy": "category", "name": "Entertainment"}, {"taxonomy": "language", "slug": "sr"}]]},
    }


def inject_http(handler):
    def factory(base_url, **kwargs):
        client = SourceHTTPClient(base_url, transport_factory=lambda: httpx.MockTransport(handler))
        return WordPressConnector(base_url, http_client=client, **kwargs)
    return patch("app.config.sources.WordPressConnector", side_effect=factory)


class WordPressTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_serbia_selective_policy_preserves_parser_and_full_article_data(self):
        requests = []
        payload = wp_post()
        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.params.get("_embed"), "wp:featuredmedia,wp:term")
            self.assertEqual(request.url.params.get("per_page"), "5")
            return json_response([payload])
        with inject_http(handler):
            source = configured_diagnostic_source(SERBIA)
            posts = await source.connector_factory(source.url).fetch_latest(limit=5)
            articles = normalize_source_batch(posts, source.url, source.connector, source.name)
        self.assertEqual(len(requests), 1)
        article = articles[0]
        self.assertEqual((article.external_id, article.source, article.source_url), ("42", "Hype Serbia", SERBIA))
        self.assertEqual(article.title, "A & B")
        self.assertEqual(article.url, payload["link"])
        self.assertEqual(article.published_at, payload["date_gmt"])
        self.assertEqual(article.featured_image, "https://media.invalid/image.jpg")
        self.assertEqual(article.categories, ["Entertainment"])
        self.assertEqual(article.language, "sr")
        self.assertEqual(article.content, "Full source content")
        self.assertEqual(article.raw, payload)

    async def test_all_other_source_embedding_policies_remain_unchanged(self):
        observed = []
        def handler(request):
            observed.append(request)
            self.assertIn("_embed", request.url.params)
            self.assertEqual(request.url.params.get("_embed"), "")
            return json_response([])
        with inject_http(handler):
            for source in HYPE_SOURCES:
                if source.url != SERBIA:
                    self.assertEqual(await source.connector_factory(source.url).fetch_latest(), [])
        self.assertEqual(len(observed), 5)
        self.assertIn("www.hypeproduction.rs", {request.url.host for request in observed})

    async def test_page_limits_are_bounded(self):
        observed = []
        def handler(request):
            observed.append(request.url.params["per_page"])
            return json_response([])
        with inject_http(handler):
            connector = configured_diagnostic_source(SERBIA).connector_factory(SERBIA)
            await connector.fetch_latest(limit=0)
            await connector.fetch_latest(limit=1000)
        self.assertEqual(observed, ["1", "100"])

    async def test_empty_posts_succeed_but_objects_and_non_object_entries_fail(self):
        for payload, expected in (([], None), ({"message": "secret"}, "malformed_structure"), ([None], "malformed_structure")):
            with inject_http(lambda request: json_response(payload)):
                connector = configured_diagnostic_source(PRODUCTION).connector_factory(PRODUCTION)
                if expected:
                    with self.assertRaises(SourceFetchError) as caught:
                        await connector.fetch_latest()
                    self.assertEqual(caught.exception.code, expected)
                else:
                    with self.assertLogs("app.services.source_collection", level="INFO") as logs:
                        result = normalize_source_batch(await connector.fetch_latest(), PRODUCTION)
                    self.assertEqual(result, [])
                    self.assertIn("upstream_empty", " ".join(logs.output))

    async def test_malformed_embedding_has_structured_failure_not_attribute_error(self):
        for embedded in ("invalid", {"wp:featuredmedia": [None]}, {"wp:term": [None]}, {"wp:term": [["invalid"]]}, {"wp:term": [[{"taxonomy": []}]]}):
            payload = wp_post()
            payload["_embedded"] = embedded
            with self.subTest(embedded=embedded), inject_http(lambda request: json_response([payload])):
                with self.assertRaises(SourceFetchError) as caught:
                    await configured_diagnostic_source(SERBIA).connector_factory(SERBIA).fetch_latest()
                self.assertEqual(caught.exception.code, "malformed_structure")

    async def test_optional_embedding_can_be_absent(self):
        payload = wp_post()
        payload["_embedded"] = None
        with inject_http(lambda request: json_response([payload])):
            fetched = await configured_diagnostic_source(SERBIA).connector_factory(SERBIA).fetch_latest()
        article = normalize_source_batch(fetched, SERBIA)[0]
        self.assertIsNone(article.featured_image)
        self.assertEqual(article.categories, [])
        self.assertEqual(article.content, "Full source content")

    async def test_unsafe_article_urls_are_filtered_and_media_urls_are_removed(self):
        for target in ("javascript:alert(1)", "data:text/html,unsafe", "file:///secret", "http://127.0.0.1/private", "https://user:secret@host.invalid/"):
            payload = wp_post()
            payload["link"] = target
            payload["_embedded"]["wp:featuredmedia"][0]["source_url"] = target
            with self.subTest(target=target), inject_http(lambda request: json_response([payload])):
                fetched = await configured_diagnostic_source(SERBIA).connector_factory(SERBIA).fetch_latest()
                with self.assertRaises(SourceFetchError) as caught:
                    normalize_source_batch(fetched, SERBIA)
                self.assertEqual(caught.exception.code, "normalization_filtered")
                self.assertIsNone(fetched[0]["featured_image"])

    async def test_partial_filtering_retains_valid_articles_with_explicit_log(self):
        payload = wp_post()
        malformed = copy.deepcopy(payload)
        malformed["title"] = {}
        with inject_http(lambda request: json_response([payload, malformed])):
            fetched = await configured_diagnostic_source(SERBIA).connector_factory(SERBIA).fetch_latest()
        with self.assertLogs("app.services.source_collection", level="WARNING") as logs:
            result = normalize_source_batch(fetched, SERBIA)
        self.assertEqual(len(result), 1)
        self.assertIn("normalization_filtered", " ".join(logs.output))
        self.assertIn("fetched=2 accepted=1", " ".join(logs.output))

    async def test_unsafe_media_does_not_discard_otherwise_valid_article(self):
        payload = wp_post()
        payload["_embedded"]["wp:featuredmedia"][0]["source_url"] = "javascript:unsafe()"
        with inject_http(lambda request: json_response([payload])):
            fetched = await configured_diagnostic_source(SERBIA).connector_factory(SERBIA).fetch_latest()
        article = normalize_source_batch(fetched, SERBIA)[0]
        self.assertEqual(article.external_id, "42")
        self.assertEqual(article.content, "Full source content")
        self.assertIsNone(article.featured_image)

    async def test_connection_probe_uses_same_embedding_and_reports_empty_as_success(self):
        requests = []
        def handler(request):
            requests.append(request)
            return json_response({"routes": {}} if request.url.path == "/wp-json" else [])
        with inject_http(handler):
            result = await configured_diagnostic_source(SERBIA).connector_factory(SERBIA).test_connection()
        self.assertTrue(result["success"])
        self.assertEqual(requests[1].url.params.get("_embed"), "wp:featuredmedia,wp:term")


class DiscoveryCollectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.previous = get_latest_stories()

    def tearDown(self):
        set_latest_stories(self.previous)

    async def test_discovery_and_collection_use_same_policies_and_production_stays_empty(self):
        requests = []
        def handler(request):
            requests.append(request)
            if request.url.path == "/wp-json":
                return json_response({"routes": {}})
            if request.url.path == "/feed/":
                return httpx.Response(200, headers={"content-type": "application/rss+xml"}, stream=httpx.ByteStream(b"<rss><channel/></rss>"))
            self.assertEqual(request.url.path, "/wp-json/wp/v2/posts")
            if request.url.host == "hypetv.rs":
                self.assertEqual(request.url.params.get("_embed"), "wp:featuredmedia,wp:term")
            else:
                self.assertEqual(request.url.params.get("_embed"), "")
            return json_response([] if request.url.host == "www.hypeproduction.rs" else [wp_post(f"https://{request.url.host}")])
        with inject_http(handler):
            discovery = await discover_sources()
            result = await collect_articles(limit_per_source=5)
        production = next(item for item in discovery if item.url == PRODUCTION)
        self.assertTrue(production.wordpress)
        self.assertIsNone(production.sample_article)
        self.assertEqual(production.preferred, "wordpress")
        self.assertEqual(result.sources_failed, 0)
        self.assertEqual(result.articles_total, 5)
        source_result = next(item for item in result.source_results if item.url == PRODUCTION)
        self.assertEqual((source_result.status, source_result.articles_total, source_result.error), ("success", 0, None))
        serbia_calls = [request for request in requests if request.url.host == "hypetv.rs" and "posts" in request.url.path]
        self.assertEqual({request.url.params["per_page"] for request in serbia_calls}, {"1", "5"})
        self.assertFalse(any("pages" in request.url.path for request in requests))

    async def test_http_failures_and_normalization_failures_remain_isolated(self):
        selected = [configured_diagnostic_source(SERBIA), configured_diagnostic_source(PRODUCTION)]
        for outcome in (403, 429, 503, "filtered", "timeout", "html", "json"):
            def handler(request):
                if request.url.host == "www.hypeproduction.rs":
                    return json_response([])
                if isinstance(outcome, int):
                    return httpx.Response(outcome, content="secret origin details")
                if outcome == "filtered":
                    return json_response([{"id": 1, "title": {}, "link": "javascript:unsafe()"}])
                if outcome == "timeout":
                    raise httpx.ReadTimeout("secret network details")
                body = b"<html>secret</html>" if outcome == "html" else b"{invalid"
                return httpx.Response(200, headers={"content-type": "text/html" if outcome == "html" else "application/json"}, stream=httpx.ByteStream(body))
            with self.subTest(outcome=outcome), inject_http(handler), patch("app.services.collector.HYPE_SOURCES", selected), self.assertLogs("app.services.collector", level="ERROR"):
                result = await collect_articles()
            self.assertEqual((result.sources_processed, result.sources_failed), (2, 1))
            self.assertEqual(result.source_results[1].status, "success")
            self.assertNotIn("secret", result.source_results[0].error)
            self.assertIn({403: "http_rejected", 429: "http_rejected", 503: "http_rejected", "filtered": "normalization_filtered", "timeout": "timeout", "html": "invalid_json", "json": "invalid_json"}[outcome], result.source_results[0].error)

    async def test_discovery_does_not_mistake_html_for_wordpress_or_fetch_corporate_pages(self):
        def handler(request):
            if request.url.path == "/wp-json":
                return httpx.Response(200, headers={"content-type": "text/html"}, stream=httpx.ByteStream(b"<html/>"))
            if "posts" in request.url.path:
                return json_response({"code": "error", "message": "secret"})
            return httpx.Response(404)
        with inject_http(handler):
            result = await discover_sources()
        self.assertTrue(all(not item.wordpress and not item.rss and item.sample_article is None for item in result))


class DiagnosticSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(Settings(_env_file=None)))
        self.addCleanup(self.client.close)

    def test_unconfigured_and_unsafe_urls_are_rejected_before_outbound_access(self):
        urls = ("http://hypetv.rs", "https://localhost", "https://127.0.0.1", "https://169.254.169.254", "https://[::1]", "https://2130706433", "https://unconfigured.invalid", "https://hypetv.rs.attacker.invalid", "https://user:secret@hypetv.rs", "https://hypetv.rs:8443", "https://hypetv.rs/private", "https://hypetv.rs?path=private", "https://hypetv.rs#fragment")
        with patch("app.connectors.http_client.SourceHTTPClient.get", AsyncMock(side_effect=AssertionError("Unexpected network"))) as fetch:
            for endpoint in ("/api/test-wordpress", "/api/fetch-wordpress", "/api/test-wordpress-normalized"):
                for url in urls:
                    response = self.client.get(endpoint, params={"url": url})
                    self.assertEqual(response.status_code, 403, response.text)
                    self.assertNotIn("secret", response.text)
            fetch.assert_not_awaited()

    def test_allowed_hostname_resolving_private_is_forbidden_without_opening_socket(self):
        backend = WireBackend()
        def factory(base_url, **kwargs):
            network = PublicNetworkBackend({"hypetv.rs"}, resolver=AsyncMock(return_value=["10.0.0.1"]), backend=backend)
            client = SourceHTTPClient(base_url, transport_factory=lambda: PublicHTTPTransport({"hypetv.rs"}, network_backend=network))
            return WordPressConnector(base_url, http_client=client, **kwargs)
        with patch("app.config.sources.WordPressConnector", side_effect=factory):
            for endpoint in ("/api/test-wordpress", "/api/fetch-wordpress", "/api/test-wordpress-normalized"):
                response = self.client.get(endpoint, params={"url": SERBIA})
                self.assertEqual(response.status_code, 403)
                self.assertNotIn("10.0.0.1", response.text)
        self.assertEqual(backend.calls, [])

    def test_configured_public_diagnostics_keep_contracts_and_production_empty_success(self):
        def handler(request):
            return json_response({"routes": {}} if request.url.path == "/wp-json" else ([] if request.url.host == "www.hypeproduction.rs" else [wp_post()]))
        with inject_http(handler):
            for endpoint in ("/api/fetch-wordpress", "/api/test-wordpress-normalized"):
                response = self.client.get(endpoint, params={"url": SERBIA})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()[0]["external_id"], "42")
            response = self.client.get("/api/test-wordpress", params={"url": PRODUCTION})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "posts_found": 0, "connector": "wordpress"})

    def test_upstream_error_response_contains_only_safe_category(self):
        with inject_http(lambda request: httpx.Response(403, content="secret origin body")):
            response = self.client.get("/api/fetch-wordpress", params={"url": SERBIA})
        self.assertEqual(response.status_code, 502)
        self.assertIn("http_rejected", response.json()["detail"])
        self.assertNotIn("secret", response.text)
