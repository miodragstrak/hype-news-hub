"""Private editorial security and immutable provenance foundation.

Revision ID: 20261030_03
Revises: 20261030_02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261030_03"
down_revision = "20261030_02"
branch_labels = None
depends_on = None

_HISTORY_TABLES = ("editorial_draft_versions", "editorial_version_sources", "editorial_decisions", "editorial_events")
_SNAPSHOT_SIGNATURE = "public.hnh_editorial_snapshot_hash(uuid, uuid, text, text, text, text, text, timestamptz, text, timestamptz)"


def upgrade() -> None:
    # Canonical PostgreSQL JSONB text, explicit UTC timestamp formatting, UTF-8
    # SHA-256. Never depends on session TimeZone, DateStyle or source HTML parsing.
    op.execute("""CREATE FUNCTION public.hnh_editorial_snapshot_hash(
        source_id uuid, article_id uuid, source_name text, source_url text, external_id text,
        original_url text, canonical_url text, published_at timestamptz, input_text text, captured_at timestamptz
    ) RETURNS text LANGUAGE SQL IMMUTABLE PARALLEL SAFE SET search_path = pg_catalog AS $$
        SELECT public.hnh_identity_hash(jsonb_build_array(source_id::text, article_id::text,
            source_name, source_url, external_id, original_url, canonical_url,
            to_char(published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), input_text,
            to_char(captured_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))::text)
    $$""")
    op.create_table('editorial_drafts',
    sa.Column('story_id', sa.Uuid(), nullable=False),
    sa.Column('target_locale', sa.String(length=16), server_default='sr-Latn', nullable=False),
    sa.Column('status', sa.String(length=24), server_default='editing', nullable=False),
    sa.Column('current_version_number', sa.Integer(), nullable=True),
    sa.Column('revision', sa.Integer(), server_default='1', nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_issuer', sa.Text(), nullable=False),
    sa.Column('actor_subject', sa.Text(), nullable=False),
    sa.CheckConstraint("btrim(actor_issuer) <> ''", name=op.f('ck_editorial_drafts_actor_issuer_not_blank')),
    sa.CheckConstraint("btrim(actor_subject) <> ''", name=op.f('ck_editorial_drafts_actor_subject_not_blank')),
    sa.CheckConstraint("status = 'editing' OR current_version_number IS NOT NULL", name=op.f('ck_editorial_drafts_state_requires_version')),
    sa.CheckConstraint("status IN ('editing', 'in_review', 'changes_requested', 'approved', 'rejected')", name=op.f('ck_editorial_drafts_valid_status')),
    sa.CheckConstraint("target_locale = 'sr-Latn'", name=op.f('ck_editorial_drafts_supported_locale')),
    sa.CheckConstraint('current_version_number IS NULL OR current_version_number >= 1', name=op.f('ck_editorial_drafts_valid_current_version')),
    sa.CheckConstraint('revision >= 1', name=op.f('ck_editorial_drafts_positive_revision')),
    sa.ForeignKeyConstraint(['story_id'], ['stories.id'], name=op.f('fk_editorial_drafts_story_id_stories'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_editorial_drafts')),
    sa.UniqueConstraint('story_id', 'target_locale', name='uq_editorial_drafts_story_locale')
    )
    op.create_index('ix_editorial_drafts_status_updated', 'editorial_drafts', ['status', 'updated_at'], unique=False)
    op.create_index(op.f('ix_editorial_drafts_story_id'), 'editorial_drafts', ['story_id'], unique=False)
    op.create_table('editorial_draft_versions',
    sa.Column('draft_id', sa.Uuid(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('payload_schema_version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content_hash', sa.String(length=64), sa.Computed('hnh_identity_hash(payload::text)', ), nullable=False),
    sa.Column('source_count', sa.Integer(), nullable=False),
    sa.Column('origin', sa.String(length=16), server_default='manual', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('actor_issuer', sa.Text(), nullable=False),
    sa.Column('actor_subject', sa.Text(), nullable=False),
    sa.CheckConstraint("btrim(actor_issuer) <> ''", name=op.f('ck_editorial_draft_versions_actor_issuer_not_blank')),
    sa.CheckConstraint("btrim(actor_subject) <> ''", name=op.f('ck_editorial_draft_versions_actor_subject_not_blank')),
    sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name=op.f('ck_editorial_draft_versions_payload_object')),
    sa.CheckConstraint("origin IN ('manual', 'imported', 'ai')", name=op.f('ck_editorial_draft_versions_valid_origin')),
    sa.CheckConstraint('payload_schema_version >= 1', name=op.f('ck_editorial_draft_versions_positive_schema_version')),
    sa.CheckConstraint('source_count >= 1', name=op.f('ck_editorial_draft_versions_positive_source_count')),
    sa.CheckConstraint('version_number >= 1', name=op.f('ck_editorial_draft_versions_positive_version')),
    sa.ForeignKeyConstraint(['draft_id'], ['editorial_drafts.id'], name=op.f('fk_editorial_draft_versions_draft_id_editorial_drafts'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_editorial_draft_versions')),
    sa.UniqueConstraint('draft_id', 'version_number', 'content_hash', name='uq_editorial_versions_content'),
    sa.UniqueConstraint('draft_id', 'version_number', name='uq_editorial_versions_number')
    )
    op.create_table('editorial_version_sources',
    sa.Column('draft_id', sa.Uuid(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('article_id', sa.Uuid(), nullable=False),
    sa.Column('source_name', sa.Text(), nullable=False),
    sa.Column('source_url', sa.Text(), nullable=False),
    sa.Column('external_id', sa.Text(), nullable=True),
    sa.Column('original_url', sa.Text(), nullable=False),
    sa.Column('canonical_url', sa.Text(), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('input_text', sa.Text(), nullable=False),
    sa.Column('captured_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('snapshot_hash', sa.String(length=64), sa.Computed('public.hnh_editorial_snapshot_hash(source_id, article_id, source_name, source_url, external_id, original_url, canonical_url, published_at, input_text, captured_at)', ), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.CheckConstraint("btrim(input_text) <> ''", name=op.f('ck_editorial_version_sources_input_text_not_blank')),
    sa.CheckConstraint("btrim(original_url) <> ''", name=op.f('ck_editorial_version_sources_original_url_not_blank')),
    sa.CheckConstraint("btrim(source_name) <> '' AND btrim(source_url) <> ''", name=op.f('ck_editorial_version_sources_source_identity_not_blank')),
    sa.CheckConstraint("canonical_url IS NULL OR btrim(canonical_url) <> ''", name=op.f('ck_editorial_version_sources_canonical_url_not_blank')),
    sa.CheckConstraint("external_id IS NULL OR btrim(external_id) <> ''", name=op.f('ck_editorial_version_sources_external_id_not_blank')),
    sa.CheckConstraint('version_number >= 1', name=op.f('ck_editorial_version_sources_positive_version')),
    sa.ForeignKeyConstraint(['article_id', 'source_id'], ['collected_articles.id', 'collected_articles.source_id'], name=op.f('fk_editorial_version_sources_article_id_collected_articles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['draft_id', 'version_number'], ['editorial_draft_versions.draft_id', 'editorial_draft_versions.version_number'], name=op.f('fk_editorial_version_sources_draft_id_editorial_draft_versions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_editorial_version_sources')),
    sa.UniqueConstraint('draft_id', 'version_number', 'article_id', name='uq_editorial_version_sources_article')
    )
    op.create_index('ix_editorial_version_sources_article', 'editorial_version_sources', ['article_id'], unique=False)
    op.create_index('ix_editorial_version_sources_source', 'editorial_version_sources', ['source_id'], unique=False)
    op.create_table('editorial_decisions',
    sa.Column('draft_id', sa.Uuid(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('decision', sa.String(length=24), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('actor_issuer', sa.Text(), nullable=False),
    sa.Column('actor_subject', sa.Text(), nullable=False),
    sa.CheckConstraint("btrim(actor_issuer) <> ''", name=op.f('ck_editorial_decisions_actor_issuer_not_blank')),
    sa.CheckConstraint("btrim(actor_subject) <> ''", name=op.f('ck_editorial_decisions_actor_subject_not_blank')),
    sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_editorial_decisions_content_hash_format')),
    sa.CheckConstraint("decision = 'approve' OR reason IS NOT NULL", name=op.f('ck_editorial_decisions_negative_decision_requires_reason')),
    sa.CheckConstraint("decision IN ('approve', 'reject', 'request_changes')", name=op.f('ck_editorial_decisions_valid_decision')),
    sa.CheckConstraint("reason IS NULL OR btrim(reason) <> ''", name=op.f('ck_editorial_decisions_reason_not_blank')),
    sa.ForeignKeyConstraint(['draft_id', 'version_number', 'content_hash'], ['editorial_draft_versions.draft_id', 'editorial_draft_versions.version_number', 'editorial_draft_versions.content_hash'], name=op.f('fk_editorial_decisions_draft_id_editorial_draft_versions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_editorial_decisions'))
    )
    op.create_index('ix_editorial_decisions_version', 'editorial_decisions', ['draft_id', 'version_number', 'decided_at'], unique=False)
    op.create_table('editorial_events',
    sa.Column('draft_id', sa.Uuid(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=True),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('from_status', sa.String(length=24), nullable=True),
    sa.Column('to_status', sa.String(length=24), nullable=True),
    sa.Column('command_id', sa.Uuid(), nullable=True),
    sa.Column('request_hash', sa.String(length=64), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('actor_issuer', sa.Text(), nullable=False),
    sa.Column('actor_subject', sa.Text(), nullable=False),
    sa.CheckConstraint("(command_id IS NULL AND request_hash IS NULL) OR (command_id IS NOT NULL AND request_hash IS NOT NULL AND request_hash ~ '^[0-9a-f]{64}$')", name=op.f('ck_editorial_events_command_hash_pair')),
    sa.CheckConstraint("btrim(actor_issuer) <> ''", name=op.f('ck_editorial_events_actor_issuer_not_blank')),
    sa.CheckConstraint("btrim(actor_subject) <> ''", name=op.f('ck_editorial_events_actor_subject_not_blank')),
    sa.CheckConstraint("event_type ~ '^[a-z][a-z0-9_.]*$'", name=op.f('ck_editorial_events_valid_event_type')),
    sa.CheckConstraint("from_status IS NULL OR from_status IN ('editing', 'in_review', 'changes_requested', 'approved', 'rejected')", name=op.f('ck_editorial_events_valid_from_status')),
    sa.CheckConstraint("jsonb_typeof(details) = 'object'", name=op.f('ck_editorial_events_details_object')),
    sa.CheckConstraint("to_status IS NULL OR to_status IN ('editing', 'in_review', 'changes_requested', 'approved', 'rejected')", name=op.f('ck_editorial_events_valid_to_status')),
    sa.CheckConstraint('version_number IS NULL OR version_number >= 1', name=op.f('ck_editorial_events_valid_version')),
    sa.ForeignKeyConstraint(['draft_id', 'version_number'], ['editorial_draft_versions.draft_id', 'editorial_draft_versions.version_number'], name=op.f('fk_editorial_events_draft_id_editorial_draft_versions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['draft_id'], ['editorial_drafts.id'], name=op.f('fk_editorial_events_draft_id_editorial_drafts'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_editorial_events')),
    sa.UniqueConstraint('draft_id', 'command_id', name='uq_editorial_events_command')
    )
    op.create_index('ix_editorial_events_history', 'editorial_events', ['draft_id', 'occurred_at', 'id'], unique=False)
    op.create_foreign_key('fk_editorial_drafts_current_version', 'editorial_drafts', 'editorial_draft_versions', ['id', 'current_version_number'], ['draft_id', 'version_number'], initially='DEFERRED', deferrable=True, use_alter=True)

    op.execute("""CREATE FUNCTION public.hnh_editorial_immutable() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$ BEGIN
            RAISE EXCEPTION 'Historical editorial records are immutable' USING ERRCODE = '23514';
        END $$""")
    for table in _HISTORY_TABLES:
        op.execute(f"CREATE TRIGGER hnh_editorial_immutable BEFORE UPDATE OR DELETE ON public.{table} "
                   "FOR EACH ROW EXECUTE FUNCTION public.hnh_editorial_immutable()")

    op.execute("""CREATE FUNCTION public.hnh_editorial_source_count_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$ DECLARE expected integer; actual bigint; BEGIN
            SELECT source_count INTO expected FROM public.editorial_draft_versions
                WHERE draft_id = NEW.draft_id AND version_number = NEW.version_number;
            SELECT count(*) INTO actual FROM public.editorial_version_sources
                WHERE draft_id = NEW.draft_id AND version_number = NEW.version_number;
            IF expected IS NULL OR actual <> expected THEN
                RAISE EXCEPTION 'Editorial version requires its complete immutable source snapshots'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END $$""")
    # Count at COMMIT permits one atomic version+snapshots insertion, but rejects
    # incomplete versions and any later addition of sources to committed history.
    for table in ("editorial_draft_versions", "editorial_version_sources"):
        op.execute(f"CREATE CONSTRAINT TRIGGER hnh_editorial_sources_complete AFTER INSERT ON public.{table} "
                   "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.hnh_editorial_source_count_guard()")

    op.execute("""CREATE FUNCTION public.hnh_editorial_draft_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$ BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.story_id IS DISTINCT FROM OLD.story_id
                OR NEW.target_locale IS DISTINCT FROM OLD.target_locale
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.actor_issuer IS DISTINCT FROM OLD.actor_issuer
                OR NEW.actor_subject IS DISTINCT FROM OLD.actor_subject THEN
                RAISE EXCEPTION 'Editorial draft identity and creator are immutable' USING ERRCODE = '23514';
            END IF;
            IF NEW.revision <> OLD.revision + 1 THEN
                RAISE EXCEPTION 'Editorial draft update requires one concurrency revision increment' USING ERRCODE = '23514';
            END IF;
            IF OLD.current_version_number IS NOT NULL AND (NEW.current_version_number IS NULL
                OR NEW.current_version_number < OLD.current_version_number) THEN
                RAISE EXCEPTION 'Editorial draft version cannot move backwards' USING ERRCODE = '23514';
            END IF;
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END $$""")
    op.execute("CREATE TRIGGER hnh_editorial_draft_guard BEFORE UPDATE ON public.editorial_drafts "
               "FOR EACH ROW EXECUTE FUNCTION public.hnh_editorial_draft_guard()")
    op.execute("""CREATE FUNCTION public.hnh_editorial_approval_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$ BEGIN
            IF EXISTS (SELECT 1 FROM public.editorial_drafts d WHERE d.id = NEW.id AND d.status = 'approved'
                AND NOT EXISTS (SELECT 1 FROM public.editorial_decisions a
                    WHERE a.draft_id = d.id AND a.version_number = d.current_version_number AND a.decision = 'approve')) THEN
                RAISE EXCEPTION 'Approved editorial state requires a decision for the exact current version'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END $$""")
    op.execute("CREATE CONSTRAINT TRIGGER hnh_editorial_approval_required AFTER INSERT OR UPDATE ON public.editorial_drafts "
               "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.hnh_editorial_approval_guard()")
    tables = ", ".join("public." + table for table in ("editorial_drafts", *_HISTORY_TABLES))
    op.execute(f"REVOKE ALL ON TABLE {tables} FROM PUBLIC")
    for function in (_SNAPSHOT_SIGNATURE, "public.hnh_editorial_immutable()",
                     "public.hnh_editorial_source_count_guard()", "public.hnh_editorial_draft_guard()",
                     "public.hnh_editorial_approval_guard()"):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")


def downgrade() -> None:
    # Owner maintenance only; removes editorial data, never collection data.
    op.drop_constraint("fk_editorial_drafts_current_version", "editorial_drafts", type_="foreignkey")
    for table in ("editorial_events", "editorial_decisions", "editorial_version_sources",
                  "editorial_draft_versions", "editorial_drafts"):
        op.drop_table(table)
    for function in ("public.hnh_editorial_approval_guard()", "public.hnh_editorial_draft_guard()", "public.hnh_editorial_source_count_guard()",
                     "public.hnh_editorial_immutable()", _SNAPSHOT_SIGNATURE):
        op.execute(f"DROP FUNCTION {function}")
