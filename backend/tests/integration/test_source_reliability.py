import httpx
from sqlalchemy import select

from app.config.sources import configured_diagnostic_source
from app.models import CollectedArticle, CollectionRun
from integration.test_persistent_collection import PersistentCollectionCase
from test_source_http import json_response
from test_wordpress_reliability import PRODUCTION, SERBIA, inject_http, wp_post


class PersistentSourceReliabilityTests(PersistentCollectionCase):
    def test_real_connector_transport_persists_identities_and_truthful_empty_results(self):
        selected = [configured_diagnostic_source(SERBIA), configured_diagnostic_source(PRODUCTION)]
        def handler(request):
            if request.url.host == "hypetv.rs":
                self.assertEqual(request.url.params.get("_embed"), "wp:featuredmedia,wp:term")
                return json_response([wp_post()])
            return json_response([])
        with inject_http(handler):
            first = self.collect(selected)
            repeated = self.collect(selected)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(repeated.headers["X-Collection-New-Articles"], "0")
        self.assertEqual(first.json()["stories"], repeated.json()["stories"])
        self.assertEqual(first.json()["source_results"][1]["status"], "success")
        self.assertEqual(first.json()["source_results"][1]["articles_total"], 0)
        self.assertEqual(self.count(CollectedArticle), 1)
        with self.factory() as session:
            article = session.scalars(select(CollectedArticle)).one()
            self.assertEqual(article.external_id, "42")
            self.assertEqual(article.url, wp_post()["link"])
            self.assertEqual(article.content, "Full source content")
            self.assertEqual(article.featured_image, "https://media.invalid/image.jpg")

    def test_filtered_and_http_failures_are_persisted_without_clearing_feed(self):
        selected = [configured_diagnostic_source(SERBIA), configured_diagnostic_source(PRODUCTION)]
        with inject_http(lambda request: json_response([wp_post()] if request.url.host == "hypetv.rs" else [])):
            original = self.collect(selected).json()["stories"]
        for outcome in ("filtered", "timeout", 429):
            def handler(request):
                if request.url.host == "www.hypeproduction.rs":
                    return json_response([])
                if outcome == "filtered":
                    return json_response([{"id": 42, "title": {}, "link": "javascript:unsafe"}])
                if outcome == "timeout":
                    raise httpx.ReadTimeout("sensitive connection details")
                return httpx.Response(outcome, content="sensitive origin body")
            with self.subTest(outcome=outcome), inject_http(handler):
                response = self.collect(selected)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["X-Collection-State"], "partial")
            self.assertEqual(response.json()["stories"], original)
            self.assertEqual(self.count(CollectedArticle), 1)
            self.assertNotIn("sensitive", response.text)
        with self.factory() as session:
            runs = list(session.scalars(select(CollectionRun).order_by(CollectionRun.started_at)))
            errors = [next(result.error for result in run.source_results if result.status == "failed") for run in runs[1:]]
            self.assertTrue(any("normalization_filtered" in error for error in errors))
            self.assertTrue(any("timeout" in error for error in errors))
            self.assertTrue(any("http_rejected" in error for error in errors))

    def test_historical_unsafe_media_is_not_emitted_by_database_reads(self):
        selected = [configured_diagnostic_source(SERBIA)]
        with inject_http(lambda request: json_response([wp_post()])):
            response = self.collect(selected)
        with self.factory.begin() as session:
            article = session.scalars(select(CollectedArticle)).one()
            article.featured_image = "javascript:unsafe"
        story_id = response.json()["stories"][0]["id"]
        workspace = self.client.get(f"/api/editorial-stories/{story_id}")
        self.assertEqual(workspace.status_code, 200)
        self.assertIsNone(workspace.json()["source_articles"][0]["featured_image"])
