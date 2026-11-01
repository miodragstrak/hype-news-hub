# Private editorial workflow — Sprint 17A

The existing modular monolith now supports manual PostgreSQL editorial work.
The [editorial frontend](editorial-frontend.md) supports manual editing, version
history, review decisions and version-pinned approved preview. AI providers,
WordPress delivery and production identity activation remain separate work.
No production credentials or deployment settings are included. Memory mode remains the
default and cannot execute these commands. Public collection/demo projections
do not join private tables or acquire new response fields.

## Security and preparation

Use the existing migration/provisioning commands in [PostgreSQL operations](postgresql.md).
The migration chain is `20261030_01 → 20261030_02 → 20261030_03`; revision `20261030_03` supports the
workflow, source snapshots, append-only history and command receipts. Revisions
01/02/03 are unchanged by Sprints 17A.4/17A.4.1; these corrections need no new migration.
Before PostgreSQL startup, re-provision existing runtime logins to reset table and
column ACLs to the documented allowlists. PUBLIC grants or dependent grants issued
by the runtime login require administrator review first; provisioning never
silently rewrites shared ACLs. Until correction, the runtime guard fails closed.
All editorial/collection ORM and Core operations explicitly target `public` tables.
Sprint 17A.4.1 also requires no effective database/schema CREATE and no database,
schema or relation ownership, including outside public. Re-provision existing
roles; review PUBLIC CREATE and unexpected shadow objects as an administrator.
The connection path is restored on pool checkout, but correctness does not rely
on that mutable setting alone. See [trusted schema operations](postgresql.md#trusted-application-schema--sprint-17a41).

A trusted server-side `EditorialIdentityVerifier` must be composed into `create_app`.
The default verifier always denies private access; no configuration flag, test
token or client-supplied identity enables it. Automated tests inject the isolated
fixture provider. Production identity integration remains separate work.
All endpoints require Bearer authentication and configured, restricted PostgreSQL.
Missing credentials return 401, insufficient permission 403, and unavailable
verification/storage or memory mode 503. Actor issuer/subject come exclusively
from the verified principal. Request models reject extra actor/role fields.
Successful private responses use `Cache-Control: no-store`.

## REST contracts

Paths below are under `/api/editorial`. OpenAPI documents the full schemas.
Role permissions compose; Administrator includes all permissions. Publisher alone
has read access here and cannot deliver anything in this sprint.

| Method / path | Permission | Input / result |
| --- | --- | --- |
| GET `/stories/{story_id}/sources` | Read | Paginated source summaries with stable article/source UUID pairs; no writes. |
| POST `/drafts` | Edit | `CreateDraft`; 201 `CommandResult`. |
| GET `/drafts?story_id={uuid}` | Read | The story's sr-Latn workspace, or 404. |
| GET `/drafts/{draft_id}` | Read | Head revision/state, current immutable payload/sources and effective approval. |
| POST `/drafts/{draft_id}/revisions` | Edit | `SaveRevision`; new immutable version; 200 `CommandResult`. |
| POST `/drafts/{draft_id}/submit` | Submit | `VersionCommand`; 200 `CommandResult`. |
| POST `/drafts/{draft_id}/approve` | Review | `DecisionCommand`; optional reason; 200 `CommandResult`. |
| POST `/drafts/{draft_id}/request-changes` | Review | `NegativeDecisionCommand`; required reason. |
| POST `/drafts/{draft_id}/reject` | Review | `NegativeDecisionCommand`; required reason. |
| POST `/drafts/{draft_id}/reopen` | Edit | `NegativeDecisionCommand`; required reason recorded in audit. |
| GET `/drafts/{draft_id}/versions` | Read | Lightweight, paginated immutable version metadata; excludes payloads and snapshots. |
| GET `/drafts/{draft_id}/versions/{version_number}` | Read | One complete immutable payload with authorship, timestamps and frozen source snapshots. |
| GET `/drafts/{draft_id}/events` | Read | Paginated append-only command/decision audit timeline. |

Version summaries use `limit=20` (1–50). Other lists retain `limit=50` (1–100).
All lists use `offset=0` (0–1,000,000), returning arrays in their existing order.
Command JSON bodies have a 1 MiB limit enforced before parsing, including streamed
bodies without Content-Length; larger bodies return 413.
Invalid payload/reference syntax is 422; missing story/workspace is 404.
Stale revisions, invalid transitions, conflicting command IDs, duplicate
workspaces and lock contention are 409. Infrastructure errors are sanitized 503.

### Strict JSON and safe errors — Sprint 17A.2.1

Commands accept UTF-8 `application/json`, application media types ending in `+json`,
or the existing JSON behavior with no Content-Type. UTF-8 charset parameters and
an optional UTF-8 BOM are accepted. Unsupported media types/declared charsets return
415. Invalid UTF-8, malformed JSON, nesting beyond 64 levels, escaped lone Unicode
surrogates, NaN/Infinity and exponent overflow return 400 before field validation.
Unicode is checked in every decoded string, including object keys. Valid surrogate
pairs/non-BMP text remain supported. Bodies are validated without rewriting their
bytes; successful command hashes and retry receipts are unchanged.

Private field/path/query validation errors return 422 with exactly
`{"detail":"Invalid editorial request."}`. Malformed transport/JSON errors and
unsupported media types also use fixed JSON-safe detail strings. They never echo
input values, arbitrary field names or internal exception objects. Error responses
use `Cache-Control: no-store`; CORS still applies. Existing public endpoints retain
their original validation-error contracts. Malformed requests do not create
versions, decisions or audit events, and do not change approval state.

### Version history and detail budgets — Sprint 17A.2.1

Each summary contains only `id`, `version_number`, `payload_schema_version`,
`content_hash`, `source_count`, `origin`, `actor_issuer`, `actor_subject` and
`created_at`. The query projects these columns only; it does not load version
payloads or source snapshots. Query count stays constant as the page grows.
No authorship, version identity, content hashes or timestamps are truncated or
recomputed. A page exceeding 256 KiB returns 422; request a smaller limit. This
also handles oversized legacy metadata without silently dropping history entries.

Retrieve the exact frozen content with
`GET /api/editorial/drafts/{draft_id}/versions/{version_number}`. It returns the
existing `VersionRead` shape (`payload`, sources, hashes, authorship and capture/
creation timestamps) for exactly the requested draft/version. Missing draft or
version returns 404; invalid version numbers return sanitized 422. It requires
Read permission, restricted PostgreSQL and verified identity, and uses no-store.
It cannot select another workspace's version by ID or external WordPress ID.

A complete detail has a 32 MiB response budget. PostgreSQL checks a conservative
serialized-size estimate before snapshot text is fetched into the application;
the final version representation is also checked. Oversized legacy details return
422 without truncation or history changes. The existing current-draft endpoint and
approval policy are unchanged. Source evidence still has its existing 4 MiB input
limit per created version; the larger detail budget permits JSON escaping and
metadata. New history/detail reads require no new migration or grants.

Create requires `command_id` (UUID), `expected_revision: 0`, `story_id` (persisted
UUID), `target_locale: "sr-Latn"` and a complete `payload`. One workspace per
story/locale is enforced by the existing unique constraint and a transaction-scoped
advisory lock, including requests in independent application instances. A new
workspace starts at revision 1 / version 1. A different creation command for an
existing workspace returns 409; find it with the story lookup.

Save requires `command_id`, positive integer `expected_revision` and a complete
replacement `payload`. Partial patches are rejected. An unchanged payload returns
422 and creates no history. Every successful content change appends a version and
increments the workspace revision once. Existing versions are never overwritten.

Submit/review/reopen require `command_id`, `expected_revision`, `version_number`
and `content_hash` from a fresh private read. Negative decisions/reopening also
require nonblank `reason` (maximum 2,000 characters). Version numbers are scoped
to the path's draft; a different draft's hash cannot authorize a decision.

Example payload shape (UUID placeholders must be replaced using private source lookup):

```json
{
  "headline": "Regionalni festival počinje večeras",
  "body": "Prvi pasus uredničkog teksta.\n\nDrugi pasus.",
  "excerpt": "Najvažnije informacije o festivalu.",
  "slug": "regionalni-festival",
  "categories": ["Zabava"],
  "tags": ["Festival"],
  "seo": {"title": "Regionalni festival", "description": "Proverene informacije."},
  "images": [],
  "source_attribution": [{"article_id": "ARTICLE_UUID", "source_id": "SOURCE_UUID"}]
}
```

Headline/body/excerpt/SEO/category/tag text is bounded, nonblank plain text.
Body permits paragraphs, up to 100,000 characters. HTML/control characters and
Cyrillic script are rejected; this is script validation, not automatic detection
of Serbian language or factual correctness. Slugs use lowercase ASCII letters,
digits and single hyphen separators. Categories require 1–20 unique labels; tags
allow 0–50. Images allow 0–10 objects containing `url`, `alt`, `credit` and a
`source_article_id` from the selected attribution. URLs must pass non-fetching
HTTP(S) safety validation; no image downloading or remote validation occurs.
Future rendering must escape plain text, never decode it into unsafe HTML.

Attribution contains 1–100 unique article/source UUID pairs. New selections must
belong to the persisted story and match the source UUID. External WordPress IDs
alone cannot select a source. Initial snapshots capture original/canonical URLs,
source identity/external ID, publication timestamp, exact input text, generated
hash and capture time. Prior selections copy their frozen snapshots verbatim;
new selections capture current source rows. Total input is limited to 4 MiB per
version and rejected rather than truncated. An explicit source-evidence refresh
operation is deferred; changing upstream content never silently changes evidence.

## Transitions and effective approval

| Current state | Command | New state |
| --- | --- | --- |
| editing | save / submit | editing (new version) / in_review |
| in_review | approve / request changes / reject | approved / changes_requested / rejected |
| changes_requested | save / reopen | editing |
| rejected | reopen | editing |
| approved | save changed payload | editing (new version, approval invalidated) |

Other transitions are rejected. In-review content is frozen until a decision;
rejected drafts require explicit authorized reopening. Reopening preserves content
and decisions but increments revision and records the reason. Submit validates
the complete current payload, including legacy foundation rows.

Decisions reference the exact current version/hash. State, decision and audit
event commit atomically. Effective approval requires approved head state and an
approval event for that exact current revision linked to its matching decision,
version/hash and actor. Earlier approvals do not qualify after edits, requests for
changes, rejection, reopening or resubmission. Unpaired legacy/maintenance decisions
fail closed; create a new content version before approving such evidence.
The existing DB approval trigger is a structural guard, not this authorization
policy. Future publishing must use the current private workflow state and effective
approval policy, never `EXISTS(any historical approve)` or a cached command receipt.

## Transactions, concurrency and retries

Each command uses one PostgreSQL transaction with runtime-role validation. Existing
workspaces are locked with `SELECT FOR UPDATE`, followed by an expected-revision
check. Every Core SQL head update also includes the expected revision in its
predicate and requires exactly one affected row. A stale write returns 409; state,
versions, snapshots, decisions and audit events roll back together. Lock timeout
is five seconds; per-statement timeout is fifteen seconds. No process-local lock
or in-memory receipt determines correctness.

The caller generates one command UUID per intended action. The event stores its
normalized request hash (including authenticated actor/action) and immutable result.
After authorization, an exact retry returns the **original command result**, even
when later commands have advanced the workspace. Reusing that ID with different
data, action or identity returns 409. IDs are scoped to the workspace. A repeated
creation returns 201 with the original result; other successful retries return 200.

`CommandResult` contains command/draft UUIDs and the resulting revision/state and
version/hash **at that command's revision**. It deliberately contains no effective
approval boolean. Only a fresh draft read reports effective approval. Always read
the draft again after retrying an old command; an old successful approval receipt
is never present authorization.

Audit events include the authenticated actor, action, old/new state, version,
database timestamp, command UUID and revision result; decisions add decision UUID
and reason. They and all version/source records are append-only. No secrets or
provider credentials are stored. Raw maintenance writers must use expected-revision
predicates/affected-row checks and the same atomic command protocol; the runtime
credential is never distributed to editors or external clients.

## Verification and remaining work

Tests cover lifecycle/negative transitions, role boundaries and fail-closed modes,
cross-story/source references, immutable provenance, independent-application races,
effective approval, idempotent retries, rollback, restart persistence and legacy
collection/migration/runtime-role regressions. Run the existing disposable PostgreSQL
test profile and frontend checks documented in the foundation guide.
Hardening tests additionally replay the three previously reproduced malformed-input
failures, verify zero mutations on rejection, test supported UTF-8/media formats,
and measure history/detail sizes and query counts with 50 versions backed by
multi-megabyte frozen evidence. Existing private history clients must use summaries
for navigation and the new detail endpoint for historical payloads/snapshots.

Production identity adapter, explicit evidence refresh, deployment
access controls/ingress deadlines/rate limits, retention/large-archive query tuning, AI and
WordPress Draft delivery remain separate work. Manual review remains responsible
for language quality, fact checking, attribution and image rights. Owner access
can change DDL and remains outside the application threat boundary.
