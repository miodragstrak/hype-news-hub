"""initial_postgresql_foundation

Revision ID: 20261030_01
Revises: None
Create Date: 2026-10-30 12:06:52.721454

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '20261030_01'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('collection_runs',
    sa.Column('status', sa.String(length=16), server_default='running', nullable=False),
    sa.Column('limit_per_source', sa.Integer(), server_default='5', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sources_processed', sa.Integer(), server_default='0', nullable=False),
    sa.Column('sources_failed', sa.Integer(), server_default='0', nullable=False),
    sa.Column('articles_total', sa.Integer(), server_default='0', nullable=False),
    sa.Column('stories_total', sa.Integer(), server_default='0', nullable=False),
    sa.Column('story_candidates_total', sa.Integer(), server_default='0', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.CheckConstraint("(status = 'running' AND finished_at IS NULL) OR (status <> 'running' AND finished_at IS NOT NULL)", name=op.f('ck_collection_runs_status_finish_time')),
    sa.CheckConstraint("status IN ('running', 'completed', 'partial', 'failed')", name=op.f('ck_collection_runs_valid_status')),
    sa.CheckConstraint('articles_total >= 0 AND stories_total >= 0 AND story_candidates_total >= 0', name=op.f('ck_collection_runs_nonnegative_counts')),
    sa.CheckConstraint('finished_at IS NULL OR finished_at >= started_at', name=op.f('ck_collection_runs_valid_finish_time')),
    sa.CheckConstraint('limit_per_source BETWEEN 1 AND 50', name=op.f('ck_collection_runs_valid_limit')),
    sa.CheckConstraint('sources_processed >= 0 AND sources_failed >= 0 AND sources_failed <= sources_processed', name=op.f('ck_collection_runs_valid_source_counts')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collection_runs'))
    )
    op.create_index(op.f('ix_collection_runs_started_at'), 'collection_runs', ['started_at'], unique=False)
    op.create_index(op.f('ix_collection_runs_status'), 'collection_runs', ['status'], unique=False)
    op.create_table('news_sources',
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('connector', sa.String(length=32), server_default='wordpress', nullable=False),
    sa.Column('language', sa.String(length=16), nullable=True),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("btrim(connector) <> ''", name=op.f('ck_news_sources_connector_not_blank')),
    sa.CheckConstraint("btrim(name) <> ''", name=op.f('ck_news_sources_name_not_blank')),
    sa.CheckConstraint("btrim(url) <> ''", name=op.f('ck_news_sources_url_not_blank')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_news_sources')),
    sa.UniqueConstraint('url', name=op.f('uq_news_sources_url'))
    )
    op.create_table('stories',
    sa.Column('headline', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='collected', nullable=False),
    sa.Column('similarity_score', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('language', sa.String(length=16), nullable=True),
    sa.Column('categories', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("btrim(headline) <> ''", name=op.f('ck_stories_headline_not_blank')),
    sa.CheckConstraint("status IN ('collected', 'merged', 'translated', 'draft', 'review', 'published')", name=op.f('ck_stories_valid_status')),
    sa.CheckConstraint('similarity_score BETWEEN 0 AND 100', name=op.f('ck_stories_valid_similarity')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stories'))
    )
    op.create_index(op.f('ix_stories_published_at'), 'stories', ['published_at'], unique=False)
    op.create_index(op.f('ix_stories_status'), 'stories', ['status'], unique=False)
    op.create_table('collected_articles',
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('first_seen_run_id', sa.Uuid(), nullable=True),
    sa.Column('external_id', sa.Text(), nullable=True),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('canonical_url', sa.Text(), nullable=True),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('excerpt', sa.Text(), server_default='', nullable=False),
    sa.Column('content', sa.Text(), nullable=True),
    sa.Column('featured_image', sa.Text(), nullable=True),
    sa.Column('language', sa.String(length=16), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('categories', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
    sa.Column('raw', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("btrim(title) <> ''", name=op.f('ck_collected_articles_title_not_blank')),
    sa.CheckConstraint("btrim(url) <> ''", name=op.f('ck_collected_articles_url_not_blank')),
    sa.CheckConstraint("canonical_url IS NULL OR btrim(canonical_url) <> ''", name=op.f('ck_collected_articles_canonical_url_not_blank')),
    sa.CheckConstraint("content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_collected_articles_content_hash_format')),
    sa.CheckConstraint("external_id IS NULL OR btrim(external_id) <> ''", name=op.f('ck_collected_articles_external_id_not_blank')),
    sa.ForeignKeyConstraint(['first_seen_run_id'], ['collection_runs.id'], name=op.f('fk_collected_articles_first_seen_run_id_collection_runs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_id'], ['news_sources.id'], name=op.f('fk_collected_articles_source_id_news_sources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collected_articles')),
    sa.UniqueConstraint('source_id', 'canonical_url', name='uq_collected_articles_source_canonical_url'),
    sa.UniqueConstraint('source_id', 'external_id', name='uq_collected_articles_source_external_id'),
    sa.UniqueConstraint('source_id', 'url', name='uq_collected_articles_source_url')
    )
    op.create_index(op.f('ix_collected_articles_content_hash'), 'collected_articles', ['content_hash'], unique=False)
    op.create_index(op.f('ix_collected_articles_first_seen_run_id'), 'collected_articles', ['first_seen_run_id'], unique=False)
    op.create_index('ix_collected_articles_source_published', 'collected_articles', ['source_id', 'published_at'], unique=False)
    op.create_table('collection_source_results',
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('articles_total', sa.Integer(), server_default='0', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.CheckConstraint("(status = 'pending' AND started_at IS NULL AND finished_at IS NULL) OR (status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL) OR (status IN ('success', 'failed') AND started_at IS NOT NULL AND finished_at IS NOT NULL)", name=op.f('ck_collection_source_results_status_timestamps')),
    sa.CheckConstraint("status IN ('pending', 'running', 'success', 'failed')", name=op.f('ck_collection_source_results_valid_status')),
    sa.CheckConstraint('articles_total >= 0', name=op.f('ck_collection_source_results_nonnegative_article_count')),
    sa.CheckConstraint('finished_at IS NULL OR (started_at IS NOT NULL AND finished_at >= started_at)', name=op.f('ck_collection_source_results_valid_finish_time')),
    sa.ForeignKeyConstraint(['run_id'], ['collection_runs.id'], name=op.f('fk_collection_source_results_run_id_collection_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_id'], ['news_sources.id'], name=op.f('fk_collection_source_results_source_id_news_sources'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collection_source_results')),
    sa.UniqueConstraint('run_id', 'source_id', name='uq_collection_source_results_run_source')
    )
    op.create_index(op.f('ix_collection_source_results_source_id'), 'collection_source_results', ['source_id'], unique=False)
    op.create_table('story_articles',
    sa.Column('story_id', sa.Uuid(), nullable=False),
    sa.Column('article_id', sa.Uuid(), nullable=False),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('match_score', sa.SmallInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('match_score IS NULL OR match_score BETWEEN 0 AND 100', name=op.f('ck_story_articles_valid_match_score')),
    sa.ForeignKeyConstraint(['article_id'], ['collected_articles.id'], name=op.f('fk_story_articles_article_id_collected_articles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['story_id'], ['stories.id'], name=op.f('fk_story_articles_story_id_stories'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('story_id', 'article_id', name=op.f('pk_story_articles')),
    sa.UniqueConstraint('article_id', name='uq_story_articles_article_id')
    )
    op.create_index('uq_story_articles_primary', 'story_articles', ['story_id'], unique=True, postgresql_where=sa.text('is_primary'))


def downgrade() -> None:
    op.drop_index('uq_story_articles_primary', table_name='story_articles', postgresql_where=sa.text('is_primary'))
    op.drop_table('story_articles')
    op.drop_index(op.f('ix_collection_source_results_source_id'), table_name='collection_source_results')
    op.drop_table('collection_source_results')
    op.drop_index('ix_collected_articles_source_published', table_name='collected_articles')
    op.drop_index(op.f('ix_collected_articles_first_seen_run_id'), table_name='collected_articles')
    op.drop_index(op.f('ix_collected_articles_content_hash'), table_name='collected_articles')
    op.drop_table('collected_articles')
    op.drop_index(op.f('ix_stories_status'), table_name='stories')
    op.drop_index(op.f('ix_stories_published_at'), table_name='stories')
    op.drop_table('stories')
    op.drop_table('news_sources')
    op.drop_index(op.f('ix_collection_runs_status'), table_name='collection_runs')
    op.drop_index(op.f('ix_collection_runs_started_at'), table_name='collection_runs')
    op.drop_table('collection_runs')
