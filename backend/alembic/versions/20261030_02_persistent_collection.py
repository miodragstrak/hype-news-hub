"""Bounded identity indexes and collection intake metadata.

Revision ID: 20261030_02
Revises: 20261030_01
"""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from hashlib import sha256

from app.core.url_identity_v1 import canonicalize_url

revision = "20261030_02"
down_revision = "20261030_01"
branch_labels = None
depends_on = None


def _identity_plan(connection):
    """Preflight all identities before DDL/backfill; never merge legacy rows."""
    sources, aliases, owners, source_owners = [], [], {}, {}
    for row in connection.execute(sa.text("SELECT id, url FROM news_sources ORDER BY id")).mappings():
        try:
            canonical = canonicalize_url(row["url"])
        except ValueError as exc:
            raise RuntimeError(f"Invalid URL identity for source {row['id']}: {exc} Correct the legacy URL and retry migration.") from exc
        if canonical in source_owners:
            raise RuntimeError(f"Normalized source identity conflict: sources {source_owners[canonical]} and {row['id']}. Reconcile provenance explicitly before retrying migration.")
        source_owners[canonical] = row["id"]
        sources.append({"id": row["id"], "canonical": canonical})
    for row in connection.execute(sa.text("SELECT id, source_id, external_id, url, canonical_url FROM collected_articles ORDER BY id")).mappings():
        keys = set()
        if row["external_id"] is not None:
            keys.add(("external_id", row["external_id"]))
        for value in (row["url"], row["canonical_url"]):
            if value is None:
                continue
            try:
                canonical = canonicalize_url(value)
            except ValueError as exc:
                raise RuntimeError(f"Invalid URL identity for article {row['id']} in source {row['source_id']}: {exc} Correct the legacy URL and retry migration.") from exc
            keys.update({("url", value), ("url", canonical)})
        for kind, value in sorted(keys):
            fingerprint = sha256(value.encode("utf-8")).hexdigest()
            key = (row["source_id"], kind, fingerprint)
            previous = owners.get(key)
            if previous is not None:
                if previous != (row["id"], value):
                    raise RuntimeError(f"Article identity conflict in source {row['source_id']}: articles {previous[0]} and {row['id']}, kind {kind}, SHA-256 {fingerprint}. Reconcile the conflicting rows before retrying migration; no aliases were written.")
                continue
            owners[key] = (row["id"], value)
            aliases.append({"source_id": row["source_id"], "article_id": row["id"], "kind": kind, "value": value})
    return sources, aliases


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Migration 20261030_02 requires an online connection to preflight and backfill existing URL identities.")
    connection = op.get_bind()
    # Exclude concurrent legacy writers between preflight and unique-key creation.
    # Migrations are explicit maintenance operations, never API startup work.
    op.execute("LOCK TABLE news_sources, collected_articles IN SHARE ROW EXCLUSIVE MODE")
    sources, aliases = _identity_plan(connection)
    # convert_to is marked stable for its variable encoding argument. This wrapper
    # fixes UTF-8, making the conversion deterministic within a PostgreSQL database.
    op.execute("""CREATE FUNCTION public.hnh_identity_hash(value text) RETURNS text
        LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$ SELECT encode(sha256(convert_to(value, 'UTF8')), 'hex') $$""")
    op.add_column("news_sources", sa.Column("identity_url", sa.Text()))
    op.add_column("news_sources", sa.Column("url_key", sa.String(64), sa.Computed("hnh_identity_hash(COALESCE(identity_url, url))"), nullable=False))
    op.create_unique_constraint("uq_news_sources_url_key", "news_sources", ["url_key"])
    op.drop_constraint("uq_news_sources_url", "news_sources", type_="unique")
    if sources:
        connection.execute(sa.text("UPDATE news_sources SET identity_url = :canonical WHERE id = :id"), sources)
    for field in ("external_id", "url", "canonical_url"):
        op.add_column("collected_articles", sa.Column(field + "_key", sa.String(64), sa.Computed(f"hnh_identity_hash({field})"), nullable=field != "url"))
        op.drop_constraint("uq_collected_articles_source_" + field, "collected_articles", type_="unique")
        op.create_unique_constraint("uq_collected_articles_source_" + field, "collected_articles", ["source_id", field + "_key"])
    op.create_unique_constraint("uq_collected_articles_id_source", "collected_articles", ["id", "source_id"])
    op.add_column("collected_articles", sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text())))
    op.add_column("collection_runs", sa.Column("articles_new", sa.Integer(), server_default="0", nullable=False))
    op.create_check_constraint(op.f("ck_collection_runs_valid_new_count"), "collection_runs", "articles_new >= 0 AND articles_new <= articles_total")
    op.create_table("article_identities",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_key", sa.String(64), sa.Computed("hnh_identity_hash(value)"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_article_identities")),
        sa.ForeignKeyConstraint(["article_id", "source_id"], ["collected_articles.id", "collected_articles.source_id"], ondelete="CASCADE", name=op.f("fk_article_identities_article_id_collected_articles")),
        sa.UniqueConstraint("source_id", "kind", "value_key", name="uq_article_identities_source_kind_key"),
        sa.CheckConstraint("kind IN ('external_id', 'url')", name=op.f("ck_article_identities_valid_kind")),
        sa.CheckConstraint("btrim(value) <> ''", name=op.f("ck_article_identities_value_not_blank")),
    )
    op.create_index("ix_article_identities_article_id", "article_identities", ["article_id"])
    if aliases:
        connection.execute(sa.text("INSERT INTO article_identities (source_id, article_id, kind, value) VALUES (:source_id, :article_id, :kind, :value)"), aliases)


def downgrade() -> None:
    # A populated database with very long keys may no longer fit the old indexes.
    # PostgreSQL transactional DDL leaves this revision intact if restoration fails.
    for field in ("external_id", "url", "canonical_url"):
        op.drop_constraint("uq_collected_articles_source_" + field, "collected_articles", type_="unique")
        op.create_unique_constraint("uq_collected_articles_source_" + field, "collected_articles", ["source_id", field])
    op.create_unique_constraint("uq_news_sources_url", "news_sources", ["url"])
    op.drop_index("ix_article_identities_article_id", table_name="article_identities")
    op.drop_table("article_identities")
    op.drop_constraint("uq_collected_articles_id_source", "collected_articles", type_="unique")
    op.drop_constraint(op.f("ck_collection_runs_valid_new_count"), "collection_runs", type_="check")
    op.drop_column("collection_runs", "articles_new")
    op.drop_column("collected_articles", "source_metadata")
    for field in ("external_id", "url", "canonical_url"):
        op.drop_column("collected_articles", field + "_key")
    op.drop_constraint("uq_news_sources_url_key", "news_sources", type_="unique")
    op.drop_column("news_sources", "url_key")
    op.drop_column("news_sources", "identity_url")
    op.execute("DROP FUNCTION public.hnh_identity_hash(text)")
