"""Opt-in integration tests. Only an EMPTY hype_news_hub_test database is accepted."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import delete, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.database.base import Base
from app.database.session import create_database_engine, create_session_factory, get_db, session_scope
from app.models import CollectedArticle, CollectionRun, CollectionSourceResult, NewsSource, Story, StoryArticle


def alembic_config(connection):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_TESTS") == "1", "Set RUN_POSTGRES_TESTS=1 for the isolated PostgreSQL test database")
class PostgresCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = Settings(_env_file=None)
        if config.postgres_db != "hype_news_hub_test":
            raise RuntimeError("Refusing integration tests outside the dedicated hype_news_hub_test database.")
        cls.engine = create_database_engine(config)
        cls.addClassCleanup(cls.engine.dispose)
        with cls.engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            if tables - {"alembic_version"} or inspect(connection).get_view_names():
                raise RuntimeError("Integration tests require an empty test database; existing objects will not be deleted.")
            if "alembic_version" in tables and connection.execute(text("SELECT version_num FROM alembic_version")).first():
                raise RuntimeError("Integration tests require an unmigrated test database.")
        cls.factory = create_session_factory(cls.engine)
        with cls.engine.begin() as connection:
            command.upgrade(alembic_config(connection), "head")
        cls.addClassCleanup(cls.remove_test_schema)

    @classmethod
    def remove_test_schema(cls):
        with cls.engine.begin() as connection:
            command.downgrade(alembic_config(connection), "base")


class PostgreSQLModelTests(PostgresCase):
    def setUp(self):
        self.session = self.factory()
        self.source = NewsSource(name="Hype Serbia", url="https://source.invalid")
        self.run = CollectionRun()
        self.session.add_all([self.source, self.run])
        self.session.flush()

    def tearDown(self):
        self.session.rollback()
        self.session.close()
        # Only tables created in this explicitly isolated, initially empty DB.
        with self.engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(delete(table))

    def article(self, **overrides):
        values = {"source_id": self.source.id, "url": "https://source.invalid/article/" + uuid4().hex,
                  "title": "Original regional headline", "first_seen_run_id": self.run.id}
        values.update(overrides)
        article = CollectedArticle(**values)
        self.session.add(article)
        self.session.flush()
        return article

    def test_uuid_identity_and_full_original_data_survive_new_sessions(self):
        published = datetime(2026, 10, 30, 14, tzinfo=timezone(timedelta(hours=2)))
        article = self.article(external_id="000123", canonical_url="https://source.invalid/canonical",
                               excerpt="Source excerpt", content="Original source body", raw={"id": 123, "nested": {"verified": True}},
                               categories=["Zabava", "Region"], language="sr", published_at=published)
        identity = article.id
        self.session.commit()
        with self.factory() as other:
            stored = other.get(CollectedArticle, identity)
            self.assertIsInstance(stored.id, UUID)
            self.assertEqual(stored.external_id, "000123")
            self.assertEqual(stored.content, "Original source body")
            self.assertEqual(stored.raw["nested"], {"verified": True})
            self.assertEqual(stored.categories, ["Zabava", "Region"])
            self.assertEqual(stored.published_at, published)
            self.assertIsNotNone(stored.created_at.tzinfo)
            self.assertEqual(stored.first_seen_run_id, self.run.id)
            self.assertEqual(stored.source.name, "Hype Serbia")

    def test_source_url_is_unique(self):
        self.session.add(NewsSource(name="Renamed source", url=self.source.url))
        with self.assertRaises(IntegrityError):
            self.session.flush()

    def test_external_id_is_unique_within_source(self):
        self.article(external_id="42")
        with self.assertRaises(IntegrityError):
            self.article(external_id="42")

    def test_original_url_is_unique_within_source(self):
        article = self.article()
        with self.assertRaises(IntegrityError):
            self.article(url=article.url)

    def test_canonical_url_is_unique_within_source(self):
        self.article(canonical_url="https://source.invalid/canonical")
        with self.assertRaises(IntegrityError):
            self.article(canonical_url="https://source.invalid/canonical")

    def test_same_identifiers_across_sources_preserve_both_attributions(self):
        other = NewsSource(name="Hype Croatia", url="https://other.invalid")
        self.session.add(other)
        self.session.flush()
        one = self.article(external_id="42", url="https://common.invalid/item", canonical_url="https://common.invalid/item")
        two = self.article(source_id=other.id, external_id="42", url=one.url, canonical_url=one.canonical_url)
        self.assertNotEqual(one.id, two.id)

    def test_unknown_identifiers_use_null_without_collision(self):
        self.assertNotEqual(self.article().id, self.article().id)

    def test_unavailable_raw_payload_is_sql_null(self):
        article = self.article(raw=None)
        self.assertTrue(self.session.execute(
            text("SELECT raw IS NULL FROM collected_articles WHERE id = :id"), {"id": article.id},
        ).scalar_one())

    def test_blank_metadata_and_bad_hashes_are_rejected(self):
        cases = [{"title": " "}, {"url": " "}, {"canonical_url": " "}, {"content_hash": "bad-hash"}]
        for values in cases:
            with self.subTest(values=values), self.assertRaises(IntegrityError):
                with self.session.begin_nested():
                    self.article(**values)

    def test_empty_external_id_is_rejected(self):
        with self.assertRaises(IntegrityError):
            self.article(external_id=" ")

    def test_foreign_keys_reject_missing_sources(self):
        with self.assertRaises(IntegrityError):
            self.article(source_id=uuid4())

    def test_source_cannot_be_deleted_while_attribution_is_referenced(self):
        self.article()
        with self.assertRaises(IntegrityError):
            self.session.execute(delete(NewsSource).where(NewsSource.id == self.source.id))

    def test_story_membership_round_trip_and_primary_article(self):
        story = Story(headline="Grouped story", similarity_score=77, status="merged")
        article = self.article()
        story.article_links.append(StoryArticle(article=article, is_primary=True, match_score=77))
        self.session.add(story)
        self.session.commit()
        with self.factory() as other:
            stored = other.get(Story, story.id)
            self.assertEqual(stored.article_links[0].article.id, article.id)
            self.assertTrue(stored.article_links[0].is_primary)
            self.assertEqual(stored.article_links[0].match_score, 77)

    def test_article_cannot_belong_to_two_current_stories(self):
        article = self.article()
        one, two = Story(headline="One"), Story(headline="Two")
        self.session.add_all([one, two])
        self.session.flush()
        self.session.add(StoryArticle(story_id=one.id, article_id=article.id))
        self.session.flush()
        self.session.add(StoryArticle(story_id=two.id, article_id=article.id))
        with self.assertRaises(IntegrityError):
            self.session.flush()

    def test_story_cannot_have_two_primary_articles(self):
        story = Story(headline="One")
        self.session.add(story)
        self.session.flush()
        self.session.add(StoryArticle(story_id=story.id, article_id=self.article().id, is_primary=True))
        self.session.flush()
        self.session.add(StoryArticle(story_id=story.id, article_id=self.article().id, is_primary=True))
        with self.assertRaises(IntegrityError):
            self.session.flush()

    def test_out_of_range_story_scores_are_rejected(self):
        self.session.add(Story(headline="Invalid", similarity_score=101))
        with self.assertRaises(IntegrityError):
            self.session.flush()

    def test_story_delete_removes_memberships_but_keeps_articles(self):
        story = Story(headline="One")
        article = self.article()
        self.session.add(story)
        self.session.flush()
        self.session.add(StoryArticle(story_id=story.id, article_id=article.id))
        self.session.flush()
        self.session.execute(delete(Story).where(Story.id == story.id))
        self.assertIsNotNone(self.session.get(CollectedArticle, article.id))
        self.assertEqual(self.session.scalars(select(StoryArticle)).all(), [])

    def test_per_source_result_is_unique_per_run(self):
        self.session.add(CollectionSourceResult(run_id=self.run.id, source_id=self.source.id))
        self.session.flush()
        self.session.add(CollectionSourceResult(run_id=self.run.id, source_id=self.source.id))
        with self.assertRaises(IntegrityError):
            self.session.flush()

    def test_finished_run_and_source_failure_details_are_persisted(self):
        start = datetime.now(timezone.utc)
        self.run.started_at = start
        self.run.finished_at = start + timedelta(seconds=1)
        self.run.status = "failed"
        self.run.sources_processed = self.run.sources_failed = 1
        result = CollectionSourceResult(run_id=self.run.id, source_id=self.source.id, status="failed",
                                        started_at=start, finished_at=self.run.finished_at, error="Source timed out")
        self.session.add(result)
        self.session.commit()
        with self.factory() as other:
            stored = other.get(CollectionRun, self.run.id)
            self.assertEqual(stored.source_results[0].error, "Source timed out")

    def test_invalid_run_status_is_rejected(self):
        self.run.status = "made_up"
        with self.assertRaises(IntegrityError):
            self.session.flush()

    def test_failed_source_count_cannot_exceed_processed_count(self):
        self.run.sources_failed = 1
        with self.assertRaises(IntegrityError):
            self.session.flush()

    def test_completed_run_requires_finish_timestamp(self):
        self.run.status = "completed"
        with self.assertRaises(IntegrityError):
            self.session.flush()

    def test_negative_counts_and_invalid_limits_are_rejected(self):
        cases = [{"sources_processed": -1}, {"articles_total": -1}, {"stories_total": -1},
                 {"story_candidates_total": -1}, {"limit_per_source": 0}, {"limit_per_source": 51}]
        for values in cases:
            with self.subTest(values=values), self.assertRaises(IntegrityError):
                with self.session.begin_nested():
                    self.session.add(CollectionRun(**values))
                    self.session.flush()

    def test_run_finish_cannot_precede_start(self):
        self.run.status = "completed"
        self.run.finished_at = self.run.started_at - timedelta(seconds=1)
        with self.assertRaises(IntegrityError):
            self.session.flush()

    def test_deleting_run_cascades_results_and_clears_optional_first_seen_link(self):
        article = self.article()
        self.session.add(CollectionSourceResult(run_id=self.run.id, source_id=self.source.id))
        self.session.flush()
        self.session.execute(delete(CollectionRun).where(CollectionRun.id == self.run.id))
        self.session.expire(article)
        self.assertIsNone(article.first_seen_run_id)
        self.assertEqual(self.session.scalars(select(CollectionSourceResult)).all(), [])

    def test_finished_source_result_requires_timestamps(self):
        self.session.add(CollectionSourceResult(run_id=self.run.id, source_id=self.source.id, status="success"))
        with self.assertRaises(IntegrityError):
            self.session.flush()

    def test_session_scope_commits_and_rolls_back(self):
        with session_scope(self.factory) as session:
            source = NewsSource(name="Committed", url="https://committed.invalid")
            session.add(source)
        with self.assertRaisesRegex(RuntimeError, "abort"):
            with session_scope(self.factory) as session:
                session.add(NewsSource(name="Rollback", url="https://rollback.invalid"))
                session.flush()
                raise RuntimeError("abort")
        with self.factory() as session:
            self.assertIsNotNone(session.get(NewsSource, source.id))
            self.assertEqual(session.scalars(select(NewsSource).where(NewsSource.url == "https://rollback.invalid")).all(), [])

    def test_dependency_closes_and_rolls_back_uncommitted_work(self):
        with patch("app.database.session.get_engine", return_value=self.engine):
            dependency = get_db()
            session = next(dependency)
            session.add(NewsSource(name="Uncommitted", url="https://uncommitted.invalid"))
            session.flush()
            dependency.close()
        with self.factory() as other:
            self.assertEqual(other.scalars(select(NewsSource).where(NewsSource.url == "https://uncommitted.invalid")).all(), [])

    def test_database_generates_ids_for_non_orm_inserts(self):
        identity = self.session.execute(text(
            "INSERT INTO news_sources (name, url) VALUES ('SQL source', 'https://sql.invalid') RETURNING id"
        )).scalar_one()
        self.assertIsInstance(identity, UUID)


class PostgreSQLMigrationTests(PostgresCase):
    def test_upgrade_check_downgrade_and_reupgrade(self):
        with self.engine.begin() as connection:
            config = alembic_config(connection)
            self.assertEqual(set(inspect(connection).get_table_names()) - {"alembic_version"}, set(Base.metadata.tables))
            command.upgrade(config, "head")
            command.check(config)
            command.downgrade(config, "base")
            self.assertEqual(set(inspect(connection).get_table_names()), {"alembic_version"})
            command.upgrade(config, "head")
            command.check(config)
