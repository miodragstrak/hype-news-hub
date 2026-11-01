"""Explicit AI acceptance with durable receipts; revision 04 is unchanged.

Downgrade refuses accepted suggestions rather than discarding immutable receipts.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261101_05"
down_revision = "20261101_04"
branch_labels = None
depends_on = None

# Frozen DDL, independent of runtime models.
_UPGRADE = (
    """ALTER TABLE public.ai_processing_runs ADD CONSTRAINT ck_ai_processing_runs_acceptance_reference CHECK ((status = 'accepted' AND accepted_at IS NOT NULL AND accepted_draft_id IS NOT NULL AND accepted_version_number >= 1 AND accepted_version_number IS NOT NULL AND accepted_content_hash ~ '^[0-9a-f]{64}$' AND accepted_content_hash IS NOT NULL) OR (status <> 'accepted' AND accepted_at IS NULL AND accepted_draft_id IS NULL AND accepted_version_number IS NULL AND accepted_content_hash IS NULL))""",
    """ALTER TABLE public.ai_processing_runs ADD CONSTRAINT ck_ai_processing_runs_state_payload CHECK ((status = 'processing' AND revision = 1 AND output IS NULL AND error_code IS NULL AND completed_at IS NULL AND rejected_at IS NULL) OR (status = 'succeeded' AND revision = 2 AND output IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL AND rejected_at IS NULL) OR (status IN ('failed', 'interrupted') AND revision = 2 AND output IS NULL AND error_code IN ('provider_timeout','provider_failure','invalid_provider_output','process_interrupted') AND error_code IS NOT NULL AND completed_at IS NOT NULL AND rejected_at IS NULL) OR (status = 'rejected' AND revision = 3 AND output IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL AND rejected_at IS NOT NULL) OR (status = 'accepted' AND revision = 3 AND output IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL AND rejected_at IS NULL))""",
    """ALTER TABLE public.ai_processing_runs ADD CONSTRAINT ck_ai_processing_runs_valid_status CHECK (status IN ('processing', 'succeeded', 'failed', 'interrupted', 'rejected', 'accepted'))""",
    """ALTER TABLE public.ai_processing_runs ADD CONSTRAINT ck_ai_processing_runs_valid_timestamps CHECK (expires_at > created_at AND (completed_at IS NULL OR completed_at >= created_at) AND (rejected_at IS NULL OR rejected_at >= completed_at) AND (accepted_at IS NULL OR accepted_at >= completed_at))""",
    """ALTER TABLE public.ai_processing_runs ADD CONSTRAINT fk_ai_processing_runs_accepted_version FOREIGN KEY(accepted_draft_id, accepted_version_number, accepted_content_hash) REFERENCES public.editorial_draft_versions (draft_id, version_number, content_hash) ON DELETE RESTRICT""",
    """ALTER TABLE public.ai_processing_events ADD CONSTRAINT ck_ai_processing_events_bounded_result CHECK ((action = 'suggestion.accepted' AND result IS NOT NULL AND jsonb_typeof(result) = 'object' AND octet_length(result::text) <= 4096) OR (action <> 'suggestion.accepted' AND result IS NULL))""",
    """ALTER TABLE public.ai_processing_events ADD CONSTRAINT ck_ai_processing_events_event_shape CHECK ((revision = 1 AND action = 'generation.requested' AND status = 'processing' AND command_id IS NOT NULL AND reason IS NULL) OR (revision = 2 AND action = 'generation.' || status AND status IN ('succeeded','failed','interrupted') AND command_id IS NULL AND reason IS NULL) OR (revision = 3 AND action = 'suggestion.rejected' AND status = 'rejected' AND command_id IS NOT NULL AND reason IS NOT NULL) OR (revision = 3 AND action = 'suggestion.accepted' AND status = 'accepted' AND command_id IS NOT NULL AND reason IS NULL))""",
    """ALTER TABLE public.ai_processing_events ADD CONSTRAINT ck_ai_processing_events_valid_action CHECK (action IN ('generation.requested','generation.succeeded','generation.failed','generation.interrupted','suggestion.rejected','suggestion.accepted'))""",
    """ALTER TABLE public.ai_processing_events ADD CONSTRAINT ck_ai_processing_events_valid_status CHECK (status IN ('processing', 'succeeded', 'failed', 'interrupted', 'rejected', 'accepted'))""",
)
_DOWNGRADE = (
    """ALTER TABLE public.ai_processing_runs ADD CONSTRAINT ck_ai_processing_runs_state_payload CHECK ((status = 'processing' AND revision = 1 AND output IS NULL AND error_code IS NULL AND completed_at IS NULL AND rejected_at IS NULL) OR (status = 'succeeded' AND revision = 2 AND output IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL AND rejected_at IS NULL) OR (status IN ('failed', 'interrupted') AND revision = 2 AND output IS NULL AND error_code IN ('provider_timeout','provider_failure','invalid_provider_output','process_interrupted') AND error_code IS NOT NULL AND completed_at IS NOT NULL AND rejected_at IS NULL) OR (status = 'rejected' AND revision = 3 AND output IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL AND rejected_at IS NOT NULL))""",
    """ALTER TABLE public.ai_processing_runs ADD CONSTRAINT ck_ai_processing_runs_valid_status CHECK (status IN ('processing', 'succeeded', 'failed', 'interrupted', 'rejected'))""",
    """ALTER TABLE public.ai_processing_runs ADD CONSTRAINT ck_ai_processing_runs_valid_timestamps CHECK (expires_at > created_at AND (completed_at IS NULL OR completed_at >= created_at) AND (rejected_at IS NULL OR rejected_at >= completed_at))""",
    """ALTER TABLE public.ai_processing_events ADD CONSTRAINT ck_ai_processing_events_event_shape CHECK ((revision = 1 AND action = 'generation.requested' AND status = 'processing' AND command_id IS NOT NULL AND reason IS NULL) OR (revision = 2 AND action = 'generation.' || status AND status IN ('succeeded','failed','interrupted') AND command_id IS NULL AND reason IS NULL) OR (revision = 3 AND action = 'suggestion.rejected' AND status = 'rejected' AND command_id IS NOT NULL AND reason IS NOT NULL))""",
    """ALTER TABLE public.ai_processing_events ADD CONSTRAINT ck_ai_processing_events_valid_action CHECK (action IN ('generation.requested','generation.succeeded','generation.failed','generation.interrupted','suggestion.rejected'))""",
    """ALTER TABLE public.ai_processing_events ADD CONSTRAINT ck_ai_processing_events_valid_status CHECK (status IN ('processing', 'succeeded', 'failed', 'interrupted', 'rejected'))""",
)
_OLD_RUN_GUARD = """CREATE OR REPLACE FUNCTION public.hnh_ai_run_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$ BEGIN
        IF (to_jsonb(NEW) - ARRAY['status','revision','input_hash','output','output_hash','error_code','completed_at','rejected_at'])
            IS DISTINCT FROM
            (to_jsonb(OLD) - ARRAY['status','revision','input_hash','output','output_hash','error_code','completed_at','rejected_at'])
            OR NEW.revision <> OLD.revision + 1 THEN
            RAISE EXCEPTION 'AI request and evidence are immutable; updates require a revision' USING ERRCODE = '23514';
        END IF;
        IF OLD.status = 'processing' AND NEW.status IN ('succeeded','failed','interrupted') THEN
            RETURN NEW;
        END IF;
        IF OLD.status = 'succeeded' AND NEW.status = 'rejected'
            AND NEW.output IS NOT DISTINCT FROM OLD.output
            AND NEW.error_code IS NOT DISTINCT FROM OLD.error_code
            AND NEW.completed_at IS NOT DISTINCT FROM OLD.completed_at THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'AI terminal result is immutable' USING ERRCODE = '23514';
        END $$"""


def _drop_constraints(statements):
    # Table/constraint names are literal, reviewed migration DDL above.
    for statement in statements:
        words = statement.split()
        op.execute(f"ALTER TABLE {words[2]} DROP CONSTRAINT {words[5]}")


def upgrade() -> None:
    for column in (sa.Column('accepted_at', sa.DateTime(timezone=True)),
                   sa.Column('accepted_draft_id', sa.Uuid()),
                   sa.Column('accepted_version_number', sa.Integer()),
                   sa.Column('accepted_content_hash', sa.String(64))):
        op.add_column('ai_processing_runs', column, schema='public')
    op.add_column('ai_processing_events', sa.Column('result', postgresql.JSONB()), schema='public')
    _drop_constraints(_DOWNGRADE)
    for statement in _UPGRADE:
        op.execute(statement)
    op.execute("""CREATE OR REPLACE FUNCTION public.hnh_ai_run_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$ BEGIN
        IF (to_jsonb(NEW) - ARRAY['status','revision','input_hash','output','output_hash','error_code','completed_at',
                'rejected_at','accepted_at','accepted_draft_id','accepted_version_number','accepted_content_hash'])
            IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status','revision','input_hash','output','output_hash','error_code','completed_at',
                'rejected_at','accepted_at','accepted_draft_id','accepted_version_number','accepted_content_hash'])
            OR NEW.revision <> OLD.revision + 1 THEN
            RAISE EXCEPTION 'AI request and evidence are immutable; updates require a revision' USING ERRCODE = '23514';
        END IF;
        IF OLD.status = 'processing' AND NEW.status IN ('succeeded','failed','interrupted') THEN RETURN NEW; END IF;
        IF OLD.status = 'succeeded' AND NEW.status IN ('rejected','accepted')
            AND NEW.output IS NOT DISTINCT FROM OLD.output AND NEW.error_code IS NOT DISTINCT FROM OLD.error_code
            AND NEW.completed_at IS NOT DISTINCT FROM OLD.completed_at THEN RETURN NEW; END IF;
        RAISE EXCEPTION 'AI terminal result is immutable' USING ERRCODE = '23514';
        END $$""")
    op.execute("""CREATE FUNCTION public.hnh_ai_acceptance_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$ DECLARE
            identity uuid; head public.ai_processing_runs%ROWTYPE;
        BEGIN
            IF TG_TABLE_NAME = 'ai_processing_runs' THEN identity := NEW.id; ELSE identity := NEW.run_id; END IF;
            SELECT * INTO head FROM public.ai_processing_runs WHERE id = identity;
            IF head.status <> 'accepted' THEN RETURN NULL; END IF;
            IF NOT EXISTS (
                SELECT 1 FROM public.editorial_draft_versions v JOIN public.editorial_drafts d ON d.id = v.draft_id
                JOIN public.editorial_version_sources s ON s.draft_id = v.draft_id AND s.version_number = v.version_number
                WHERE v.draft_id = head.accepted_draft_id AND v.version_number = head.accepted_version_number
                    AND v.content_hash = head.accepted_content_hash AND v.origin = 'ai' AND v.source_count = 1
                    AND d.story_id = head.story_id AND d.target_locale = head.target_locale
                    AND s.article_id = head.article_id AND s.source_id = head.source_id
                    AND s.source_name = head.input_payload->'source'->>'source_name'
                    AND s.source_url = head.input_payload->'source'->>'source_url'
                    AND s.original_url = head.input_payload->'source'->>'original_url'
                    AND s.canonical_url IS NOT DISTINCT FROM (head.input_payload->'source'->>'canonical_url')
                    AND s.external_id IS NOT DISTINCT FROM (head.input_payload->'source'->>'external_id')
                    AND s.published_at IS NOT DISTINCT FROM ((head.input_payload->'source'->>'published_at')::timestamptz)
                    AND s.captured_at = (head.input_payload->'source'->>'captured_at')::timestamptz
                    AND s.input_text = head.input_payload->'source'->>'input_text'
            ) OR NOT EXISTS (
                SELECT 1 FROM public.ai_processing_events e JOIN public.editorial_events a
                    ON a.draft_id = head.accepted_draft_id AND a.version_number = head.accepted_version_number
                    AND a.command_id = e.command_id AND a.actor_issuer = e.actor_issuer AND a.actor_subject = e.actor_subject
                WHERE e.run_id = head.id AND e.revision = 3 AND e.action = 'suggestion.accepted'
                    AND e.occurred_at = head.accepted_at AND a.occurred_at = head.accepted_at
                    AND a.event_type = 'draft.accept_ai' AND a.to_status = 'editing'
                    AND e.result @> jsonb_build_object('command_id', e.command_id::text,
                        'draft_id', head.accepted_draft_id::text, 'version_number', head.accepted_version_number,
                        'content_hash', head.accepted_content_hash, 'status', 'editing')
                    AND a.details->'result' = e.result
                    AND a.details->'ai_provenance' @> jsonb_build_object('suggestion_id', head.id::text,
                        'input_hash', head.input_hash, 'output_hash', head.output_hash, 'provider', head.provenance,
                        'prompt_version', head.input_payload->>'prompt_version')
            ) THEN
                RAISE EXCEPTION 'AI acceptance requires exact frozen evidence and paired immutable receipts' USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END $$""")
    for table in ('ai_processing_runs', 'ai_processing_events'):
        op.execute(f"CREATE CONSTRAINT TRIGGER hnh_ai_acceptance_complete AFTER INSERT OR UPDATE ON public.{table} "
                   "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.hnh_ai_acceptance_guard()")
    op.execute("REVOKE ALL ON FUNCTION public.hnh_ai_acceptance_guard() FROM PUBLIC")


def downgrade() -> None:
    # Restoring 04 cannot represent an accepted receipt. Refuse rather than alter
    # immutable history or leave an accepted editorial version without its link.
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM public.ai_processing_runs WHERE status = 'accepted') THEN
        RAISE EXCEPTION 'Cannot downgrade AI acceptance while accepted suggestions exist. Back up/export and obtain an explicit data-retention plan; immutable receipts were not changed.';
        END IF; END $$""")
    for table in ('ai_processing_runs', 'ai_processing_events'):
        op.execute(f"DROP TRIGGER hnh_ai_acceptance_complete ON public.{table}")
    op.execute("DROP FUNCTION public.hnh_ai_acceptance_guard()")
    op.execute(_OLD_RUN_GUARD)
    _drop_constraints(_UPGRADE)
    for statement in _DOWNGRADE:
        op.execute(statement)
    op.drop_column('ai_processing_events', 'result', schema='public')
    for column in ('accepted_content_hash', 'accepted_version_number', 'accepted_draft_id', 'accepted_at'):
        op.drop_column('ai_processing_runs', column, schema='public')
