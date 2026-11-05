# Sprint 14D: security remediation and activation prerequisites

This is the operational `feat/selfhosted-production` application. It contains no
client-preview simulation. No remote server, production identity, live AI or
WordPress integration is activated by these changes.

## Request authority and authentication

The outermost self-hosted ASGI middleware validates one exact Host authority
against `HNW_PUBLIC_ORIGIN`, rejects URL delimiters, userinfo, malformed ports,
unexpected hosts, duplicate Host headers and invalid request targets. Forwarded
Host/URL headers never grant access. Security checks use ASGI `scope["path"]`,
which is also the routing input, with no second percent-decoding. The Nginx
configuration must preserve `/api` and not mount/rewrite the app under a prefix.
Absolute-form targets that a server normalizes to origin-form still require
normal authentication; visible raw absolute-form ASGI targets are rejected.

The only alternate authority is `127.0.0.1:8000` / `[::1]:8000`, for GET health
checks from a loopback peer. It cannot access API routes. Invalid authority returns
a generic 400 even when auth is disabled; a valid protected request without auth
returns 401 when enabled and 503 when disabled. Nginx validation is an additional
layer, not the application authorization boundary. Do not trust broad proxy CIDRs.

FastAPI 0.136.3 and Starlette 1.3.1 are a compatible pinned pair. Older migration
revisions remain unchanged. The existing JSON-without-Content-Type contract is
retained explicitly; strict editorial UTF-8/media validation and cookie CSRF
checks still apply. FastAPI adds optional `input`/`ctx` fields to its generic
ValidationError OpenAPI schema; existing required fields and endpoint contracts
are unchanged. Self-hosted/private validation responses remain sanitized and do
not reflect these fields. The self-hosted Python 3.12 image installs pip 26.2
and `backend/requirements.selfhosted.lock`; refresh the complete lock intentionally,
run `pip check`, audit it and rebuild images. Record image digests as well: Docker
base tags are not immutable dependency locks.

## Login budget isolation

The PostgreSQL advisory transaction lock still serializes rate-limit accounting
across processes. Limits remain 10/IP, 5/account and 30/global per 60 seconds.
All three budgets admit a login atomically or charge none. An exhausted IP or
account is rejected without consuming global capacity. Counts include successful
and unsuccessful admitted logins; no password attempt bypasses the global limit.
The existing fixed hashed bucket space remains bounded; collisions intentionally
fail stricter. Distributed traffic can still exhaust the deliberate global cap.
Sale should consider a narrowly scoped Nginx login request limit after measuring
normal newsroom usage, without changing AskHype's locations or shared policies.

## Account-security history and migration 08

`20261104_08` follows `20261104_07` and is forward-only. It adds
`public.app_security_events`; there are now 18 application tables. Provision again
after upgrade. Runtime receives SELECT/INSERT only on this new table, with no
UPDATE, DELETE, TRUNCATE, grant options or DDL. A trigger also rejects row UPDATE
and DELETE; existing editorial history and prior migration files are unchanged.

Account creation, activation/deactivation, role changes, unchanged administrative
updates, and rejected duplicate/stale/last-admin changes record attributable events.
Existing pre-08 accounts are preserved without inventing historical events.
Successful changes and their events share one transaction. An event-write failure
rolls back the account change. Known rejected administrator commands persist a
conflict event without changing the account. Requests rejected before the command
service (invalid credentials, missing permissions, malformed payloads) do not create
account events. Generic access logs remain separate; this is not a complete login
security-monitoring system.

Events contain verified actor UUID/issuer/subject, target UUID, action, outcome,
DB timestamp, safe previous/current role/status and revision. They contain no
password, hash, session token, cookie, CSRF proof, arbitrary request JSON or email.
Bootstrap records the authenticated database role as actor under a distinct fixed
bootstrap issuer. There is no new public audit endpoint. Owner inspection example:

```sql
SELECT occurred_at, actor_issuer, actor_subject, target_user_id, action, outcome,
       previous_role, new_role, previous_active, new_active, target_revision
FROM public.app_security_events
ORDER BY occurred_at DESC LIMIT 100;
```

## Session retention: explicit owner maintenance

Suggested initial retention is **30 days after expiry or revocation**; Sale must
confirm the policy. It does not change the absolute authentication lifetime
(`HNW_AUTH_SESSION_SECONDS`, default eight hours). Nothing deletes sessions during
startup and the runtime still cannot DELETE. Use only the Hype World News owner
tool/database, after a backup. Never run against AskHype or grant runtime DELETE.

Using the `hnw_compose` helper defined in the deployment runbook:

```bash
hnw_compose exec -T news-db sh -c 'export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"; exec psql -X -v ON_ERROR_STOP=1 -v retention_days=30 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
BEGIN;
SET LOCAL statement_timeout = '5s';
SET LOCAL lock_timeout = '1s';
WITH batch AS (
  SELECT token_hash FROM public.app_sessions
  WHERE expires_at < clock_timestamp() - make_interval(days => :retention_days)
     OR revoked_at < clock_timestamp() - make_interval(days => :retention_days)
  ORDER BY expires_at LIMIT 1000 FOR UPDATE SKIP LOCKED
)
DELETE FROM public.app_sessions s USING batch b WHERE s.token_hash = b.token_hash;
COMMIT;
SQL
```

Choose a positive retention_days value under the approved policy. Each invocation
removes at most 1000 already inactive sessions; repeat deliberately as needed.
It never deletes users, security events or editorial history. Monitor
`pg_stat_user_tables.n_live_tup`, `n_dead_tup`, `last_autovacuum` and
`pg_total_relation_size('public.app_sessions')`, plus volume/free disk and backup
size. Do not routinely VACUUM FULL or TRUNCATE. Review security-event retention
separately; do not bypass immutability for routine cleanup.

## Static server and dependency advisory handling

The web image uses `frontend/runtime/package.json` and its dedicated lockfile,
installed using `npm ci --omit=dev --ignore-scripts`. It runs the local Serve binary
as non-root with **--no-compression**. Its compression dependency is also patched
to 1.8.2; disabling the feature alone is only a mitigation, not an advisory fix.
Patched overrides also cover minimatch, Ajv and on-headers. Audit the final installed
tree as well as the app lockfile; the app's `npm audit` does not inspect this package.
SPA routing and the normal Vite production build remain separate and supported.

React Router is patched within v6 to 6.30.6 for GHSA-jjmj-jmhj-qwj2. Remaining
GHSA-wrjc-x8rr-h8h6 (backslash navigation) and GHSA-337j-9hxr-rhxg (SSR hydration)
require 7.18+ for complete upstream remediation. No SSR/hydration is used here;
navigation targets are fixed internal paths or UUID-derived routes, not untrusted
redirect URLs. These are **unresolved conditional advisories**, not patched ones.
Do not claim a clean app audit. A Router v7 migration is a separately tested change;
review this residual exposure before activation and keep navigation inputs bounded.

Vite remains on v7 (7.3.7), PostCSS on v8 (8.5.23); affected build transitive packages
are refreshed within their compatible major ranges. Serve remains on v14. No
unrelated major migration is introduced. Re-run all three audits after future
lock changes and monitor upstream notices; registry data can change after review.

## Sale's activation checklist

- Independent security recheck of these fixes and residual advisory disposition.
- Back up; upgrade through 08; rerun runtime provisioning; inspect grants and events.
- Initial admin bootstrap once (or existing accounts preserved); separate author
  and reviewer accounts; no Editor approval privilege.
- Confirm exact origin, actual Nginx peer, overwritten X-Real-IP, TLS and Host checks.
- Dedicated Compose name, private DB, unused loopback ports, no accidental public
  API/DB binding, and no changes to AskHype networks/ACLs/vhosts.
- Verify no compressed responses from the web image, SPA direct-route refreshes,
  cookie security, CSRF, login budget isolation, deactivation and session expiry.
- Verify backups/restores, logs/retention, disk/OOM/health alerts and AskHype baseline.
- Retain compatible image pairs/digests. Revisions 07/08 refuse downgrade; restore
  to a separate database when image-only rollback is incompatible.
- Keep AUTH_ENABLED=false/ingress denied until approved. Keep AI disabled.
