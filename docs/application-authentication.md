# Sprint 14B: application authentication

This implementation targets the self-hosted newsroom only. It uses PostgreSQL
server sessions and Argon2id rather than an external identity service. No server,
Nginx installation, production account or deployment is changed by this task.
Render's normal `app.main:app` composition and the client-preview simulation remain
separate. Never use the demo entry point as the operational server.

## Activation and configuration

`HNW_AUTH_ENABLED=false` retains the Sprint 14A application-wide 503 gate. Set it
to `true` only after the following owner-controlled steps and independent review:

1. Back up the existing database and prove recovery into a separate database.
2. Build the new API/web image pair and migrate through **20261104_07**.
3. Run the existing self-hosted runtime provisioning command again.
4. Bootstrap the initial administrator interactively, once, as described below.
5. Configure the exact HTTPS origin and the actual Nginx-to-container peer IP/CIDR.
6. Verify Nginx TLS, loopback-only upstreams, overwritten `X-Real-IP`, cookies,
   CSRF, unauthorized API rejection and readiness on an isolated staging route.
7. Remove the example's deny-all only as part of the administrator's reviewed
   configuration rollout. No VPN, SSO, OAuth gateway or external IdP is required.

Compose maps these settings; passwords remain in the existing protected files:

| Host setting | Backend setting | Purpose |
|---|---|---|
| `HNW_AUTH_ENABLED` | `AUTH_ENABLED` | Default false; enables real session authentication, never a bypass. |
| `HNW_AUTH_SESSION_SECONDS` | `AUTH_SESSION_SECONDS` | Absolute lifetime, default 28800; allowed 300–86400 seconds. Reads do not extend expiry. |
| `HNW_TRUSTED_PROXY_IPS` | `AUTH_TRUSTED_PROXY_IPS` | Explicit Nginx peer IPs/CIDRs, no wildcard/default route. Mandatory when auth is enabled. |
| `HNW_PUBLIC_ORIGIN` | `BACKEND_CORS_ORIGINS` | Exact browser HTTPS origin; no path or trailing slash. Used for Origin/CSRF validation. |

Confirm the **peer seen inside FastAPI**, which may be a Docker bridge gateway
rather than 127.0.0.1. Do not guess or whitelist arbitrary private networks.
Uvicorn runs with `--no-proxy-headers`; application code uses `X-Real-IP` only from
configured trusted peers, and otherwise uses the actual socket IP and ignores all
forwarding headers. Trusted peers with a missing/invalid `X-Real-IP` cannot log in.
Nginx must overwrite `X-Real-IP` with `$remote_addr`. It must forward cookies and
the browser's Origin/CSRF headers unchanged. Do not enable proxy retries for commands.

The self-hosted frontend uses `build:selfhosted` and same-origin relative `/api`
requests with cookies. That build ignores environment-derived `VITE_*` values;
no backend credential or session token enters the bundle. The normal and
client-preview entries retain their existing build/authentication behavior.

## Initial administrator and account management

Use the protected Compose command from [the deployment runbook](selfhosted-deployment.md).
After migration and provisioning, run in a real interactive terminal:

```bash
hnw_compose --profile tools run --rm news-migrate \
  python -B -m app.selfhosted_tools bootstrap-admin
```

The CLI prompts for email and a hidden password twice. Do not append passwords,
pipe them from shell history, embed them in source or put them in environment
variables. It requires a TTY, strong 15–128-character passwords and an empty user
table; it refuses to create a replacement or reset an existing installation.
Bootstrap and HTTP account administration share a PostgreSQL advisory transaction
lock, preventing concurrent first-admin/last-admin races. Bootstrap issues no
session. Owner credentials exist only in migration/provisioning tools, never API.

Admins create users through the authenticated **Upravljanje korisnicima** panel
or the private API below. Emails are ASCII email identifiers, trimmed and
lowercased, max 254 characters, unique in PostgreSQL. Passwords are never trimmed;
Unicode passwords are supported. There is no public registration, social login,
MFA or password-reset email flow. An administrator lockout/password recovery needs
an explicitly reviewed owner procedure, not a hidden HTTP recovery endpoint.

User changes require the expected user revision. Last-active-admin deactivation
or demotion is rejected with 409 until a replacement active admin exists. User
deactivation atomically revokes their active sessions. Role changes apply on the
next request because authentication joins the current active user every time;
authorization is checked again inside admin-command transactions.

## Routes and editorial roles

| Route | Policy |
|---|---|
| `GET /`, `GET /ready` | Public, non-sensitive health; keep readiness private at Nginx. |
| `POST /api/auth/login` | Public credential verification, exact Origin required, distributed rate limit. |
| `GET /api/auth/session` | Valid cookie required; returns account fields and CSRF proof only. |
| `POST /api/auth/logout` | Origin and valid-session CSRF required; revokes session and expires cookie. An already expired/missing session can be cleared idempotently. |
| `GET /api/admin/users?limit=20&offset=0` | Current admin only; max page 50. |
| `POST /api/admin/users` | Current admin + CSRF; `{email,password,role}`. |
| `PATCH /api/admin/users/{uuid}` | Current admin + CSRF; `{expected_revision,role,active}`. |
| All other API, discovery, collection, story, queue, draft, history, AI and review routes | Valid active session first, then existing editorial permissions where applicable. Unknown paths and docs are also protected. |
| Legacy `generate-demo-draft` | Explicitly disabled with 403 in the operational server. |

There is no anonymous API fallback and no Bearer/header role override in the
cookie composition. The default/demo app keeps its original Bearer contracts;
the self-hosted OpenAPI describes cookie authentication. Responses never include
password hashes, session hashes or raw session secrets. Malformed auth/admin
requests return sanitized 4xx, never reflected password fields or exceptions.

P0 `editor` maps to the existing **Editor** (read, edit, submit); it does **not**
receive Reviewer permissions. P0 `admin` maps to the existing **Administrator**,
including review and administration. An editor authors/submits and a separate admin
can review/approve. Immutable versions, exact-version/hash decisions and approval
invalidation are unchanged. A non-administrative reviewer cannot be represented
by this two-role P0 model: the smallest future extension is a third account role
mapped to existing Reviewer permissions. Do not grant review to all editors.
The pre-existing Administrator role has all editorial permissions; this sprint
does not add a new prohibition on administrator-authored self-review. Use separate
author/reviewer accounts operationally; a stronger two-person rule requires an
explicit editorial-policy change. WordPress delivery is still not implemented.

## Session and CSRF controls

Every login creates a fresh 256-bit random opaque token. Only its SHA-256 hash is
stored. `__Host-hwn_session` is host-only, Path=/, Secure, HttpOnly, SameSite=Lax.
No session token is available to JavaScript, localStorage or sessionStorage.
Logout uses matching cookie attributes to delete it and records server revocation.
Password hashes use Argon2id (19 MiB, 2 iterations, parallelism 1) with random salts;
expensive hashes are limited to two simultaneous operations per process.

The session bootstrap returns an HMAC-derived CSRF proof bound to the opaque
cookie secret. JavaScript keeps only that proof and account data in memory. All
state-changing requests require it and an exact trusted Origin. The legacy GET
`/api/collect` also requires the proof; browser GET may omit Origin, but cross-site
Fetch Metadata or a mismatching Origin is rejected. SameSite alone is not the
CSRF control. Login itself requires exact Origin to prevent login CSRF.

Rate limits are PostgreSQL-backed and shared across processes: 5 attempts per
account bucket, 10 per IP bucket and 30 globally per 60 seconds, including successful
attempts. Stored buckets are SHA-256-sharded into a fixed space of at most 8193
rows, retaining no raw attempted email/IP. Collisions deliberately fail stricter;
busy shared offices may need a separately reviewed limit change. Unknown, inactive
and wrong-password attempts return the same generic 401; dummy Argon2 verification
reduces timing differences. Rate-limited replies are generic 429/Retry-After:60.

Identity changes/logout unmount private React state and invalidate pending results.
The existing session-generation guards also protect cookie-mode CSRF acquisition.
Bootstrap refreshes on focus/visibility and every 60 seconds; server authorization
is checked on every request, not just at refresh. A 403 refreshes current account
state without resubmitting the command. Network-uncertain logout hides private
content and offers an explicit retry; it cannot claim server revocation until a
response confirms it. Reload after an unconfirmed network logout may still find
the unrevoked cookie: complete logout before leaving an unattended device.

## Database and operations

Revision `20261104_07` follows `20261101_06`; previous migration files are unchanged.
It adds `public.app_users`, `public.app_sessions` and a third bounded throttle
table. A third table is necessary for reliable cross-process rate limits without
adding Redis or another service. Authentication has separate trusted-schema ORM
metadata; editorial collection history is not rewritten or given user-delete FKs.
Runtime gets SELECT/INSERT/UPDATE only on these three tables, in addition to the
existing immutable-history allowlists and readiness marker read. It cannot DELETE,
TRUNCATE, perform DDL or delegate privileges. Existing legacy provisioning defaults
remain unchanged; use the self-hosted provisioner for the combined auth policy.

Readiness verifies all 17 tables, exact head, effective runtime privileges and an
active initial admin when auth is enabled. It reveals no DB/credential details.
There is no background cleanup or scheduler. Sessions remain hashed/revoked for
operator-reviewed retention; expired-session cleanup is a future owner-maintenance
procedure. User rows are deactivated, not deleted, preserving audit identities.

Migration 07 is **forward-only** and refuses all downgrades. Back up before upgrade;
roll back via compatible images or a separately restored pre-upgrade database.
Do not stamp or manually drop production auth tables. Legacy migration tests pin
reversible revisions 01–06. Auth tests explicitly upgrade populated 06 and use only
initially-empty `hype_news_hub_test`; their DROP/stamp cleanup is test-only and not
a supported production rollback.

Before deployment: independent security review; current dependency advisory triage;
operator secrets, TLS/origin/proxy-IP checks; tested backups/restores and monitoring.
No production accounts, passwords, Nginx changes or deployment are provided here.
