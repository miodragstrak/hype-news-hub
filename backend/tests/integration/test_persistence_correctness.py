"""Correctness regressions use only the guarded, disposable PostgreSQL database."""
import asyncio
import multiprocessing
import time
from unittest.mock import AsyncMock, patch

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from app.core.config import Settings
from app.database.runtime_security import provision_runtime_role
from app.main import create_app
from app.models import CollectedArticle, CollectionRun, NewsSource, Story, StoryArticle
from integration.test_persistent_collection import PersistentCollectionCase, post, source
from tests.integration.test_postgresql import alembic_config


def collect_in_independent_process(config, entered, release, result_pipe):
    """Spawn creates a new interpreter, app, engine and PostgreSQL connection."""
    application = create_app(config)
    async def pause_after_committed_source(**kwargs):
        entered.set()
        for _ in range(1500):
            if release.is_set():
                return []
            await asyncio.sleep(.01)
        raise TimeoutError("Worker test release timeout")
    connector = AsyncMock()
    connector.fetch_latest.side_effect = pause_after_committed_source
    try:
        with TestClient(application) as client, patch("app.services.collector.HYPE_SOURCES", [
            source(posts=[post()]), source("paused", connector=connector),
        ]):
            response = client.get("/api/collect")
            result_pipe.send({"status": response.status_code})
    except BaseException as exc:
        result_pipe.send({"error": type(exc).__name__})
        raise
    finally:
        result_pipe.close()


class PersistenceCorrectnessTests(PersistentCollectionCase):
    def tearDown(self):
        # Stop spawned collectors before the base fixture deletes test rows.
        self.doCleanups()
        super().tearDown()

    def test_recurring_identical_headlines_months_or_years_apart_create_distinct_stories(self):
        identities = set()
        for key, date in (("old", "2020-01-01T12:00:00Z"), ("month", "2020-06-01T12:00:00Z"), ("year", "2026-10-30T12:00:00Z")):
            response = self.collect([source(posts=[post(key, "https://one.invalid/" + key, published_at=date)])])
            self.assertEqual(response.status_code, 200, response.text)
            current = {story["id"] for story in response.json()["stories"]}
            self.assertEqual(len(current - identities), 1)
            identities = current
        self.assertEqual(self.count(Story), 3)
        self.assertEqual(self.count(StoryArticle), 3)

    def test_missing_or_invalid_dates_do_not_create_automatic_memberships(self):
        for index, date in enumerate((None, "not-a-date", "2026-10-30T12:00:00Z")):
            self.collect([source(posts=[post(str(index), f"https://one.invalid/{index}", published_at=date)])])
        self.assertEqual(self.count(Story), 3)
        repeated = self.collect([source(posts=[post("0", "https://one.invalid/0", published_at=None)])])
        self.assertEqual(repeated.headers["X-Collection-New-Articles"], "0")
        self.assertEqual(self.count(Story), 3)

    def test_same_event_reuses_story_without_splitting_existing_members_after_policy_change(self):
        first = self.collect([source(posts=[post()])]).json()["stories"][0]["id"]
        related = source("two", [post("2", "https://two.invalid/item", published_at="2026-10-31T14:00:00+02:00")])
        result = self.collect([related])
        self.assertEqual(result.json()["stories_total"], 1)
        self.assertEqual(result.json()["stories"][0]["id"], first)
        self.repository.config = self.runtime_config.model_copy(update={"story_match_max_gap_hours": 1})
        repeated = self.collect([related])
        self.assertEqual(repeated.json()["stories"][0]["article_count"], 2)
        self.assertEqual(repeated.json()["stories"][0]["id"], first)
        self.collect([source("three", [post("3", "https://three.invalid/item", published_at="2026-10-30T14:00:00Z")])])
        self.assertEqual(self.count(Story), 2)

    def test_naive_source_local_date_is_ineligible_but_explicit_wordpress_gmt_is_reliable(self):
        original = self.collect([source(posts=[post()])]).json()["stories"][0]["id"]
        self.collect([source("local", [post("local", "https://local.invalid/item", published_at="2026-10-30T13:00:00")])])
        self.assertEqual(self.count(Story), 2)
        gmt = "2026-10-30T14:00:00"
        response = self.collect([source("gmt", [post("gmt", "https://gmt.invalid/item", published_at=gmt, raw={"date_gmt": gmt})])])
        self.assertEqual(self.count(Story), 2)
        original_story = next(story for story in response.json()["stories"] if story["id"] == original)
        self.assertEqual(original_story["article_count"], 2)

    def test_empty_and_partial_collection_responses_include_complete_retained_snapshot(self):
        before = self.collect([source(posts=[post()])]).json()["stories"]
        response = self.collect([source(error=TimeoutError()), source("two", [post("new", "https://two.invalid/new", title="A completely different sports championship")])])
        self.assertEqual(response.headers["X-Collection-State"], "partial")
        self.assertEqual(response.json()["stories_total"], 2)
        self.assertIn(before[0]["id"], {item["id"] for item in response.json()["stories"]})
        self.assertEqual(response.json()["stories"], self.client.get("/api/stories").json()["stories"])
        empty = self.collect([source()])
        self.assertEqual(empty.json()["articles_total"], 0)
        self.assertEqual(empty.json()["stories"], response.json()["stories"])
        with self.factory() as session:
            run = session.get(CollectionRun, empty.headers["X-Collection-Run-Id"])
            self.assertEqual(run.stories_total, 0)  # run metrics remain separate from the visible snapshot

    def test_opaque_query_aliases_cannot_overwrite_unrelated_articles(self):
        self.collect([source(posts=[post("1", "https://one.invalid/?id=%FF", title="Original first article")])])
        second = self.collect([source(posts=[post("2", "https://one.invalid/?id=%FE", title="Original second article")])])
        self.assertEqual(second.headers["X-Collection-New-Articles"], "1")
        updated = self.collect([source(posts=[post("2", "https://one.invalid/?id=%fe", title="Updated second article")])])
        self.assertEqual(updated.headers["X-Collection-New-Articles"], "0")
        with self.factory() as session:
            rows = {row.external_id: row for row in session.scalars(select(CollectedArticle))}
            self.assertEqual(set(rows), {"1", "2"})
            self.assertEqual(rows["1"].title, "Original first article")
            self.assertEqual(rows["2"].title, "Updated second article")

    def test_malformed_url_rolls_back_source_batch_and_preserves_prior_data(self):
        self.collect([source(posts=[post()])])
        response = self.collect([source(posts=[post("2", "https://one.invalid/new"), post("3", "https://one.invalid/?id=%G0")])])
        self.assertEqual(response.headers["X-Collection-State"], "failed")
        self.assertEqual(self.count(CollectedArticle), 1)

    def test_unicode_and_encoded_urls_recollect_as_one_article_without_external_id(self):
        first = self.collect([source(posts=[post("", "https://one.invalid/čć?ime=Đorđe")])])
        second = self.collect([source(posts=[post("", "https://one.invalid/%C4%8D%C4%87?ime=%C4%90or%C4%91e")])])
        self.assertEqual(second.headers["X-Collection-New-Articles"], "0")
        self.assertEqual(first.json()["stories"][0]["id"], second.json()["stories"][0]["id"])
        self.assertEqual(self.count(CollectedArticle), 1)

    def test_populated_15a_without_optional_identities_recollects_existing_article_and_story(self):
        with self.engine.begin() as connection:
            config = alembic_config(connection)
            command.downgrade(config, "20261030_01")
            source_id = connection.execute(text("INSERT INTO news_sources (name, url) VALUES ('Legacy', 'HTTPS://ONE.INVALID:443/') RETURNING id")).scalar_one()
            original = "HTTPS://SOURCE.INVALID:443/item/?utm_source=legacy"
            article_id = connection.execute(text("INSERT INTO collected_articles (source_id, url, title) VALUES (:source, :url, 'Legacy article') RETURNING id"), {"source": source_id, "url": original}).scalar_one()
            story_id = connection.execute(text("INSERT INTO stories (headline) VALUES ('Legacy story') RETURNING id")).scalar_one()
            connection.execute(text("INSERT INTO story_articles (story_id, article_id, is_primary) VALUES (:story, :article, true)"), {"story": story_id, "article": article_id})
            command.upgrade(config, "head")
            command.check(config)
        provision_runtime_role(Settings(_env_file=None), self.role, self.runtime_config.postgres_password.get_secret_value())
        response = self.collect([source(posts=[post("", "https://source.invalid/item/", title="Updated legacy article")])])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["X-Collection-New-Articles"], "0")
        self.assertEqual((self.count(NewsSource), self.count(CollectedArticle), self.count(Story)), (1, 1, 1))
        self.assertEqual(response.json()["stories"][0]["id"], str(story_id))
        with self.factory() as session:
            row = session.get(CollectedArticle, article_id)
            self.assertEqual(row.url, original)
            self.assertIsNone(row.external_id)
            self.assertEqual(row.title, "Updated legacy article")

    def _start_worker(self):
        context = multiprocessing.get_context("spawn")
        entered, release = context.Event(), context.Event()
        receive, send = context.Pipe(duplex=False)
        worker = context.Process(target=collect_in_independent_process, args=(self.runtime_config, entered, release, send))
        worker.start()
        send.close()
        self.addCleanup(receive.close)
        def stop_worker():
            if worker.is_alive():
                worker.terminate()
            worker.join(5)
            if worker.is_alive():
                worker.kill()
                worker.join(5)
            worker.close()
        self.addCleanup(stop_worker)
        self.assertTrue(entered.wait(8), "Independent collector did not reach the source pause.")
        return worker, release, receive

    def test_independent_processes_share_collection_lock_and_do_not_duplicate_work(self):
        worker, release, receive = self._start_worker()
        response = self.collect([source(posts=[post()])])
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.count(CollectedArticle), 1)
        release.set()
        self.assertTrue(receive.poll(8))
        self.assertEqual(receive.recv(), {"status": 200})
        worker.join(8)
        self.assertEqual(worker.exitcode, 0)
        retried = self.collect([source(posts=[post()])])
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.headers["X-Collection-New-Articles"], "0")
        self.assertEqual(self.count(CollectionRun), 2)

    def test_terminated_process_releases_lock_and_next_run_recovers_committed_work(self):
        worker, _, _ = self._start_worker()
        worker.terminate()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        deadline = time.monotonic() + 8
        while True:
            response = self.collect([source(posts=[post()])])
            if response.status_code != 409 or time.monotonic() >= deadline:
                break
            time.sleep(.05)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["X-Collection-New-Articles"], "0")
        self.assertEqual(self.count(CollectedArticle), 1)
        with self.factory() as session:
            runs = list(session.scalars(select(CollectionRun).order_by(CollectionRun.started_at)))
            self.assertEqual([run.status for run in runs], ["partial", "completed"])
            self.assertIn("interrupted", runs[0].error)
            self.assertEqual(sorted(result.status for result in runs[0].source_results), ["failed", "success"])


class LegacyIdentityConflictTests(PersistentCollectionCase):
    def _legacy_schema(self, connection):
        config = alembic_config(connection)
        command.downgrade(config, "20261030_01")
        return config

    def test_normalized_legacy_conflict_aborts_before_alias_writes(self):
        with self.engine.begin() as connection:
            config = self._legacy_schema(connection)
            source_id = connection.execute(text("INSERT INTO news_sources (name, url) VALUES ('Legacy', 'https://legacy.invalid') RETURNING id")).scalar_one()
            identities = []
            for url in ("https://legacy.invalid/item/?utm_source=one", "https://legacy.invalid/item"):
                identities.append(connection.execute(text("INSERT INTO collected_articles (source_id, url, title) VALUES (:source, :url, 'Legacy') RETURNING id"), {"source": source_id, "url": url}).scalar_one())
            with self.assertRaisesRegex(RuntimeError, "Article identity conflict") as caught:
                with connection.begin_nested():
                    command.upgrade(config, "head")
            self.assertTrue(all(str(identity) in str(caught.exception) for identity in identities))
            self.assertIn("no aliases were written", str(caught.exception))
            self.assertEqual(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one(), "20261030_01")
            self.assertNotIn("article_identities", inspect(connection).get_table_names())
            self.assertEqual(connection.execute(text("SELECT count(*) FROM collected_articles")).scalar_one(), 2)
            connection.execute(text("DELETE FROM collected_articles"))
            command.upgrade(config, "head")

    def test_normalized_source_conflict_aborts_without_reassigning_provenance(self):
        with self.engine.begin() as connection:
            config = self._legacy_schema(connection)
            for url in ("HTTPS://LEGACY.INVALID:443/", "https://legacy.invalid"):
                connection.execute(text("INSERT INTO news_sources (name, url) VALUES ('Legacy', :url)"), {"url": url})
            with self.assertRaisesRegex(RuntimeError, "Normalized source identity conflict"):
                with connection.begin_nested():
                    command.upgrade(config, "head")
            self.assertNotIn("article_identities", inspect(connection).get_table_names())
            self.assertEqual(connection.execute(text("SELECT count(*) FROM news_sources")).scalar_one(), 2)
            connection.execute(text("DELETE FROM news_sources"))
            command.upgrade(config, "head")

    def test_malformed_legacy_url_reports_article_and_preserves_schema_for_repair(self):
        with self.engine.begin() as connection:
            config = self._legacy_schema(connection)
            source_id = connection.execute(text("INSERT INTO news_sources (name, url) VALUES ('Legacy', 'https://legacy.invalid') RETURNING id")).scalar_one()
            article_id = connection.execute(text("INSERT INTO collected_articles (source_id, url, title) VALUES (:source, 'https://legacy.invalid/?id=%', 'Legacy') RETURNING id"), {"source": source_id}).scalar_one()
            with self.assertRaisesRegex(RuntimeError, str(article_id)):
                with connection.begin_nested():
                    command.upgrade(config, "head")
            self.assertNotIn("article_identities", inspect(connection).get_table_names())
            connection.execute(text("UPDATE collected_articles SET url = 'https://legacy.invalid/fixed'"))
            command.upgrade(config, "head")
