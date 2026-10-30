import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.config.sources import SourceConfig
from app.main import app
from app.schemas.article import NormalizedArticle
from app.services.collector import collect_articles
from app.services.editorial_intelligence import get_editorial_queue_response
from app.services.story_service import build_stories_from_articles, get_latest_stories, set_latest_stories
from app.services.timestamps import parse_published_at


def article(external_id="1", title="A & B", date="2026-10-30T10:00:00", source="Source One"):
    return NormalizedArticle(
        external_id=external_id, connector="wordpress", source=source,
        source_url="https://one.invalid", title=title,
        url=f"https://one.invalid/{external_id}", published_at=date,
        categories=["Entertainment"],
    )


def source(name, posts=None, error=None):
    connector = AsyncMock()
    connector.fetch_latest.return_value = posts or []
    connector.fetch_latest.side_effect = error
    return SourceConfig(name=name, url=f"https://{name}.invalid", connector="wordpress", connector_factory=lambda _: connector)


def post(external_id, date):
    return {"external_id": external_id, "title": f"Headline {external_id}",
            "url": f"https://one.invalid/{external_id}", "published_at": date}


class TimestampTests(unittest.TestCase):
    def test_dates_are_normalized_to_utc_without_rewriting_source_values(self):
        expected = datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
        for value in ["2026-10-30T10:00:00", "2026-10-30T10:00:00Z", "2026-10-30T12:00:00+02:00"]:
            with self.subTest(value=value):
                self.assertEqual(parse_published_at(value), expected)

    def test_missing_invalid_and_out_of_range_dates_are_unknown(self):
        for value in [None, "", "not-a-date", "2026-02-30", "0001-01-01T00:00:00+01:00"]:
            with self.subTest(value=value):
                self.assertIsNone(parse_published_at(value))


class StoryScoreTests(unittest.TestCase):
    def test_single_article_has_no_observed_pairwise_match(self):
        story = build_stories_from_articles([article()]).stories[0]
        self.assertEqual(story.similarity_score, 0)

    def test_nonidentical_match_is_not_reported_as_perfect(self):
        result = build_stories_from_articles([article(), article("2", "A and B", source="Source Two")])
        self.assertEqual(len(result.stories), 1)
        self.assertEqual(result.story_candidates_total, 1)
        self.assertEqual(result.stories[0].similarity_score, 77)

    def test_actual_perfect_match_can_raise_the_strongest_match_to_100(self):
        result = build_stories_from_articles([article(), article("2", "A and B"), article("3")])
        self.assertEqual(len(result.stories), 1)
        self.assertEqual(result.stories[0].similarity_score, 100)

    def test_story_order_uses_instants_not_lexical_offsets(self):
        result = build_stories_from_articles([
            article("earlier", date="2026-10-30T12:00:00+03:00"),
            article("later", title="Entirely unrelated news", date="2026-10-30T10:00:00Z"),
            article("unknown", title="Another distinct event", date="invalid"),
        ], merge_threshold=100)
        self.assertEqual([story.primary_article.external_id for story in result.stories], ["later", "earlier", "unknown"])


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.previous = get_latest_stories()

    def tearDown(self):
        set_latest_stories(self.previous)

    async def test_mixed_dates_do_not_abort_collection_and_attribution_is_retained(self):
        posts = [post("naive", "2026-10-30T10:00:00"), post("offset", "2026-10-30T12:00:00+03:00"),
                 post("zulu", "2026-10-30T11:00:00Z"), post("missing", None), post("invalid", "bad")]
        with patch("app.services.collector.HYPE_SOURCES", [source("one", posts)]):
            result = await collect_articles()
        self.assertEqual([a.external_id for a in result.articles], ["zulu", "naive", "offset", "missing", "invalid"])
        self.assertEqual(result.articles[1].published_at, "2026-10-30T10:00:00")
        self.assertTrue(all(a.source == "one" and a.source_url == "https://one.invalid" for a in result.articles))
        self.assertEqual(result.source_results[0].articles_total, 5)

    async def test_source_failure_is_isolated_and_reported(self):
        with patch("app.services.collector.HYPE_SOURCES", [source("bad", error=RuntimeError("upstream failed")), source("good", [post(1, None)])]), self.assertLogs("app.services.collector", level="ERROR"):
            result = await collect_articles()
        self.assertEqual((result.sources_processed, result.sources_failed, result.articles_total), (2, 1, 1))
        self.assertEqual([s.status for s in result.source_results], ["failed", "success"])
        self.assertIsNotNone(result.source_results[0].error)

    async def test_connector_construction_failure_does_not_abort_other_sources(self):
        def fail_to_construct(_):
            raise ValueError("invalid config")

        broken = SourceConfig("broken", "https://broken.invalid", "wordpress", fail_to_construct)
        with patch("app.services.collector.HYPE_SOURCES", [broken, source("good")]), self.assertLogs("app.services.collector", level="ERROR"):
            result = await collect_articles()
        self.assertEqual(result.sources_failed, 1)
        self.assertEqual(result.source_results[1].status, "success")

    async def test_all_source_failures_preserve_previous_stories(self):
        previous = build_stories_from_articles([article()]).stories
        set_latest_stories(previous)
        with patch("app.services.collector.HYPE_SOURCES", [source("bad", error=TimeoutError())]), self.assertLogs("app.services.collector", level="ERROR"):
            result = await collect_articles()
        self.assertEqual((result.sources_failed, result.articles_total, result.stories_total), (1, 0, 0))
        self.assertEqual(get_latest_stories(), previous)

    async def test_successful_empty_collection_is_not_a_failure(self):
        set_latest_stories(build_stories_from_articles([article()]).stories)
        with patch("app.services.collector.HYPE_SOURCES", [source("empty")]):
            result = await collect_articles()
        self.assertEqual((result.sources_failed, result.articles_total), (0, 0))
        self.assertEqual(result.source_results[0].status, "success")
        self.assertEqual(get_latest_stories(), [])

    async def test_corrected_score_reaches_editorial_queue(self):
        set_latest_stories(build_stories_from_articles([article(), article("2", "A and B", source="Source Two")]).stories)
        queue = get_editorial_queue_response()
        self.assertEqual(queue.stories[0].similarity_score, 77)
        self.assertEqual(queue.stories[0].confidence_score, 57)


class APIContractTests(unittest.TestCase):
    def setUp(self):
        self.previous = get_latest_stories()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        set_latest_stories(self.previous)

    def test_collect_contract_retains_existing_fields_and_adds_source_results(self):
        with patch("app.services.collector.HYPE_SOURCES", [source("one", [post(1, "2026-10-30T10:00:00Z")])]):
            response = self.client.get("/api/collect?limit_per_source=5")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue({"sources_processed", "sources_failed", "articles_total", "articles", "story_candidates_total", "stories_total", "stories"} <= payload.keys())
        self.assertEqual(payload["source_results"][0]["status"], "success")
        summary = payload["stories"][0]
        self.assertEqual(set(summary), {"id", "headline", "sources", "article_count", "similarity_score", "status", "published_at"})
        self.assertEqual(self.client.get("/api/stories").json()["stories"], payload["stories"])

    def test_collect_validation_is_preserved(self):
        for limit in [0, 51]:
            self.assertEqual(self.client.get(f"/api/collect?limit_per_source={limit}").status_code, 422)

    def test_all_failure_stays_http_200_with_explicit_failure_counts(self):
        with patch("app.services.collector.HYPE_SOURCES", [source("bad", error=TimeoutError())]), self.assertLogs("app.services.collector", level="ERROR"):
            response = self.client.get("/api/collect")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sources_failed"], 1)
        self.assertEqual(response.json()["source_results"][0]["status"], "failed")
