"""Gemini failure classification and immutable usage metadata. Prior revisions unchanged."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261101_06"
down_revision = "20261101_05"
branch_labels = None
depends_on = None

_OLD_STATE = """ALTER TABLE public.ai_processing_runs ADD CONSTRAINT ck_ai_processing_runs_state_payload CHECK ((status = 'processing' AND revision = 1 AND output IS NULL AND error_code IS NULL AND completed_at IS NULL AND rejected_at IS NULL) OR (status = 'succeeded' AND revision = 2 AND output IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL AND rejected_at IS NULL) OR (status IN ('failed', 'interrupted') AND revision = 2 AND output IS NULL AND error_code IN ('provider_timeout','provider_failure','invalid_provider_output','process_interrupted') AND error_code IS NOT NULL AND completed_at IS NOT NULL AND rejected_at IS NULL) OR (status = 'rejected' AND revision = 3 AND output IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL AND rejected_at IS NOT NULL) OR (status = 'accepted' AND revision = 3 AND output IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL AND rejected_at IS NULL))"""
_NEW_STATE = """ALTER TABLE public.ai_processing_runs ADD CONSTRAINT ck_ai_processing_runs_state_payload CHECK ((status = 'processing' AND revision = 1 AND output IS NULL AND error_code IS NULL AND completed_at IS NULL AND rejected_at IS NULL) OR (status = 'succeeded' AND revision = 2 AND output IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL AND rejected_at IS NULL) OR (status IN ('failed', 'interrupted') AND revision = 2 AND output IS NULL AND error_code IN ('provider_timeout','provider_failure','invalid_provider_output','process_interrupted','provider_auth','provider_throttled','provider_unavailable','provider_invalid_model','provider_invalid_request','provider_refused','provider_incomplete','insufficient_evidence','input_token_limit','provider_uncertain','provider_response_too_large') AND error_code IS NOT NULL AND completed_at IS NOT NULL AND rejected_at IS NULL) OR (status = 'rejected' AND revision = 3 AND output IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL AND rejected_at IS NOT NULL) OR (status = 'accepted' AND revision = 3 AND output IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL AND rejected_at IS NULL))"""
_METADATA_CHECK = """ALTER TABLE public.ai_processing_runs ADD CONSTRAINT ck_ai_processing_runs_bounded_processing_metadata CHECK ((status <> 'processing' OR processing_metadata IS NULL) AND (processing_metadata IS NULL OR (jsonb_typeof(processing_metadata) = 'object' AND octet_length(processing_metadata::text) <= 16384)))"""
_OLD_GUARD = """CREATE OR REPLACE FUNCTION public.hnh_ai_run_guard() RETURNS trigger
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
        END $$"""
_NEW_GUARD = """CREATE OR REPLACE FUNCTION public.hnh_ai_run_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$ BEGIN
        IF (to_jsonb(NEW) - ARRAY['status','revision','input_hash','output','output_hash','error_code','completed_at',
                'rejected_at','processing_metadata','accepted_at','accepted_draft_id','accepted_version_number','accepted_content_hash'])
            IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status','revision','input_hash','output','output_hash','error_code','completed_at',
                'rejected_at','processing_metadata','accepted_at','accepted_draft_id','accepted_version_number','accepted_content_hash'])
            OR NEW.revision <> OLD.revision + 1 THEN
            RAISE EXCEPTION 'AI request and evidence are immutable; updates require a revision' USING ERRCODE = '23514';
        END IF;
        IF OLD.status = 'processing' AND NEW.status IN ('succeeded','failed','interrupted') THEN RETURN NEW; END IF;
        IF OLD.status = 'succeeded' AND NEW.status IN ('rejected','accepted')
            AND NEW.output IS NOT DISTINCT FROM OLD.output AND NEW.error_code IS NOT DISTINCT FROM OLD.error_code
            AND NEW.completed_at IS NOT DISTINCT FROM OLD.completed_at
            AND NEW.processing_metadata IS NOT DISTINCT FROM OLD.processing_metadata THEN RETURN NEW; END IF;
        RAISE EXCEPTION 'AI terminal result is immutable' USING ERRCODE = '23514';
        END $$"""


def upgrade() -> None:
    op.add_column('ai_processing_runs', sa.Column('processing_metadata', postgresql.JSONB()), schema='public')
    op.execute("ALTER TABLE public.ai_processing_runs DROP CONSTRAINT ck_ai_processing_runs_state_payload")
    op.execute(_NEW_STATE)
    op.execute(_METADATA_CHECK)
    op.execute(_NEW_GUARD)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM public.ai_processing_runs
        WHERE coalesce(provenance->>'provider','') <> 'mock' OR processing_metadata IS NOT NULL) THEN
        RAISE EXCEPTION 'Cannot downgrade Gemini records or accounting metadata. Back up/export and obtain an explicit retention plan; immutable history was not changed.';
        END IF; END $$""")
    op.execute(_OLD_GUARD)
    op.execute("ALTER TABLE public.ai_processing_runs DROP CONSTRAINT ck_ai_processing_runs_bounded_processing_metadata")
    op.execute("ALTER TABLE public.ai_processing_runs DROP CONSTRAINT ck_ai_processing_runs_state_payload")
    op.execute(_OLD_STATE)
    op.drop_column('ai_processing_runs', 'processing_metadata', schema='public')
