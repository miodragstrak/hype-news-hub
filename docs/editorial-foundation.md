# Editorial security and database foundation — Sprint 17A

Sprint 17A.1 added security boundaries and storage. Sprint 17A.2 adds authenticated
PostgreSQL editorial commands and reads; see [workflow contracts](editorial-workflow.md).
Sprint 17A.3 implements the authenticated frontend editor, version history, review
decisions and approved preview; see [frontend integration](editorial-frontend.md).
Production identity activation, AI generation and WordPress delivery remain separate work.
No AI/WordPress credentials, production identity credentials, dependencies, Render
settings, Vercel settings or Docker deployment definitions are added.

## Identity boundary and authorization

`app/core/editorial_security.py` defines the async `EditorialIdentityVerifier`
protocol and immutable `EditorialPrincipal(issuer, subject, roles)`. A verifier
must verify credentials and map trusted roles on the server. A future adapter
must perform the validation appropriate to its identity system (for example,
signature, issuer, audience, expiry and key rotation for signed access tokens).
No JWT decoding or unverified claim acceptance is provided in this phase.

`create_app(..., editorial_identity_verifier=...)` is a server-side composition
point. The default verifier always reports unavailable. There is no environment
switch, development login, shared password, magic header or request option that
installs a verifier. Without a production adapter, private access remains denied.

The only fake verifier is `backend/tests/editorial_identity.py`, an automated-test
fixture injected into test applications. Application code never imports it. The
backend runtime image copies only `app/`, excluding tests and fixture identities.
Never install this fixture in a deployed application.

`app/api/editorial_security.py` supplies the FastAPI permission dependency. It
checks a Bearer credential, asks the configured verifier for a principal, checks
permission, then verifies PostgreSQL availability, the existing restricted runtime
role and read access to all five editorial tables. Unauthorized users do not probe
the database. A verified principal alone cannot enable private access in memory mode.
Successful protected responses receive `Cache-Control: no-store`.

| Role | Permissions |
| --- | --- |
| Reader | `editorial:read` |
| Editor | Read, `editorial:edit`, `editorial:submit` |
| Reviewer | Read, `editorial:review` |
| Publisher | Read, `editorial:deliver` |
| Administrator | All six permissions, including `editorial:administer` |

Multiple trusted roles combine permissions. Editor does not imply Reviewer or
Publisher. Actors/roles are never taken from query parameters, bodies or identity
headers. These application roles do not grant database ownership or DDL permission.

## Protected capability endpoint

`GET /api/editorial/capabilities` uses `require_editorial_permission(READ)` and
returns only verified roles, logical permissions, `storage: "postgres"`, and
`commands_enabled` boolean. It is true for identities with Edit, Submit or Review
permission after the PostgreSQL boundary succeeds; Reader/Publisher alone return
false. No private draft content is exposed through this endpoint. The private
workflow endpoints apply their own permission dependencies on every request.

- Missing/invalid credentials: HTTP 401 and `WWW-Authenticate: Bearer`.
- Valid identity lacking permission: HTTP 403.
- Unconfigured/failed identity verification: HTTP 503.
- Memory mode, missing PostgreSQL credentials, unavailable storage, schema-owner
  credentials, missing editorial tables or SELECT grants: HTTP 503.

Provider exception text and tokens are not returned or logged. Unexpected verifier
errors are sanitized and fail closed. PostgreSQL failures use the existing safe
storage error handler; there is no memory fallback.

Existing public API paths and response models remain unchanged. The private
capability boolean now reflects enabled command permissions instead of literal false.
Legacy public story/workspace projections continue to read collection data and
the existing explicitly labelled in-memory demo override. They never join the new
editorial tables. Future private content routes must reuse the permission boundary;
do not attach private drafts to unprotected legacy responses.

## Five additive tables

| Table | Data and constraints |
| --- | --- |
| `editorial_drafts` | Stable UUID and restricted story FK; unique story/`sr-Latn` locale; editorial status; current version number; positive optimistic concurrency revision; immutable creator identity; created/updated timestamps. |
| `editorial_draft_versions` | Immutable numbered versions, schema-versioned JSON object payload, generated SHA-256 content hash, origin (`manual`, `imported`, future `ai`), creator identity, creation timestamp and required source count. |
| `editorial_version_sources` | Version FK; source/article UUID composite FK; source name/URL, external ID, original/canonical URLs, publication timestamp, exact captured input text, capture timestamp and generated snapshot hash. One article per version. |
| `editorial_decisions` | Exact draft/version/content-hash FK, approve/reject/request-changes decision, actor and timestamp; negative decisions require a nonblank reason. |
| `editorial_events` | Draft and optional version FKs, event/state metadata, actor and timestamp; optional command UUID paired with request hash and unique within its draft. |

Status values are `editing`, `in_review`, `changes_requested`, `approved`, and
`rejected`. They are independent of collection status and future delivery status.
Source/article UUID association is checked even when two sources use the same
WordPress external ID. Source-name/URL text is frozen attribution, not a live join.

### Database guards

- Historical versions, source snapshots, decisions and events reject row UPDATE
  and DELETE through database triggers, including accidental owner DML.
- A deferred constraint requires exactly the declared positive number of source
  snapshots at commit. A version and all snapshots must be inserted atomically.
  A committed version cannot later acquire additional sources.
- A composite FK prevents a draft head from pointing to another draft's version.
  A deferred guard requires an approval decision for the exact current version
  before `approved` state can commit. Decision hashes are tied to version content.
- Draft identity/creator cannot change, head version cannot move backwards, and
  each update must increment `revision` exactly once. SQLAlchemy uses the revision
  in its update predicate and reports stale writes. Raw writers must also compare
  the expected revision in their WHERE clause; incrementing alone is not CAS.
- Immutable history has restricted foreign keys rather than delete cascades.

The schema provides structural constraints; the Sprint 17A.2 command service now
implements permissions, actor construction, payload validation, transitions,
idempotency and HTTP conflict responses. Both previously deferred requirements
are enforced there:

- Effective approval requires approved head state and its exact revision's
  approval command/decision for the current version/hash. Historical approvals
  alone never qualify. Unpaired legacy decisions fail closed.
- Every command update uses `WHERE id = :id AND revision = :expected_revision`,
  checks affected rows, and increments once. Locks supplement this predicate.
  Creation requires revision zero and uniqueness; it inserts revision one.
  State, versions, decisions and events commit together. Maintenance/raw SQL must
  follow this same protocol; the DB increment guard alone is not a CAS or full
  effective-decision policy. Owner access remains outside application authorization.

### Hash format and provenance

`content_hash` is UTF-8 SHA-256 of PostgreSQL's JSONB text representation of the
payload. `snapshot_hash` covers a JSONB array of source/article UUIDs, frozen source
identity, external ID, URLs, publication timestamp, input text and capture timestamp.
Dates use an explicit numeric UTC format, independent of session TimeZone/DateStyle.
Hashes are database-generated; callers cannot supply them. Verify serialization
and restore behavior before a future PostgreSQL major-version change.

Snapshots preserve the exact text captured for a version. They do not claim to
recover earlier collection observations. The existing collector remains a latest
projection and can refresh article content without changing editorial snapshots.
Revision commands copy prior selected snapshots verbatim, including their capture
timestamps. Newly selected story members are captured from one consistent joined
SQL statement. Input text joins nonempty title, excerpt and content, in that order,
with two newlines; each original value is preserved verbatim. No HTML rendering or
instruction channel is added. Source text remains untrusted, even inside a snapshot.

## Migrations and runtime security

The migration chain is `20261030_01 → 20261030_02 → 20261030_03`.
Migration `20261030_03_editorial_foundation.py` follows `20261030_02`. Existing
migrations and collection tables are unchanged. It creates the five tables,
indexes, hash function and guards; it does not backfill editorial records or infer
approval from collection/demo states. Schema changes are explicit owner operations.

Using the protected local/self-hosted credentials prepared in `docs/postgresql.md`:

```bash
docker compose --profile tools run --rm --build migrate
docker compose --profile tools run --rm --build provision-runtime
```

Provision after migration, before enabling private features. Sprint 17A.4 resets
direct table **and column** ACLs, then grants these explicit allowlists:

| Tables | Runtime privileges |
| --- | --- |
| `news_sources`, `collected_articles`, `article_identities`, `stories`, `story_articles`, `collection_runs`, `collection_source_results` | SELECT, INSERT, UPDATE |
| `editorial_drafts` | SELECT, INSERT, UPDATE |
| `editorial_draft_versions`, `editorial_version_sources`, `editorial_decisions`, `editorial_events` | SELECT, INSERT |

No DELETE, TRUNCATE, REFERENCES, TRIGGER or grant options are allowed, including
column-level REFERENCES and historical UPDATE. CONNECT, schema USAGE and the two
hash functions' EXECUTE grants remain. No ownership, schema CREATE, DDL or
migration-table access is granted. No new migration is needed for this correction.
Sprint 17A.4.1 binds every ORM/Core table to `public`, so session search-path drift
and readable historical shadow tables cannot substitute unapproved content or
source evidence under unchanged hashes. Engines restore a trusted path on checkout;
security catalogs and raw application table references are explicitly qualified.

Non-owning, non-privileged memberships are detached from the dedicated runtime
login, closing inherited and SET ROLE paths without changing shared group ACLs
or unrelated users. Privileged/owning identities or membership paths are rejected.
Revocation uses RESTRICT; dependent grants to other users require administrator
review rather than automatic CASCADE. Effective table/column privileges, grant
options, PUBLIC access and memberships are checked before commit; any failure
rolls back password, membership and ACL changes together. Re-provisioning is idempotent.

PUBLIC table/column grants cannot be denied for just this login. Provisioning
therefore **refuses** them, with table/column/privilege diagnostics, and leaves
shared ACLs unchanged. An administrator must review their consumers, replace any
intentional shared access with named-role grants, explicitly revoke PUBLIC grants,
and rerun provisioning. See [operational prerequisites](postgresql.md#runtime-role-provisioning).
The runtime guard denies unsafe existing logins until this process succeeds;
merely deploying code or applying migrations does not repair grants.
Database CREATE, CREATE on any schema, and ownership of databases, schemas or
relations in any namespace are now rejected by the runtime guard. Provisioning
transactionally revokes manageable direct CREATE grants and detaches non-owning
membership paths. PUBLIC CREATE needs administrator review; existing owned shadow
objects need explicit administrator disposition, not automatic deletion/reassignment.
Re-provision even previously hardened runtime roles. See the
[trusted-schema policy and raw SQL boundary](postgresql.md#trusted-application-schema--sprint-17a41).

Administrator application permission still uses the restricted database role.
Database owner maintenance is privileged: triggers do not make history tamper-proof
against an owner able to change DDL or explicitly truncate tables. Owner credentials
must never enter API configuration.

Downgrading to `20261030_02` removes editorial tables/functions and **loses editorial
data**, while retaining collection data. Back up/export editorial records before
an operator-approved downgrade. Do not run downgrade as an application startup or
recovery shortcut. See `docs/postgresql.md` for backup/recovery procedures.

## Verification

Backend tests use Python 3.12 and the existing disposable PostgreSQL 16 test
service. The inherited integration guard refuses non-test/nonempty databases.
Production tests never accept fixture identities by an environment flag.

```bash
# With local protected test credentials prepared, from repository root:
docker compose --profile test run --rm --build database-tests

cd frontend
npm test
npm run typecheck
npm run build
```

Coverage includes denied/forged identity claims, role boundaries, provider failures,
memory-mode refusal, private-content non-disclosure, immutable history, complete
source snapshots, hash/version references, revision conflicts through independent
database connections, owner/runtime restrictions, missing migrations/grants,
rollback and populated upgrade/downgrade/reupgrade preservation. Existing tests
continue to cover collection concurrency, process termination recovery and URLs.
Permission regressions commit the legacy TRUNCATE exploit on the disposable
database, then prove denial after re-provisioning. They exercise direct/PUBLIC
and column drift, grant options, nested inheritance, SET ROLE, privileged/owning
identities, shared-consumer preservation, repeated provisioning and transactional
rollback (including a real dependent-grant failure).

## Remaining work

Production identity adapter and deployment access controls, explicit evidence
refresh, durable job execution,
AI provider adapters and WordPress Draft idempotency/reconciliation are not enabled.
Existing public collection and demo-preview behavior remains compatible on Render.
