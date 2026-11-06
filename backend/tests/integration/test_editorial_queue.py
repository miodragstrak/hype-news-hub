"""Private queue requests against real PostgreSQL and restricted runtime grants."""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import event, text

from app.core.editorial_security import EditorialPrincipal, EditorialRole
from app.models import (
    AIProcessingEvent,
    AIProcessingRun,
    CollectedArticle,
    Story,
    StoryArticle,
)
from app.schemas.ai_processing import CreateSuggestion
from app.services.ai_processing import AIProcessing
from integration.test_ai_processing import AIProcessingCase

QUEUE = "/api/editorial/queue"


class PrivateEditorialQueueTests(AIProcessingCase):
    def queue(self, **params):
        response = self.private.get(QUEUE, params=params, headers=self.headers("reader"))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return response.json()

    def reserve(self, expired=False):
        service = AIProcessing(self.private_app.state.news_repository,
            EditorialPrincipal("urn:hnh:test", "test-editor", frozenset({EditorialRole.EDITOR})), self.provider)
        if expired:
            with patch("app.services.ai_processing.datetime") as clock:
                clock.now.return_value = datetime.now(UTC) - timedelta(minutes=5)
                return service.reserve(CreateSuggestion(**self.creation()))[0]
        return service.reserve(CreateSuggestion(**self.creation()))[0]

    def add_stories(self, number):
        with self.factory.begin() as session:
            for index in range(number):
                article = CollectedArticle(source_id=UUID(self.source_id), url=f"https://one.invalid/queue-{index}",
                    title=f"Queue story {index}")
                story = Story(headline=article.title, published_at=datetime(2026, 11, 1, tzinfo=UTC))
                session.add_all([article, story])
                session.flush()
                session.add(StoryArticle(story_id=story.id, article_id=article.id, is_primary=True))

    def test_authentication_and_read_permission(self):
        self.assertEqual(self.private.get(QUEUE).status_code, 401)
        self.assertEqual(self.private.get(QUEUE, headers={"Authorization": "Bearer bad"}).status_code, 401)
        self.assertEqual(self.private.get(QUEUE, headers=self.headers("no-roles") | {"X-Role": "administrator"}).status_code, 403)
        for role in ("reader", "editor", "reviewer", "publisher", "administrator"):
            self.assertEqual(self.private.get(QUEUE, headers=self.headers(role)).status_code, 200)
        self.assertEqual(self.provider.calls, [])

    def test_empty_queue(self):
        with self.engine.begin() as connection:
            connection.execute(text("DELETE FROM public.story_articles"))
            connection.execute(text("DELETE FROM public.stories"))
        self.assertEqual(self.queue(), {"stories": [], "stories_total": 0, "limit": 20, "offset": 0, "has_more": False})

    def test_no_suggestion_preserves_existing_intelligence_and_collection_status(self):
        private = self.queue()["stories"][0]
        public = self.client.get("/api/editorial-queue").json()["stories"][0]
        self.assertEqual({key: private[key] for key in public}, public)
        self.assertEqual(private["status"], "collected")
        self.assertIsNone(private["editorial"])
        self.assertEqual(private["ai"], {"has_suggestion": False, "latest_suggestion_id": None,
            "status": None, "created_at": None, "completed_at": None, "recovery_required": False})

    def test_real_editorial_status_remains_distinct_from_collection_and_ai(self):
        self.create()
        response = self.private.post("/api/editorial/drafts", headers=self.headers(), json={
            "command_id": str(uuid4()), "expected_revision": 0, "story_id": self.story_id, "target_locale": "sr-Latn",
            "payload": {"headline": "Urednički naslov", "body": "Proveren urednički tekst.", "excerpt": "Sažetak.",
                "slug": "urednicki-naslov", "categories": ["Zabava"], "tags": [], "images": [],
                "seo": {"title": "Urednički naslov", "description": "Proverene činjenice."},
                "source_attribution": [{"article_id": self.article_id, "source_id": self.source_id}]}})
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        row = self.queue()["stories"][0]
        self.assertEqual(row["status"], "collected")
        self.assertEqual(row["ai"]["status"], "succeeded")
        self.assertEqual(row["editorial"], {"draft_id": result["draft_id"], "status": "editing",
            "revision": result["revision"], "current_version_number": result["version_number"]})

    def test_latest_record_selected_by_creation_time_then_uuid(self):
        first, second = self.create(), self.create()
        row = self.queue()["stories"][0]
        self.assertEqual(row["ai"]["latest_suggestion_id"], second["id"])
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(row["ai"]["created_at"], second["created_at"])
        self.assertEqual(row["ai"]["completed_at"], second["completed_at"])
        # Newer processing records take precedence over older successful results.
        now = datetime.now(UTC) + timedelta(seconds=1)
        with patch("app.services.ai_processing.datetime") as clock:
            clock.now.return_value = now
            a, b = self.reserve(), self.reserve()
        expected = str(max(a.id, b.id))
        latest = self.queue()["stories"][0]["ai"]
        self.assertEqual(latest["latest_suggestion_id"], expected)
        self.assertEqual(latest["status"], "processing")
        self.assertIsNone(latest["completed_at"])

    def test_expired_processing_is_reported_without_recovery_or_mutation(self):
        run = self.reserve(expired=True)
        before = self.count(AIProcessingEvent)
        ai = self.queue()["stories"][0]["ai"]
        self.assertEqual(ai["latest_suggestion_id"], str(run.id))
        self.assertTrue(ai["recovery_required"])
        with self.factory() as session:
            self.assertEqual(session.get(AIProcessingRun, run.id).status, "processing")
        self.assertEqual(self.count(AIProcessingEvent), before)
        self.assertEqual(self.provider.calls, [])

    def test_unexpired_processing_does_not_require_recovery(self):
        self.reserve()
        self.assertFalse(self.queue()["stories"][0]["ai"]["recovery_required"])

    def test_deterministic_pagination_including_equal_and_null_dates(self):
        self.add_stories(5)
        whole = self.queue(limit=50)
        pages = [self.queue(limit=2, offset=offset) for offset in (0, 2, 4)]
        ids = [story["id"] for page in pages for story in page["stories"]]
        self.assertEqual(ids, [story["id"] for story in whole["stories"]])
        self.assertEqual(len(set(ids)), 6)
        self.assertEqual(ids[:5], sorted(ids[:5], reverse=True))
        self.assertEqual([page["has_more"] for page in pages], [True, True, False])
        self.assertTrue(all(page["stories_total"] == 6 for page in pages))
        with self.factory.begin() as session:
            session.get(Story, UUID(ids[0])).published_at = None
        reordered = self.queue(limit=50)
        self.assertEqual(reordered["stories"][-1]["id"], ids[0])
        beyond = self.queue(offset=100)
        self.assertEqual(beyond["stories"], [])
        self.assertEqual(beyond["stories_total"], 6)
        self.assertFalse(beyond["has_more"])

    def test_bounded_pagination(self):
        for params in ({"limit": 0}, {"limit": 51}, {"offset": -1}, {"offset": 1_000_001}, {"limit": "nan"}):
            self.assertEqual(self.private.get(QUEUE, params=params, headers=self.headers()).status_code, 422)

    def test_lightweight_projection_and_fixed_query_count(self):
        self.create()
        statements = []
        engine = self.private_app.state.news_repository.engine
        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)
        event.listen(engine, "before_cursor_execute", capture)
        try:
            body = self.queue(limit=50)
            count = len(statements)
            self.add_stories(12)
            statements.clear()
            self.queue(limit=50)
            self.assertEqual(len(statements), count)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        ai = body["stories"][0]["ai"]
        self.assertEqual(set(ai), {"has_suggestion", "latest_suggestion_id", "status", "created_at", "completed_at", "recovery_required"})
        for statement in statements:
            for forbidden in (".input_payload", ".output", ".actor_", ".command_id", ".content", ".raw"):
                self.assertNotIn(forbidden, statement)
        self.assertNotIn("PRIVATE", str(body))
        self.assertNotIn("input_text", str(body))
