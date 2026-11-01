"""Persisted single-source mock suggestions; collection/editorial history unchanged.

Downgrade removes AI requests, evidence, suggestions and recovery events only.
"""
from alembic import op

revision = "20261101_04"
down_revision = "20261030_03"
branch_labels = None
depends_on = None

# Frozen DDL: no runtime model imports or dependency on future model changes.
_TABLE_DDL = (
    """CREATE TABLE public.ai_processing_runs (
	story_id UUID NOT NULL,
	article_id UUID NOT NULL,
	source_id UUID NOT NULL,
	command_id UUID NOT NULL,
	actor_issuer TEXT NOT NULL,
	actor_subject TEXT NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	target_locale VARCHAR(16) NOT NULL,
	mode VARCHAR(24) NOT NULL,
	status VARCHAR(16) NOT NULL,
	revision INTEGER NOT NULL,
	input_payload JSONB NOT NULL,
	input_hash VARCHAR(64) GENERATED ALWAYS AS (public.hnh_identity_hash(input_payload::text)) STORED NOT NULL,
	provenance JSONB NOT NULL,
	output JSONB,
	output_hash VARCHAR(64) GENERATED ALWAYS AS (public.hnh_identity_hash(output::text)) STORED,
	error_code VARCHAR(40),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE,
	rejected_at TIMESTAMP WITH TIME ZONE,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	CONSTRAINT pk_ai_processing_runs PRIMARY KEY (id),
	CONSTRAINT fk_ai_processing_runs_article_id_collected_articles FOREIGN KEY(article_id, source_id) REFERENCES public.collected_articles (id, source_id) ON DELETE RESTRICT,
	CONSTRAINT uq_ai_processing_runs_command UNIQUE (command_id),
	CONSTRAINT ck_ai_processing_runs_valid_status CHECK (status IN ('processing', 'succeeded', 'failed', 'interrupted', 'rejected')),
	CONSTRAINT ck_ai_processing_runs_valid_revision CHECK (revision BETWEEN 1 AND 3),
	CONSTRAINT ck_ai_processing_runs_supported_processing CHECK (target_locale = 'sr-Latn' AND mode = 'translation'),
	CONSTRAINT ck_ai_processing_runs_actor_not_blank CHECK (btrim(actor_issuer) <> '' AND btrim(actor_subject) <> ''),
	CONSTRAINT ck_ai_processing_runs_request_hash_format CHECK (request_hash ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_ai_processing_runs_bounded_input CHECK (jsonb_typeof(input_payload) = 'object' AND octet_length(input_payload::text) <= 262144),
	CONSTRAINT ck_ai_processing_runs_input_identity CHECK (coalesce((input_payload->>'request_id' = id::text AND input_payload->>'story_id' = story_id::text AND input_payload->'source'->>'article_id' = article_id::text AND input_payload->'source'->>'source_id' = source_id::text AND input_payload->>'mode' = mode AND input_payload->>'target_locale' = target_locale AND coalesce(octet_length(input_payload->'source'->>'input_text'), 0) BETWEEN 1 AND 65536 AND input_payload->'source'->>'input_text_hash' = public.hnh_identity_hash(input_payload->'source'->>'input_text')), false)),
	CONSTRAINT ck_ai_processing_runs_provenance_object CHECK (jsonb_typeof(provenance) = 'object'),
	CONSTRAINT ck_ai_processing_runs_bounded_output CHECK (output IS NULL OR (jsonb_typeof(output) = 'object' AND octet_length(output::text) <= 65536)),
	CONSTRAINT ck_ai_processing_runs_valid_timestamps CHECK (expires_at > created_at AND (completed_at IS NULL OR completed_at >= created_at) AND (rejected_at IS NULL OR rejected_at >= completed_at)),
	CONSTRAINT ck_ai_processing_runs_state_payload CHECK ((status = 'processing' AND revision = 1 AND output IS NULL AND error_code IS NULL AND completed_at IS NULL AND rejected_at IS NULL) OR (status = 'succeeded' AND revision = 2 AND output IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL AND rejected_at IS NULL) OR (status IN ('failed', 'interrupted') AND revision = 2 AND output IS NULL AND error_code IN ('provider_timeout','provider_failure','invalid_provider_output','process_interrupted') AND error_code IS NOT NULL AND completed_at IS NOT NULL AND rejected_at IS NULL) OR (status = 'rejected' AND revision = 3 AND output IS NOT NULL AND error_code IS NULL AND completed_at IS NOT NULL AND rejected_at IS NOT NULL)),
	CONSTRAINT fk_ai_processing_runs_story_id_stories FOREIGN KEY(story_id) REFERENCES public.stories (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE public.ai_processing_events (
	run_id UUID NOT NULL,
	revision INTEGER NOT NULL,
	action VARCHAR(40) NOT NULL,
	status VARCHAR(16) NOT NULL,
	command_id UUID,
	request_hash VARCHAR(64),
	actor_issuer TEXT NOT NULL,
	actor_subject TEXT NOT NULL,
	reason TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	CONSTRAINT pk_ai_processing_events PRIMARY KEY (id),
	CONSTRAINT uq_ai_processing_events_revision UNIQUE (run_id, revision),
	CONSTRAINT uq_ai_processing_events_command UNIQUE (command_id),
	CONSTRAINT ck_ai_processing_events_valid_revision CHECK (revision BETWEEN 1 AND 3),
	CONSTRAINT ck_ai_processing_events_valid_status CHECK (status IN ('processing', 'succeeded', 'failed', 'interrupted', 'rejected')),
	CONSTRAINT ck_ai_processing_events_valid_action CHECK (action IN ('generation.requested','generation.succeeded','generation.failed','generation.interrupted','suggestion.rejected')),
	CONSTRAINT ck_ai_processing_events_actor_not_blank CHECK (btrim(actor_issuer) <> '' AND btrim(actor_subject) <> ''),
	CONSTRAINT ck_ai_processing_events_command_hash_pair CHECK ((command_id IS NULL AND request_hash IS NULL) OR (command_id IS NOT NULL AND request_hash ~ '^[0-9a-f]{64}$' AND request_hash IS NOT NULL)),
	CONSTRAINT ck_ai_processing_events_bounded_reason CHECK (reason IS NULL OR (btrim(reason) <> '' AND char_length(reason) <= 2000)),
	CONSTRAINT ck_ai_processing_events_event_shape CHECK ((revision = 1 AND action = 'generation.requested' AND status = 'processing' AND command_id IS NOT NULL AND reason IS NULL) OR (revision = 2 AND action = 'generation.' || status AND status IN ('succeeded','failed','interrupted') AND command_id IS NULL AND reason IS NULL) OR (revision = 3 AND action = 'suggestion.rejected' AND status = 'rejected' AND command_id IS NOT NULL AND reason IS NOT NULL)),
	CONSTRAINT fk_ai_processing_events_run_id_ai_processing_runs FOREIGN KEY(run_id) REFERENCES public.ai_processing_runs (id) ON DELETE RESTRICT
)""",
    """CREATE INDEX ix_ai_processing_runs_story_created ON public.ai_processing_runs (story_id, created_at, id)""",
)


def upgrade() -> None:
    for statement in _TABLE_DDL:
        op.execute(statement)
    op.execute("""CREATE FUNCTION public.hnh_ai_run_guard() RETURNS trigger
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
        END $$""")
    # BEFORE triggers cannot compare newly computed generated hashes: PostgreSQL
    # computes them afterward. Compare input/output payloads themselves instead.
    op.execute("CREATE TRIGGER hnh_ai_run_guard BEFORE UPDATE ON public.ai_processing_runs "
               "FOR EACH ROW EXECUTE FUNCTION public.hnh_ai_run_guard()")
    op.execute("""CREATE FUNCTION public.hnh_ai_history_immutable() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$ BEGIN
        RAISE EXCEPTION 'AI history is immutable' USING ERRCODE = '23514'; END $$""")
    op.execute("CREATE TRIGGER hnh_ai_history_immutable BEFORE UPDATE OR DELETE ON public.ai_processing_events "
               "FOR EACH ROW EXECUTE FUNCTION public.hnh_ai_history_immutable()")
    op.execute("CREATE TRIGGER hnh_ai_run_no_delete BEFORE DELETE ON public.ai_processing_runs "
               "FOR EACH ROW EXECUTE FUNCTION public.hnh_ai_history_immutable()")
    op.execute("""CREATE FUNCTION public.hnh_ai_event_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$ DECLARE
            identity uuid; head public.ai_processing_runs%ROWTYPE; actual bigint;
        BEGIN
            IF TG_TABLE_NAME = 'ai_processing_runs' THEN identity := NEW.id; ELSE identity := NEW.run_id; END IF;
            SELECT * INTO head FROM public.ai_processing_runs WHERE id = identity;
            SELECT count(*) INTO actual FROM public.ai_processing_events WHERE run_id = identity;
            IF head.id IS NULL OR actual <> head.revision OR NOT EXISTS (
                SELECT 1 FROM public.ai_processing_events e WHERE e.run_id = identity
                    AND e.revision = head.revision AND e.status = head.status
            ) OR NOT EXISTS (
                SELECT 1 FROM public.ai_processing_events e WHERE e.run_id = identity AND e.revision = 1
                    AND e.command_id = head.command_id AND e.request_hash = head.request_hash
                    AND e.actor_issuer = head.actor_issuer AND e.actor_subject = head.actor_subject
            ) THEN
                RAISE EXCEPTION 'AI transition requires complete atomic command history' USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END $$""")
    for table in ('ai_processing_runs', 'ai_processing_events'):
        op.execute(f"CREATE CONSTRAINT TRIGGER hnh_ai_events_complete AFTER INSERT OR UPDATE ON public.{table} "
                   "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.hnh_ai_event_guard()")
        op.execute(f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC")
    for function in ('hnh_ai_run_guard', 'hnh_ai_history_immutable', 'hnh_ai_event_guard'):
        op.execute(f"REVOKE ALL ON FUNCTION public.{function}() FROM PUBLIC")


def downgrade() -> None:
    op.drop_table('ai_processing_events', schema='public')
    op.drop_table('ai_processing_runs', schema='public')
    for function in ('hnh_ai_event_guard', 'hnh_ai_history_immutable', 'hnh_ai_run_guard'):
        op.execute(f"DROP FUNCTION public.{function}()")
