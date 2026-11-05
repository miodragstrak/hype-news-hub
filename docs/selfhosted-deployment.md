# Self-hosted deployment: Sprint 14A infrastructure and Sprint 14B authentication

This is infrastructure and authentication preparation, **not approval to deploy**.
No remote server was inspected. AskHype's ports, storage, network ranges and
spare resources must be confirmed by its administrator. Nginx
is confirmed, but its actual configuration has not been accessed.
The existing development Compose file, Render Dockerfile, Vercel configuration and
client-preview build are independent and unchanged.

## Application authentication — Sprint 14B

The confirmed ingress is Nginx, terminating HTTPS. P0 uses application-level
email/password authentication; it does not require VPN/SSO or an external IdP.
See [application authentication](application-authentication.md) for session, CSRF,
role, rate-limit and API contracts and the administrator bootstrap procedure.

`HNW_AUTH_ENABLED=false` retains the original application-wide 503 gate. Enabling
it installs the real PostgreSQL session verifier and requires one HTTPS origin,
explicit trusted Nginx peer IPs, migration 08, correct runtime grants and an active
initial administrator. Readiness verifies database/schema/grants and reports
`editorial_access=authenticated` when enabled, or `blocked` otherwise. It does not
prove the external Nginx/TLS configuration is correct. Never activate by switching
to the unguarded demo entry point. There are no hardcoded accounts or auth bypasses.
AI remains disabled; WordPress publishing and scheduling are not added.

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
network overlap, backup destinations, existing Nginx layout and account administration,
unused loopback ports and AskHype baseline health. Docker/Compose, Python 3 and
OpenSSL commands below are prerequisites, not assumed preinstalled services.
Use a separate application directory and approved release. Do not run broad
Docker prune commands or change existing host proxy/firewall rules incidentally.

Copy `deploy/selfhosted/.env.example` to a root-protected file outside the checkout,
for example `/etc/hype-world-news/production.env` (mode 0600). Set the unique
project name, reviewed release identifier, real internal HTTPS origin with no
path/trailing slash, dedicated DB names and absolute secret file paths. The
`.invalid` hostname and release placeholder are examples, never deployment values.
The frontend uses `build:selfhosted`, forces demo mode off and uses same-origin
relative API requests. The origin is server-side CSRF configuration, not a browser
secret. Do not use `build:client-preview` or a Docker service hostname as the API.


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
hnw_compose --profile tools run --rm news-migrate python -B -m app.selfhosted_tools bootstrap-admin
# After reviewing TLS/origin/proxy settings, set HNW_AUTH_ENABLED=true in the protected env file.
hnw_compose up -d --wait news-api news-web
```

Use the chosen unique project name consistently, including backups and recovery.
Existing databases require a backup and review of the current revision before
upgrade. Stop the procedure on any nonzero command exit. Migrations run once per release as explicit owner tools, never from API
startup and never concurrently. The complete chain is:

`20261030_01 → 20261030_02 → 20261030_03 → 20261101_04 → 20261101_05 → 20261101_06 → 20261104_07 → 20261104_08`.

No previous revision is changed by 14B. Migrations 07/08 are forward-only. Runtime provisioning applies existing
least-privilege policies plus SELECT/INSERT/UPDATE on the three auth tables,
SELECT/INSERT only on app_security_events, and additionally grants **SELECT(version_num) only** on
`public.alembic_version` for readiness. It does not grant migration/DDL, DELETE,
TRUNCATE, grant options or mutable history access. The existing provisioning and
the marker grant each use transactions; rerunning completes a partially failed
procedure, while readiness remains 503 until all required grants exist. PUBLIC
grants, owning/privileged identities or delegated grants may require administrator
review; never apply CASCADE or alter shared AskHype ACLs. Re-provision after any
migration and verify again. Bootstrap credentials never run FastAPI.

## Readiness, ingress and verification

`/ready` checks connectivity, trusted runtime permissions, exact Alembic head,
all 18 managed tables/columns and required table grants, without writes or external
calls. The runtime may read only the migration marker, not change it. Missing
schema/grants, wrong revision, owner credentials and unsafe permissions fail with
generic 503; no exceptions, SQL, credentials or connection details are returned.
No paid/provider or source requests are made in readiness. With authentication
enabled, it also requires an active administrator in the local database.

```bash
hnw_compose ps
hnw_compose exec -T news-api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/ready').read().decode())"
hnw_compose logs --tail 100 news-api news-web news-db
```

Verify disabled authentication retains the intentional 503 gate. With enabled
configuration, anonymous API requests must return 401; valid editors can read/edit
but cannot administer users or approve. Verify login, CSRF rejection, logout and
immediate deactivation/role changes using HTTPS. Check restart persistence, runtime
UID, limits and no public DB/API socket. Configure existing host monitoring for
health, OOM/restarts, disk growth, backups and AskHype degradation. Complete the
full editor → separate admin review workflow before admitting production users.

For a **host-based** proxy only, first select two free ports and set
`HNW_WEB_BIND_PORT` and `HNW_API_BIND_PORT`. Add
`-f docker-compose.selfhosted.host-proxy.yml` to the same command. Mappings bind
only 127.0.0.1, never wildcard addresses. Do not expose them in host firewall rules.
For a containerized ingress, have the administrator provide a narrowly scoped
network integration instead; do not guess or attach to AskHype's database network.

`deploy/selfhosted/nginx.conf.example` is a template for the confirmed Nginx.
It retains deny-all and mandatory placeholders until operator review. Preserve
same-origin `/api` paths, Secure cookie forwarding, exact Origin/CSRF headers,
`X-Real-IP $remote_addr`, no command retries/caching, TLS and private health/docs.
Set `HNW_TRUSTED_PROXY_IPS` to actual peer addresses seen by the container, never
`*` or a default route. Uvicorn disables proxy header processing; the auth layer
alone validates the trusted Nginx peer for login rate limiting. Remove deny-all
only after reviewed staging authentication checks, then validate Nginx before its
operator reload. No changes to Nginx itself are performed by this repository task.

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
activation. Production activation requires independent authentication review and operator
TLS/proxy checks; AUTH_ENABLED is not an authentication bypass.
Review image and dependency advisories before activation. Sprint 14D updates the affected build/runtime dependency locks; two conditional
React Router advisories remain explicitly documented in its runbook.
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

Do not automatically downgrade migrations: 07/08 are forward-only, 04 removes AI data, and 05/06 can refuse
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


See [Sprint 14D security remediation](security-remediation-14d.md) for the outer ASGI
Host boundary, isolated login budgets, migration 08 account events, locked runtime
dependencies, remaining advisory applicability and owner-operated session retention.
