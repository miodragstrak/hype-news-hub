from concurrent.futures import ThreadPoolExecutor
import asyncio
import secrets
import threading
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.config.sources import SourceConfig
from app.core.config import Settings
from app.database.runtime_security import assert_runtime_role, provision_runtime_role
from app.main import create_app
from app.repositories.news_repository import CollectionWriter
from app.models import ArticleIdentity, CollectedArticle, CollectionRun, CollectionSourceResult, NewsSource, Story, StoryArticle
from app.services.story_service import get_latest_stories, set_latest_stories
from tests.integration.test_postgresql import PostgresCase


def post(key="1", url="https://source.invalid/item", title="Regional music festival opens tonight", **values):
    return {"external_id": key, "url": url, "title": title, "published_at": "2026-10-30T12:00:00Z",
            "categories": ["Entertainment"], "content": "Original source body", "raw": {"original_id": key}, **values}


def source(name="one", posts=None, error=None, url=None, connector=None):
    client = connector or AsyncMock()
    if connector is None:
        client.fetch_latest.return_value = posts or []
        client.fetch_latest.side_effect = error
    return SourceConfig(name, url or f"https://{name}.invalid", "wordpress", lambda _: client)


class PersistentCollectionCase(PostgresCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        owner = Settings(_env_file=None)
        cls.role = "hnh_runtime_test_" + secrets.token_hex(6)
        password = secrets.token_hex(32)
        provision_runtime_role(owner, cls.role, password)
        cls.addClassCleanup(cls.remove_runtime_role)
        cls.runtime_config = owner.model_copy(update={"news_storage_backend": "postgres", "postgres_user": cls.role,
                                                       "postgres_password": SecretStr(password)})

    @classmethod
    def remove_runtime_role(cls):
        with cls.engine.begin() as connection:
            connection.execute(text(f'DROP OWNED BY "{cls.role}"'))
            connection.execute(text(f'DROP ROLE "{cls.role}"'))

    def setUp(self):
        self.previous_memory = get_latest_stories()
        self.application = create_app(self.runtime_config)
        self.repository = self.application.state.news_repository
        self.client = TestClient(self.application)

    def tearDown(self):
        self.client.close()
        if "engine" in self.repository.__dict__:
            self.repository.engine.dispose()
        set_latest_stories(self.previous_memory)
        with self.engine.begin() as connection:
            from app.database.base import Base
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())

    def collect(self, sources):
        with patch("app.services.collector.HYPE_SOURCES", sources):
            return self.client.get("/api/collect")

    def count(self, model):
        with self.factory() as session:
            return session.scalar(select(func.count()).select_from(model))


class PersistentCollectionTests(PersistentCollectionCase):
    def test_first_collection_and_existing_response_contract(self):
        self.assertEqual(self.client.get("/api/stories").headers["X-Collection-State"], "never_collected")
        response = self.collect([source(posts=[post()])])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["X-Collection-State"], "completed")
        self.assertEqual(response.headers["X-Collection-New-Articles"], "1")
        body = response.json()
        self.assertEqual(set(body), {"sources_processed", "sources_failed", "articles_total", "articles", "story_candidates_total", "stories_total", "stories", "source_results"})
        self.assertEqual(body["articles"][0]["raw"], {"original_id": "1"})
        self.assertEqual(body["articles"][0]["content"], "Original source body")
        self.assertEqual(body["articles"][0]["source"], "one")
        self.assertEqual(body["articles"][0]["url"], "https://source.invalid/item")
        self.assertEqual(self.client.get("/api/stories").json()["stories"], body["stories"])
        self.assertEqual((self.count(NewsSource), self.count(CollectedArticle), self.count(Story), self.count(StoryArticle)), (1, 1, 1, 1))

    def test_repeated_collection_reuses_source_article_story_and_membership(self):
        configured = [source(posts=[post()])]
        first, second = self.collect(configured), self.collect(configured)
        self.assertEqual(first.json()["stories"], second.json()["stories"])
        self.assertEqual(second.headers["X-Collection-New-Articles"], "0")
        self.assertEqual(second.json()["articles_total"], 1)
        self.assertEqual((self.count(NewsSource), self.count(CollectedArticle), self.count(StoryArticle), self.count(CollectionRun)), (1, 1, 1, 2))

    def test_source_url_variants_keep_stable_source_identity(self):
        self.collect([source(url="HTTPS://ONE.INVALID:443/", posts=[post()])])
        result = self.collect([source(url="https://one.invalid", posts=[post()])])
        self.assertEqual(result.headers["X-Collection-New-Articles"], "0")
        self.assertEqual(self.count(NewsSource), 1)

    def test_updates_and_historical_aliases_keep_original_url_and_story(self):
        original = self.collect([source(posts=[post()])]).json()["stories"][0]["id"]
        changed = post("new-id", url="https://source.invalid/item/?utm_source=x#anchor", title="Festival announces updated programme", content="Updated body")
        updated = self.collect([source(posts=[changed])])
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["articles"][0]["content"], "Updated body")
        self.assertEqual(updated.json()["stories"][0]["headline"], changed["title"])
        self.collect([source(posts=[post("new-id", url="https://source.invalid/new-location", content="Latest body")])])
        result = self.collect([source(posts=[post("", url="https://source.invalid/item")])])
        self.assertEqual(result.headers["X-Collection-New-Articles"], "0")
        self.assertEqual(result.json()["stories"][0]["id"], original)
        self.assertEqual(self.count(CollectedArticle), 1)
        with self.factory() as session:
            row = session.scalars(select(CollectedArticle)).one()
            self.assertEqual(row.url, "https://source.invalid/item")
            self.assertEqual(row.external_id, "1")
            self.assertGreaterEqual(session.scalar(select(func.count()).select_from(ArticleIdentity)), 5)

    def test_partial_and_total_source_failures_preserve_previous_articles(self):
        first = self.collect([source(posts=[post()])]).json()["stories"][0]["id"]
        response = self.collect([source(error=TimeoutError()), source("two", [post("2", "https://two.invalid/item")])])
        self.assertEqual(response.headers["X-Collection-State"], "partial")
        self.assertEqual(response.json()["sources_failed"], 1)
        self.assertEqual(self.count(CollectedArticle), 2)
        self.assertEqual(self.client.get("/api/stories").json()["stories"][0]["id"], first)
        failed = self.collect([source(error=TimeoutError())])
        self.assertEqual(failed.status_code, 200)
        self.assertEqual(failed.headers["X-Collection-State"], "failed")
        self.assertEqual(failed.json()["articles"], [])
        self.assertEqual(self.count(CollectedArticle), 2)
        with self.factory() as session:
            results = list(session.scalars(select(CollectionSourceResult).where(CollectionSourceResult.status == "failed")))
            self.assertEqual(len(results), 2)
            self.assertTrue(all(result.error and result.finished_at for result in results))

    def test_successful_empty_collection_has_history_and_keeps_persisted_feed(self):
        empty = self.collect([source()])
        self.assertEqual(empty.headers["X-Collection-State"], "completed")
        self.assertEqual(empty.headers["X-Collection-New-Articles"], "0")
        self.assertEqual(empty.json()["articles"], [])
        self.collect([source(posts=[post()])])
        self.collect([source()])
        self.assertEqual(self.client.get("/api/stories").json()["stories_total"], 1)

    def test_restart_reloads_queue_workspace_and_story_identifiers(self):
        response = self.collect([source(posts=[post()])])
        story_id = response.json()["stories"][0]["id"]
        self.repository.engine.dispose()
        set_latest_stories([])
        restarted = create_app(self.runtime_config)
        try:
            with TestClient(restarted) as client:
                self.assertEqual(client.get("/api/stories").json()["stories"][0]["id"], story_id)
                self.assertEqual(client.get("/api/editorial-queue").json()["stories"][0]["id"], story_id)
                workspace = client.get(f"/api/editorial-stories/{story_id}")
                self.assertEqual(workspace.status_code, 200)
                self.assertEqual(workspace.json()["source_articles"][0]["content"], "Original source body")
                self.assertEqual(client.post(f"/api/editorial-stories/{story_id}/generate-demo-draft").json()["serbian_draft"]["status"], "demo_generated")
        finally:
            restarted.state.news_repository.engine.dispose()

    def test_source_transaction_rolls_back_every_row_but_keeps_other_sources(self):
        bad = [post("2", "https://bad.invalid/2"), post("3", "https://bad.invalid/3", language="x" * 50)]
        result = self.collect([source(posts=[post()]), source("bad", bad)])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.headers["X-Collection-State"], "partial")
        self.assertEqual(self.count(CollectedArticle), 1)
        self.assertEqual(self.count(StoryArticle), 1)
        with self.factory() as session:
            run = session.scalars(select(CollectionRun)).one()
            self.assertEqual((run.articles_total, run.articles_new, run.sources_failed), (1, 1, 1))

    def test_conflicting_identities_fail_source_without_arbitrary_merges(self):
        self.collect([source(posts=[post("1", "https://one.invalid/a"), post("2", "https://one.invalid/b")])])
        count = self.count(ArticleIdentity)
        response = self.collect([source(posts=[post("3", "https://one.invalid/c"), post("1", "https://one.invalid/b")])])
        self.assertEqual(response.headers["X-Collection-State"], "failed")
        self.assertEqual((self.count(CollectedArticle), self.count(ArticleIdentity)), (2, count))

    def test_long_unicode_identifiers_and_urls_never_index_unbounded_values(self):
        token = secrets.token_hex(6000)
        configured = [source(url="https://one.invalid/" + token, posts=[post("ć" + token, "https://one.invalid/" + token)])]
        self.assertEqual(self.collect(configured).headers["X-Collection-New-Articles"], "1")
        repeated = self.collect(configured)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.headers["X-Collection-New-Articles"], "0")
        self.assertEqual(self.count(CollectedArticle), 1)
        with self.factory() as session:
            row = session.scalars(select(CollectedArticle)).one()
            self.assertEqual(len(row.external_id_key), 64)
            self.assertEqual(len(row.url), len("https://one.invalid/") + len(token))

    def test_concurrent_collection_returns_busy_without_duplicate_work(self):
        entered, release = threading.Event(), threading.Event()
        async def slow_fetch(**kwargs):
            entered.set()
            for _ in range(1000):
                if release.is_set():
                    return [post()]
                await asyncio.sleep(.01)
            raise TimeoutError("Test release timeout")
        connector = AsyncMock()
        connector.fetch_latest.side_effect = slow_fetch
        with patch("app.services.collector.HYPE_SOURCES", [source(connector=connector)]), ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(self.client.get, "/api/collect")
            try:
                self.assertTrue(entered.wait(5))
                second = self.client.get("/api/collect")
                self.assertEqual(second.status_code, 409, second.text)
                self.assertEqual(second.headers["X-Collection-State"], "running")
            finally:
                release.set()
            self.assertEqual(first.result(timeout=10).status_code, 200)
        self.assertEqual((self.count(CollectedArticle), self.count(CollectionRun)), (1, 1))
        self.assertEqual(self.collect([source(posts=[post()])]).status_code, 200)  # lock was released

    def test_orphaned_run_is_recovered_without_deleting_committed_data(self):
        self.collect([source(posts=[post()])])
        with self.factory.begin() as session:
            previous = CollectionRun()
            session.add(previous)
            session.flush()
            source_row = session.scalars(select(NewsSource)).one()
            session.add(CollectionSourceResult(run_id=previous.id, source_id=source_row.id))
            identity = previous.id
        self.collect([source()])
        with self.factory() as session:
            previous = session.get(CollectionRun, identity)
            self.assertEqual(previous.status, "failed")
            self.assertIn("interrupted", previous.error)
            self.assertEqual(previous.source_results[0].status, "failed")
        self.assertEqual(self.count(CollectedArticle), 1)

    def test_runtime_role_can_crud_but_cannot_ddl_truncate_or_read_migration_table(self):
        self.assertEqual(self.collect([source(posts=[post()])]).status_code, 200)
        with self.repository.engine.begin() as connection:
            assert_runtime_role(connection)
        for statement in ("CREATE TABLE forbidden (id integer)", "ALTER TABLE stories ADD COLUMN forbidden text",
                          "DROP TABLE stories CASCADE", "TRUNCATE stories CASCADE", "CREATE ROLE forbidden",
                          "SELECT * FROM alembic_version"):
            with self.subTest(statement=statement), self.assertRaises(SQLAlchemyError):
                with self.repository.engine.begin() as connection:
                    connection.execute(text(statement))
        with self.repository.engine.begin() as connection:
            connection.execute(text("UPDATE stories SET headline = headline"))
            connection.execute(text("DELETE FROM stories WHERE false"))

    def test_schema_owner_credentials_are_rejected_by_api(self):
        application = create_app(Settings(_env_file=None, news_storage_backend="postgres"))
        try:
            with TestClient(application) as client:
                self.assertEqual(client.get("/api/stories").status_code, 503)
        finally:
            application.state.news_repository.engine.dispose()

    def test_duplicate_input_is_not_false_multi_source_corroboration(self):
        result = self.collect([source(posts=[post(), post()])])
        self.assertEqual(result.json()["articles_total"], 1)
        self.assertEqual(result.json()["stories"][0]["article_count"], 1)
        self.assertEqual(result.json()["stories"][0]["similarity_score"], 0)
        self.assertEqual(result.headers["X-Collection-New-Articles"], "1")

    def test_same_identifiers_from_two_sources_retain_independent_articles(self):
        configured = [source(posts=[post()]), source("two", [post()])]
        result = self.collect(configured)
        self.assertEqual(self.count(CollectedArticle), 2)
        self.assertEqual(result.json()["stories_total"], 1)
        self.assertEqual(result.json()["stories"][0]["sources"], ["one", "two"])
        self.assertEqual(result.json()["stories"][0]["similarity_score"], 100)
        repeated = self.collect(list(reversed(configured)))
        self.assertEqual(repeated.json()["stories"][0]["id"], result.json()["stories"][0]["id"])
        self.assertEqual(repeated.headers["X-Collection-New-Articles"], "0")

    def test_storage_error_returns_503_and_retry_reuses_committed_rows(self):
        original = CollectionWriter._upsert_article
        def fail_second(writer, session, source_id, incoming):
            if incoming.external_id == "2":
                raise OperationalError("synthetic disconnection", {}, Exception("offline"))
            return original(writer, session, source_id, incoming)
        configured = [source(posts=[post()]), source("two", [post("2")])]
        with patch.object(CollectionWriter, "_upsert_article", fail_second):
            result = self.collect(configured)
        self.assertEqual(result.status_code, 503)
        self.assertEqual(self.count(CollectedArticle), 1)
        retry = self.collect(configured)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.headers["X-Collection-New-Articles"], "1")
        self.assertEqual(self.count(CollectedArticle), 2)

    def test_provisioning_is_repeatable_and_runtime_cannot_inherit_owner(self):
        owner = Settings(_env_file=None)
        provision_runtime_role(owner, self.role, self.runtime_config.postgres_password.get_secret_value())
        quoted_owner = self.engine.dialect.identifier_preparer.quote(owner.postgres_user)
        with self.engine.begin() as connection:
            connection.execute(text(f'GRANT {quoted_owner} TO "{self.role}"'))
        try:
            self.assertEqual(self.client.get("/api/stories").status_code, 503)
            with self.assertRaises(SQLAlchemyError):
                provision_runtime_role(owner, self.role, self.runtime_config.postgres_password.get_secret_value())
        finally:
            with self.engine.begin() as connection:
                connection.execute(text(f'REVOKE {quoted_owner} FROM "{self.role}"'))

    def test_interrupted_finalization_is_not_recorded_as_completed(self):
        original = CollectionWriter.finish
        def interrupt(writer, error=None):
            if error is None:
                raise OperationalError("synthetic finalization error", {}, Exception("offline"))
            return original(writer, error=error)
        with patch.object(CollectionWriter, "finish", interrupt):
            response = self.collect([source(posts=[post()])])
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.count(CollectedArticle), 1)
        with self.factory() as session:
            run = session.scalars(select(CollectionRun)).one()
            self.assertEqual(run.status, "partial")
            self.assertIsNotNone(run.error)
            self.assertEqual(run.sources_failed, 0)

    def test_reader_uses_consistent_snapshot_while_collection_updates_story(self):
        self.collect([source(posts=[post(title="Original title")])])
        with self.repository.read() as session:
            self.assertEqual(session.scalar(select(CollectedArticle.title)), "Original title")
            updated = self.collect([source(posts=[post(title="Updated title")])])
            self.assertEqual(updated.status_code, 200, updated.text)
            self.assertEqual(session.scalar(select(CollectedArticle.title)), "Original title")
            self.assertEqual(session.scalar(select(Story.headline)), "Original title")
        self.assertEqual(self.client.get("/api/stories").json()["stories"][0]["headline"], "Updated title")

    def test_database_unavailable_returns_503_for_reads_and_collection(self):
        configured = self.runtime_config.model_copy(update={"postgres_host": "127.0.0.1", "postgres_port": 1, "postgres_connect_timeout_seconds": 1})
        application = create_app(configured)
        try:
            with TestClient(application) as client:
                for path in ("/api/stories", "/api/editorial-queue", "/api/collect"):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.headers["X-Collection-State"], "unavailable")
                    self.assertNotIn(self.runtime_config.postgres_password.get_secret_value(), response.text)
        finally:
            application.state.news_repository.engine.dispose()


class CollectionMigrationDataTests(PostgresCase):
    def test_upgrade_preserves_foundation_rows_and_backfills_identity_aliases(self):
        from alembic import command
        from tests.integration.test_postgresql import alembic_config
        with self.engine.begin() as connection:
            config = alembic_config(connection)
            command.downgrade(config, "20261030_01")
            source_id = connection.execute(text("INSERT INTO news_sources (name, url) VALUES ('Legacy', 'https://legacy.invalid') RETURNING id")).scalar_one()
            article_id = connection.execute(text("INSERT INTO collected_articles (source_id, external_id, url, canonical_url, title) VALUES (:source, '00042', 'https://legacy.invalid/item', 'https://legacy.invalid/item', 'Legacy article') RETURNING id"), {"source": source_id}).scalar_one()
            command.upgrade(config, "head")
            self.assertEqual(connection.execute(text("SELECT id FROM collected_articles")).scalar_one(), article_id)
            self.assertEqual(connection.execute(text("SELECT count(*) FROM article_identities")).scalar_one(), 2)
            self.assertEqual(connection.execute(text("SELECT length(external_id_key) FROM collected_articles")).scalar_one(), 64)
            command.check(config)
