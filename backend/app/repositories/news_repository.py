from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import cached_property
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.database.runtime_security import assert_runtime_role
from app.database.session import create_database_engine
from app.models import ArticleIdentity, CollectedArticle, CollectionRun, CollectionSourceResult, NewsSource, Story, StoryArticle
from app.schemas.article import NormalizedArticle
from app.schemas.story import Story as APIStory
from app.services.article_identity import canonicalize_url, identity_hash
from app.services.story_matcher import publication_times_eligible, similarity_score
from app.services.timestamps import parse_published_at, published_sort_key
from app.core.content_safety import safe_content_url

COLLECTION_LOCK = 0x484E480F
STORAGE_HEADERS = ["X-News-Storage", "X-Collection-State", "X-Collection-Run-Id", "X-Collection-New-Articles"]


class StorageUnavailable(Exception):
    pass


class CollectionBusy(Exception):
    pass


class IdentityConflict(ValueError):
    pass


def utcnow():
    return datetime.now(timezone.utc)


def matching_published_at(article):
    """Preserve legacy typed dates; new source observations need timezone evidence."""
    metadata = article.source_metadata or {}
    if "published_at" not in metadata:
        return article.published_at
    value = metadata["published_at"]
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.utcoffset() is not None:
        return article.published_at
    # WordPress date_gmt is UTC even when it has no suffix. A naive local-date
    # fallback is retained for display/storage but cannot justify a new match.
    if metadata.get("connector") == "wordpress" and (article.raw or {}).get("date_gmt") == value:
        return article.published_at
    return None


def api_article(article: CollectedArticle) -> NormalizedArticle:
    metadata = article.source_metadata or {}
    return NormalizedArticle(
        external_id=metadata.get("external_id", article.external_id or ""),
        connector=metadata.get("connector", article.source.connector),
        source=metadata.get("source", article.source.name),
        source_url=metadata.get("source_url", article.source.url),
        language=article.language, title=article.title, url=safe_content_url(metadata.get("url")) or safe_content_url(article.url) or "",
        published_at=metadata.get("published_at", article.published_at.isoformat() if article.published_at else None),
        excerpt=article.excerpt, content=article.content, featured_image=safe_content_url(article.featured_image),
        categories=list(article.categories), raw=article.raw,
    )


def api_story(story: Story) -> APIStory | None:
    links = sorted(story.article_links, key=lambda link: (not link.is_primary, str(link.article_id)))
    if not links:
        return None
    articles = [api_article(link.article) for link in links]
    return APIStory(id=str(story.id), headline=story.headline, primary_article=articles[0], articles=articles,
                    sources=sorted({article.source for article in articles}), categories=list(story.categories),
                    published_at=articles[0].published_at, similarity_score=story.similarity_score,
                    status=story.status, language=story.language)


def load_stories(session):
    return list(session.scalars(select(Story).options(
        selectinload(Story.article_links).selectinload(StoryArticle.article).selectinload(CollectedArticle.source)
    ).order_by(Story.id)))


class PostgresNewsRepository:
    def __init__(self, config: Settings):
        self.config = config

    @cached_property
    def engine(self):
        try:
            return create_database_engine(self.config)
        except ValueError as exc:
            raise StorageUnavailable() from exc

    @contextmanager
    def read(self):
        try:
            with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
                with connection.begin():
                    connection.execute(text("SET TRANSACTION READ ONLY"))
                    assert_runtime_role(connection)
                    with Session(bind=connection, expire_on_commit=False) as session:
                        yield session
        except (SQLAlchemyError, ValueError) as exc:
            raise StorageUnavailable() from exc

    def get_stories(self) -> list[APIStory]:
        with self.read() as session:
            stories = [result for row in load_stories(session) if (result := api_story(row)) is not None]
            return sorted(stories, key=lambda item: (published_sort_key(item.published_at), item.id), reverse=True)

    def get_story(self, story_id: str) -> APIStory | None:
        try:
            identity = UUID(story_id)
        except ValueError:
            return None
        return next((story for story in self.get_stories() if story.id == str(identity)), None)

    def headers(self) -> dict[str, str]:
        with self.read() as session:
            run = session.scalars(select(CollectionRun).order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc()).limit(1)).first()
            result = {"X-News-Storage": "postgres", "X-Collection-State": run.status if run else "never_collected"}
            if run:
                result.update({"X-Collection-Run-Id": str(run.id), "X-Collection-New-Articles": str(run.articles_new)})
            return result

    @contextmanager
    def collection(self, sources, limit):
        connection = None
        locked = False
        try:
            connection = self.engine.connect()
            assert_runtime_role(connection)
            locked = connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": COLLECTION_LOCK}).scalar_one()
            connection.commit()
            if not locked:
                raise CollectionBusy()
            writer = CollectionWriter(connection, self.config.story_merge_threshold, self.config.story_match_max_gap_hours)
            writer.start(sources, limit)
            yield writer
        except (SQLAlchemyError, ValueError) as exc:
            raise StorageUnavailable() from exc
        finally:
            if connection is not None:
                if locked:
                    try:
                        connection.rollback()
                        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": COLLECTION_LOCK})
                        connection.commit()
                    except SQLAlchemyError:
                        # Session locks must never leak back into the connection pool.
                        connection.invalidate()
                connection.close()


class CollectionWriter:
    def __init__(self, connection, threshold, max_gap_hours=48):
        self.connection = connection
        self.threshold = max(0, min(100, threshold))
        self.max_gap_hours = max_gap_hours
        self.source_ids = {}
        self.touched_stories = set()

    @contextmanager
    def transaction(self):
        with self.connection.begin(), Session(bind=self.connection, expire_on_commit=False) as session:
            yield session
            session.flush()

    def start(self, sources, limit):
        with self.transaction() as session:
            # A lock acquired after a crash means previous running rows are orphaned.
            for previous in session.scalars(select(CollectionRun).where(CollectionRun.status == "running")):
                results = list(previous.source_results)
                for result in results:
                    if result.status in {"pending", "running"}:
                        result.started_at = result.started_at or utcnow()
                        result.finished_at = utcnow()
                        result.status = "failed"
                        result.error = "Collection interrupted before this source completed."
                previous.sources_processed = len(results)
                previous.sources_failed = sum(result.status == "failed" for result in results)
                previous.status = "partial" if any(result.status == "success" for result in results) else "failed"
                previous.finished_at = utcnow()
                previous.error = "Collection interrupted; previously committed sources retained."
            run = CollectionRun(limit_per_source=limit)
            session.add(run)
            session.flush()
            self.run_id = run.id
            for configured in sources:
                canonical = canonicalize_url(configured.url)
                candidates = [row for row in session.scalars(select(NewsSource))
                              if (row.identity_url or canonicalize_url(row.url)) == canonical]
                if len(candidates) > 1:
                    raise IdentityConflict("Ambiguous source identity.")
                source = candidates[0] if candidates else NewsSource(name=configured.name, url=configured.url, identity_url=canonical, connector=configured.connector)
                source.identity_url, source.name, source.connector, source.enabled = canonical, configured.name, configured.connector, True
                session.add(source)
                session.flush()
                self.source_ids[configured.url] = source.id
                session.add(CollectionSourceResult(run_id=run.id, source_id=source.id))

    def begin_source(self, source_url):
        with self.transaction() as session:
            result = self._result(session, source_url)
            result.status, result.started_at = "running", utcnow()

    def _result(self, session, source_url):
        return session.scalars(select(CollectionSourceResult).where(
            CollectionSourceResult.run_id == self.run_id,
            CollectionSourceResult.source_id == self.source_ids[source_url],
        )).one()

    def fail_source(self, source_url, error):
        with self.transaction() as session:
            result = self._result(session, source_url)
            result.status, result.finished_at, result.error = "failed", utcnow(), error
            run = session.get(CollectionRun, self.run_id)
            run.sources_processed += 1
            run.sources_failed += 1

    def save_source(self, source_url, articles):
        touched = set()
        with self.transaction() as session:
            source_id = self.source_ids[source_url]
            accepted = {}
            created = 0
            for incoming in articles:
                row, is_new = self._upsert_article(session, source_id, incoming)
                created += is_new
                accepted[row.id] = row
            stories = load_stories(session)
            memberships = {link.article_id: (story, link) for story in stories for link in story.article_links}
            for row in accepted.values():
                if row.id in memberships:
                    story, _ = memberships[row.id]
                else:
                    article = api_article(row)
                    candidates = [(similarity_score(article, view.primary_article), str(story.id), story)
                                  for story in stories if self._temporally_eligible(row, story)
                                  and (view := api_story(story)) is not None]
                    candidates.sort(key=lambda item: (-item[0], item[1]))
                    if candidates and candidates[0][0] >= self.threshold:
                        story = candidates[0][2]
                    else:
                        story = Story(headline=row.title, published_at=row.published_at, language=row.language)
                        session.add(story)
                        session.flush()
                        stories.append(story)
                    link = StoryArticle(article=row, is_primary=not story.article_links)
                    story.article_links.append(link)
                    session.flush()
                    memberships[row.id] = (story, link)
                touched.add(story.id)
            for story in stories:
                if story.id in touched:
                    self._refresh_story(story)
            result = self._result(session, source_url)
            result.status, result.finished_at, result.articles_total = "success", utcnow(), len(accepted)
            run = session.get(CollectionRun, self.run_id)
            run.sources_processed += 1
            run.articles_total += len(accepted)
            run.articles_new += created
            current = self.touched_stories | touched
            run.stories_total = len(current)
            run.story_candidates_total = sum(max(0, len(story.article_links) - 1) for story in stories if story.id in current)
            session.flush()
            values = [api_article(row) for row in accepted.values()]
        self.touched_stories.update(touched)
        return values

    def _upsert_article(self, session, source_id, incoming):
        canonical = canonicalize_url(incoming.url)
        keys = [("url", incoming.url), ("url", canonical)]
        external = incoming.external_id if incoming.external_id.strip() else None
        if external is not None:
            keys.append(("external_id", external))
        matches = {}
        for kind, value in keys:
            alias = session.scalars(select(ArticleIdentity).where(ArticleIdentity.source_id == source_id,
                ArticleIdentity.kind == kind, ArticleIdentity.value_key == identity_hash(value))).first()
            if alias:
                if alias.value != value:
                    raise IdentityConflict("Identity hash collision.")
                matches[alias.article_id] = session.get(CollectedArticle, alias.article_id)
        # Also supports records inserted before aliases existed or outside intake.
        conditions = [CollectedArticle.url_key.in_([identity_hash(incoming.url), identity_hash(canonical)]),
                      CollectedArticle.canonical_url_key == identity_hash(canonical)]
        if external is not None:
            conditions.append(CollectedArticle.external_id_key == identity_hash(external))
        for row in session.scalars(select(CollectedArticle).where(CollectedArticle.source_id == source_id, or_(*conditions))):
            if not (row.url in {incoming.url, canonical} or row.canonical_url == canonical or
                    (external is not None and row.external_id == external)):
                raise IdentityConflict("Identity hash collision.")
            matches[row.id] = row
        if len(matches) > 1:
            raise IdentityConflict("Source identifiers resolve to different existing articles.")
        is_new = not matches
        row = next(iter(matches.values())) if matches else CollectedArticle(source_id=source_id, external_id=external,
                    url=incoming.url, first_seen_run_id=self.run_id)
        if row.external_id is None:
            row.external_id = external
        row.canonical_url = canonical
        row.title, row.excerpt, row.published_at = incoming.title, incoming.excerpt, parse_published_at(incoming.published_at)
        row.language, row.categories = incoming.language, list(incoming.categories)
        row.featured_image = incoming.featured_image
        if incoming.content is not None:
            row.content = incoming.content
        if incoming.raw is not None:
            row.raw = incoming.raw
        row.source_metadata = {key: getattr(incoming, key) for key in ("source", "source_url", "external_id", "url", "connector", "published_at")}
        row.content_hash = identity_hash(incoming.title + "\n" + incoming.excerpt + "\n" + (row.content or ""))
        session.add(row)
        session.flush()
        for kind, value in set(keys):
            existing = session.scalars(select(ArticleIdentity).where(ArticleIdentity.source_id == source_id,
                ArticleIdentity.kind == kind, ArticleIdentity.value_key == identity_hash(value))).first()
            if existing is None:
                session.add(ArticleIdentity(source_id=source_id, article_id=row.id, kind=kind, value=value))
        session.flush()
        return row, int(is_new)

    def _temporally_eligible(self, article, story):
        primary = next((link.article for link in story.article_links if link.is_primary), None)
        return primary is not None and publication_times_eligible(matching_published_at(article), matching_published_at(primary), self.max_gap_hours)

    def _refresh_story(self, story):
        primary = next((link for link in story.article_links if link.is_primary), None)
        if primary is None:
            primary = min(story.article_links, key=lambda link: str(link.article_id))
            primary.is_primary = True
        article = primary.article
        story.headline, story.published_at, story.language = article.title, article.published_at, article.language
        story.categories = sorted({category for link in story.article_links for category in link.article.categories})
        for link in story.article_links:
            link.match_score = None if link is primary else similarity_score(api_article(link.article), api_article(article))
        story.similarity_score = max((link.match_score or 0 for link in story.article_links), default=0)
        if story.status in {"collected", "merged"}:
            story.status = "merged" if len(story.article_links) > 1 else "collected"

    def finish(self, error=None):
        with self.transaction() as session:
            run = session.get(CollectionRun, self.run_id)
            if error:
                for result in run.source_results:
                    if result.status in {"pending", "running"}:
                        result.started_at = result.started_at or utcnow()
                        result.finished_at, result.status, result.error = utcnow(), "failed", error
                run.sources_processed = len(run.source_results)
                run.sources_failed = sum(result.status == "failed" for result in run.source_results)
                run.error = error
            run.finished_at = utcnow()
            run.status = ("failed" if run.sources_processed and run.sources_failed == run.sources_processed else
                          "partial" if run.sources_failed else "completed")
            if error:
                run.status = "partial" if any(result.status == "success" for result in run.source_results) else "failed"
            snapshot = [view for story in load_stories(session) if (view := api_story(story)) is not None]
            stories = [story for story in snapshot if UUID(story.id) in self.touched_stories]
            stories.sort(key=lambda story: (published_sort_key(story.published_at), story.id), reverse=True)
            run.stories_total = len(stories)
            run.story_candidates_total = sum(max(0, len(story.articles) - 1) for story in stories)
            headers = {"X-News-Storage": "postgres", "X-Collection-State": run.status,
                       "X-Collection-Run-Id": str(run.id), "X-Collection-New-Articles": str(run.articles_new)}
            snapshot.sort(key=lambda story: (published_sort_key(story.published_at), story.id), reverse=True)
            return snapshot, run.story_candidates_total, headers
