# Sprint 14A: self-hosted infrastructure preparation

This is an **unactivated infrastructure foundation**, not approval to deploy.
No remote server was inspected. AskHype's ports, proxy, identity provider, storage,
network ranges and spare resources must be confirmed by its administrator.
The existing development Compose file, Render Dockerfile, Vercel configuration and
client-preview build are independent and unchanged.

## Activation boundary — Sprint 14B blockers

The self-hosted API uses `app.selfhosted:create_selfhosted_app --factory`.
It requires production/PostgreSQL configuration, one HTTPS origin, a disabled
Vercel CORS regex and disabled AI. It **denies every application request with 503**;
only `GET /` (liveness) and `GET /ready` (infrastructure readiness) can succeed.
There is no environment switch to bypass this gate and no test identity provider.
`/ready` returning 200 does **not** mean editors can log in or use the application.
Its response explicitly says `scope=infrastructure`, `editorial_access=blocked`.

Sprint 14B must connect the frontend identity adapter and the backend's verified
identity implementation, approve server-side role mapping, protect the entire
ingress (including legacy collection/diagnostics), and only then replace the
pre-activation gate in a reviewed release. Never switch to the unguarded demo
entry point or remove access protection to make a smoke test pass. Protect both
the UI and `/api`; no database or API port may be reachable from the internet.
AI remains disabled; no GPT, Gemini activation, WordPress publishing, collection
scheduler or new infrastructure service is installed by this sprint.

## Layout and isolation

Use `docker-compose.selfhosted.yml` as a **standalone** file. Do not combine it
with `docker-compose.yml`, whose published ports would otherwise remain active.
There are no fixed container names and no published ports in the base stack.
Compose namespaces `news-api`, `news-web`, `news-db`, the application/database
networks and `news-data` volume by the unique project name. Never reuse AskHype's
project name, networks, credentials or volumes. PostgreSQL 16 has no host port
and joins only the private `internal: true` database network. The API also joins
an application bridge for future public-source access; the web container has no
database network or secrets. TLS is terminated by the administrator's confirmed
ingress; `sslmode=disable` is confined to this same-host private database network.
Reassess TLS before any database connection leaves this host.

API/tools run as UID/GID 10001 by default; web runs as the image's non-root `node`
user. Both application filesystems are read-only with bounded temporary storage,
dropped capabilities and no privilege escalation. PostgreSQL's official entry
point initializes the volume then runs the server as its own postgres user;
do not override its user or volume ownership arbitrarily.

Starting resource ceilings are DB 1 GiB/1 CPU, API 512 MiB/1 CPU and web
128 MiB/0.5 CPU, plus capped PID counts. These are configurable ceilings, not
measured requirements or reservations. Confirm host headroom with AskHype's owner,
then load-test and tune. DB has 40 connections and 128 MiB shared buffers; API has
one worker, a three-connection pool and no overflow. Recalculate budgets before
adding workers or changing PostgreSQL settings. All services rotate json-file
logs at 10 MiB × 3 files. Long-running services restart `unless-stopped`; tools
do not restart. An unhealthy status alone does not restart a running container.

## Administrator preflight and protected settings

Confirm Ubuntu/Docker/Compose versions, filesystem capacity/permissions, Docker
network overlap, backup destinations, existing ingress and identity service,
unused loopback ports and AskHype baseline health. Docker/Compose, Python 3 and
OpenSSL commands below are prerequisites, not assumed preinstalled services.
Use a separate application directory and approved release. Do not run broad
Docker prune commands or change existing host proxy/firewall rules incidentally.

Copy `deploy/selfhosted/.env.example` to a root-protected file outside the checkout,
for example `/etc/hype-world-news/production.env` (mode 0600). Set the unique
project name, reviewed release identifier, real internal HTTPS origin with no
path/trailing slash, dedicated DB names and absolute secret file paths. The
`.invalid` hostname and release placeholder are examples, never deployment values.
The frontend compiles that origin with `VITE_DEMO_MODE=false`; changing the
container environment later cannot change its API URL. The normal production
build is used, **not** `build:client-preview`. Do not set a Docker service hostname
or append `/api` to the browser API base URL.

Create two distinct cryptographically random password files, at least 24 characters,
using protected temporary files and `openssl rand -hex 32` (never display them).
Keep the secret directory root-owned, mode 0700. For the default container GID,
install each file root-owned, group 10001, mode 0440; verify this numeric GID and
adjust `HNW_APP_UID/GID` and file group if needed. Compose bind-mounted secrets
retain host permissions; its `uid/gid/mode` options cannot fix unreadable source
files. Only API receives the runtime file; only DB/tools receive the owner file.
Password values never appear in the Compose environment/configuration. The Python
loader rejects missing, empty, oversized or ambiguous environment+file secrets.
Use LF line endings. Docker administrators remain trusted and can read containers.

Changing the owner's secret file does not rotate an existing database password.
Coordinate owner rotation separately. Runtime rotation requires protected new
file contents, rerunning provisioning and restarting the API. Do not log passwords
or place them in command-line arguments, Git or `VITE_*` variables.

## Repeatable build, migration and provisioning

The commands are a future administrator procedure; this sprint does not execute
them on the server. From the reviewed checkout, define one explicit command:

```bash
hnw_compose() {
  docker compose --project-name hype-world-news \
    --env-file /etc/hype-world-news/production.env \
    -f docker-compose.selfhosted.yml "$@"
}
hnw_compose config --quiet
hnw_compose build news-api news-web
hnw_compose up -d --wait news-db
hnw_compose --profile tools run --rm news-migrate python -B -m app.selfhosted_tools migrate history
hnw_compose --profile tools run --rm news-migrate python -B -m app.selfhosted_tools migrate current
hnw_compose --profile tools run --rm news-migrate
hnw_compose --profile tools run --rm news-migrate python -B -m app.selfhosted_tools migrate check
hnw_compose --profile tools run --rm news-provision
hnw_compose up -d --wait news-api news-web
```

Use the chosen unique project name consistently, including backups and recovery.
Existing databases require a backup and review of the current revision before
upgrade. Stop the procedure on any nonzero command exit. Migrations run once per release as explicit owner tools, never from API
startup and never concurrently. The complete chain is:

`20261030_01 → 20261030_02 → 20261030_03 → 20261101_04 → 20261101_05 → 20261101_06`.

No existing revision is changed by 14A. Runtime provisioning applies existing
least-privilege policies and additionally grants **SELECT(version_num) only** on
`public.alembic_version` for readiness. It does not grant migration/DDL, DELETE,
TRUNCATE, grant options or mutable history access. The existing provisioning and
the marker grant each use transactions; rerunning completes a partially failed
procedure, while readiness remains 503 until all required grants exist. PUBLIC
grants, owning/privileged identities or delegated grants may require administrator
review; never apply CASCADE or alter shared AskHype ACLs. Re-provision after any
migration and verify again. Bootstrap credentials never run FastAPI.

## Readiness, ingress and verification

`/ready` checks connectivity, trusted runtime permissions, exact Alembic head,
all 14 managed tables/columns and required table grants, without writes or external
calls. The runtime may read only the migration marker, not change it. Missing
schema/grants, wrong revision, owner credentials and unsafe permissions fail with
generic 503; no exceptions, SQL, credentials or connection details are returned.
There are no paid/provider, source or authentication requests in readiness.

```bash
hnw_compose ps
hnw_compose exec -T news-api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/ready').read().decode())"
hnw_compose logs --tail 100 news-api news-web news-db
```

Verify API application requests return the intentional pre-activation 503 and do
not mutate data. Verify the normal frontend serves and direct routes refresh,
but authentication/editorial commands remain unavailable. Check restart persistence,
runtime UID, resource limits, rotated logs and no public DB/API socket. Configure
existing host monitoring to alert on unhealthy containers, restarts/OOM, disk and
volume growth, backup failures and AskHype degradation; no monitoring service is
installed here. After 14B, separately validate real identity, Reader/Editor/Reviewer
restrictions and the full collection/save/review workflow.

For a **host-based** proxy only, first select two free ports and set
`HNW_WEB_BIND_PORT` and `HNW_API_BIND_PORT`. Add
`-f docker-compose.selfhosted.host-proxy.yml` to the same command. Mappings bind
only 127.0.0.1, never wildcard addresses. Do not expose them in host firewall rules.
For a containerized ingress, have the administrator provide a narrowly scoped
network integration instead; do not guess or attach to AskHype's database network.

`deploy/selfhosted/nginx.conf.example` is an **optional routing example**, not an
assumption that Nginx exists. It deliberately denies all access until 14B and has
mandatory placeholders. Adapt its rules to the actual ingress: same origin,
unchanged `/api` paths (including bare `/api`), SPA frontend routes, TLS, private
readiness/docs, authorization forwarding, no command retries/caching, explicit
request/time limits and security headers. Trust only actual proxy IPs/CIDRs in
`HNW_TRUSTED_PROXY_IPS`, never `*`. Review CSP when the real identity SDK is chosen.
Validate the actual ingress configuration before reloading it. Do not install
another proxy or change shared settings without that review.

## Backup and verified recovery

Before production data is admitted, agree recovery time/data-loss objectives,
encrypted off-host storage and retention with the administrator. The named volume
is persistence, not a backup. No backup scheduler is installed by this sprint.
Example logical backup, using the same Compose command and protected host directory:

```bash
umask 077
backup_dir=/var/backups/hype-world-news
mkdir -p "$backup_dir"
backup_file="$backup_dir/$(date -u +%Y%m%dT%H%M%SZ).dump"
if hnw_compose exec -T news-db sh -c 'export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"; exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$backup_file.partial"; then
  mv "$backup_file.partial" "$backup_file"
else
  rm -f "$backup_file.partial"
  exit 1
fi
hnw_compose exec -T news-db pg_restore --list < "$backup_file"
```

Copy successful archives to administrator-managed encrypted off-host storage and
verify retrieval. Keep release image IDs/digests, configuration and role-provisioning
procedure separately; dumps do not preserve role credentials. Never copy a running
PostgreSQL data directory as an uncoordinated backup.

Restore first to a **new dedicated database**, never over the active one. Example
after confirming `hype_world_news_restore` is unused:

```bash
hnw_compose exec -T news-db sh -c 'export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"; exec createdb -U "$POSTGRES_USER" hype_world_news_restore'
hnw_compose exec -T news-db sh -c 'export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"; exec pg_restore -U "$POSTGRES_USER" -d hype_world_news_restore --exit-on-error --no-owner --no-privileges' < "$backup_file"
hnw_compose --profile tools run --rm -e POSTGRES_DB=hype_world_news_restore news-migrate python -B -m app.selfhosted_tools migrate current
hnw_compose --profile tools run --rm -e POSTGRES_DB=hype_world_news_restore news-migrate python -B -m app.selfhosted_tools migrate check
# Before provisioning, prepare /etc/hype-world-news/restore.env as described below.
docker compose --project-name hype-world-news \
  --env-file /etc/hype-world-news/restore.env -f docker-compose.selfhosted.yml \
  --profile tools run --rm -e POSTGRES_DB=hype_world_news_restore news-provision
```

Create `restore.env` from the production settings with only `HNW_DB_RUNTIME` and
`HNW_DB_RUNTIME_PASSWORD_FILE` changed to a new restore-test role and distinct
protected secret file. Keep the project, owner and database service settings
identical. Never provision using the active runtime role during rehearsal.
Check data counts, hashes,
provenance and compatible readiness against the restored DB before any approved
cutover. Do not delete the source backup or active database during rehearsal.

## Rollout, rollback and validation

First run with isolated staging settings, secrets and volume, with ingress denied.
Record images/configuration, baseline AskHype health and a successful restore test.
Reboot/restart-test persistence and verify migrations/provisioning before access
activation. Sprint 14B is a separate security gate, not an environment toggle.
Review image and dependency advisories before activation. The existing frontend
lockfile reported unresolved advisories during 14A validation (including build
tooling and React Router); this infrastructure sprint does not update dependencies.
Use `npm --prefix frontend audit` for current results and triage runtime exposure
separately from trusted build-time tooling. Never serve the Vite development server.

For rollback, stop application writes and preserve the volume and logs. Reuse the
previous approved frontend/API image pair only if compatible with the current
schema; retain the same settings/origin and image digests. Otherwise restore a
verified backup into a new database, re-provision, verify and explicitly cut over.
For a schema-compatible image rollback only:

```bash
hnw_compose stop news-web news-api
# Administrator selects the retained compatible HNW_RELEASE in the protected env file.
# Do not rebuild images or run migrations as part of this rollback.
hnw_compose up -d --no-build --wait news-api news-web
```

Do not automatically downgrade migrations: 04 removes AI data, and 05/06 can refuse
downgrades involving accepted/non-mock history. Do not run `down --volumes`, reuse
AskHype's project, or perform global Docker cleanup. No automatic rollback is installed.

Local verification, without server access:

```bash
python3 deploy/selfhosted/validate.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend backend/.venv/bin/python -B -m unittest discover -s backend/tests -v
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
git diff --check
```

The integration tests remain opt-in on an initially empty disposable PostgreSQL 16
database named `hype_news_hub_test` (`RUN_POSTGRES_TESTS=1`); never point the test
suite at this stack's persistent database or an existing service. Build and smoke
test both new Dockerfiles with disposable credentials before a server rollout.
