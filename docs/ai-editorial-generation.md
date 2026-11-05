# HNW-P0-01: Serbian editorial draft generation

The story-review page links **Generiši srpski nacrt** to the existing private AI
workspace. Select a persisted source UUID, generate one suggestion, then use
**Uredi i pripremi prihvatanje**. Edit all publishing fields and explicitly confirm
acceptance. Only acceptance creates an immutable `origin="ai"` editorial version.
Fresh version, draft and suggestion reads verify persistence. Acceptance returns
the draft to editing, invalidating effective approval. There is no WordPress call,
automatic approval, publication or AI mutation of an existing version.

## Output and historical compatibility

New Gemini requests use prompt `sr-latn-ekavian-v2` and output schema 2: headline,
lead, body continuation, excerpt, SEO title (120 characters) and description (320),
source references and warnings. The lead is stored as the first body paragraph.
The adapter requests Serbian Ekavian Latin plain text. Source excerpts retain their
original language. Existing v1 and mock suggestions serialize without new optional
fields; no historical JSON, hashes, evidence or accepted versions are backfilled.

System instructions explicitly deny authority to source instructions. Evidence is
JSON in a separate user message; no tools, browsing or external source fetching are
available. UUID/hash/excerpt references and generated URLs are validated against
frozen evidence. Structured validation rejects invalid Latin/script/HTML/output,
missing fields and insufficient evidence. This cannot prove factual truth or defeat
every semantic prompt injection; human source comparison and review remain mandatory.

## Durable UTC daily budget (no migration)

Existing immutable `public.ai_processing_runs` reservations are the ledger. A global
PostgreSQL transaction advisory lock serializes budget checks and insertion across
processes/containers. Non-read-committed transaction configuration is rejected
before dispatch to prevent stale-snapshot undercounting. Database time determines the UTC day. Every Gemini reservation
counts, including failures, interruption, uncertain completion and later acceptance
or rejection. There are no refunds. Replaying an existing command checks the sealed
receipt before budget/provider availability and makes no new generation request.

`AI_DAILY_GENERATION_LIMIT` defaults to 10 (0 disables new reservations, maximum
100). Each reservation freezes the current daily ceiling. The lowest ceiling in a
day remains effective that day even after a configuration increase; increases take
effect on the next UTC day. This is an attempt ceiling, not a currency guarantee.
Historical Gemini runs that predate this field also count. Database failure, lock
failure or timeout prevents dispatch. The count query is bounded to the configured
limit but may scan a growing archive: add a global creation-time/provider index in
a later performance migration if needed. All generation-enabled processes must run this version and share the same database
and reviewed budget configuration. Disable AI while replacing older instances that
do not participate in reservation locking. Existing statement/lock timeouts fail
closed. No new privileges, tables or migrations are required; migration head stays
`20261104_08`. No downgrade or data rewrite is performed for this change.

## Self-hosted opt-in (not activated by this implementation)

The base `docker-compose.selfhosted.yml` still hard-disables AI. The optional
`docker-compose.selfhosted.ai.yml` overlay is the only supplied operational opt-in.
Do not apply it until authentication, TLS ingress, migration head, runtime grants,
backup and provider data-processing approval have been reviewed. It requires:

- `HNW_AUTH_ENABLED=true` (existing verified opaque-session authentication).
- `HNW_GEMINI_MODEL`: an administrator-verified available structured-output model;
  there is no default model or substitution.
- `HNW_GEMINI_API_KEY_FILE`: absolute protected file, readable by API container GID.
- `HNW_AI_DAILY_GENERATION_LIMIT=10` or a smaller approved ceiling.
- Input/output ceilings at most 4096/2048; retries exactly 0; request deadline 30s.

The key is mounted only on the API as a Docker file secret and never in frontend
variables. File-only loading rejects ambiguous key environment/file configuration.
A zero daily ceiling is a service-level denial setting; the self-hosted Gemini
opt-in rejects it at startup. Use the base composition to disable operational AI
while retaining historical access. Invalid opt-in, disabled authentication, mock selection or excessive token limits
fails startup. Capability reporting performs local checks only, never provider
requests, and does not promise upstream model availability or remaining budget.

Example configuration validation (not deployment):

```bash
docker compose --env-file /path/to/protected/selfhosted.env \
  -f docker-compose.selfhosted.yml -f docker-compose.selfhosted.ai.yml config --quiet
```

Only an authorized administrator may subsequently recreate the local/staging API
with the reviewed overlay; this task does not do so. Provider requests send source
text to Google; assess privacy and rights before opt-in. An ambiguous paid request
is not retried. Reported usage is retained; cost remains explicitly unknown.

## Local verification without paid calls

Use PostgreSQL 16 disposable test resources and the existing restricted runtime
fixture. No production database or credentials:

```bash
cd backend
RUN_POSTGRES_TESTS=1 PYTHONPATH=.:tests python -B -m unittest discover -s tests -v
# Supply the existing POSTGRES_* test connection settings for a disposable PG16.
cd ../frontend
npm test
npm run typecheck
npm run build
npm run build:selfhosted
node tests/browser/ai-workspace.mjs
cd ..
python3 deploy/selfhosted/validate.py
git diff --check
```

The Gemini test transport is always mocked. Production smoke testing must begin
with AI disabled and login/role/CSRF/readiness checks. Live provider use requires
separate authorization, a current model check and one bounded request. Do not
blindly retry a timeout: recover the original command and inspect its persisted
status/history. Local unsaved edits/uncertain command intent are tab-local; navigate
only after resolving or explicitly discarding them.

## Rollback

Remove the optional AI overlay and recreate only the API with the same accepted
release after review; this stops new generation while leaving historical suggestion
reads and acceptance of already completed suggestions available. Existing command
replay remains available. Reverting application code requires attention to v2 data:
older binaries cannot read v2 requests/output; prefer disabling AI over rolling
back to a v1-only binary after new data exists. Preserve the database and backups;
never delete processing history to reset the budget.
