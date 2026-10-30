# Source connector reliability and security (Sprint 15C)

## Source policy

The source registry is `backend/app/config/sources.py`. Collection, discovery
and diagnostics instantiate its connector factories. The configured sources and
original source attribution/WordPress post IDs are retained.

| Source | WordPress request policy |
| --- | --- |
| `https://hypetv.rs` | `/wp-json/wp/v2/posts?_embed=wp:featuredmedia,wp:term&per_page=N` |
| `https://hypetv.hr` | Existing full `_embed` policy |
| `https://hypebih.ba` | Existing full `_embed` policy |
| `https://hypetv.si` | Existing full `_embed` policy |
| `https://hypetv.mk` | Existing full `_embed` policy |
| `https://www.hypeproduction.rs` | Existing full `_embed` policy; empty is valid |

Serbia's full embedding timed out in the source diagnostics. Selective embedding
retains featured images, category/language terms and full content using the same
article parser, without the unrelated embedded resources. It does not change
article identity rules or persistent story membership.

Hype Production's public posts API returns HTTP 200 with `[]` and zero total
posts. This is an upstream empty news resource. Its corporate WordPress pages
are not news and are never collected. The website operators must identify an
authoritative news endpoint/feed or publish news posts before collection can
yield articles. No RSS or HTML collection fallback is implemented. Discovery
still probes known RSS paths and retains the legacy `html_scraping` hint; that
hint does not execute a scraper or change collection behavior.

## Outcomes and compatibility

Public route names, query parameters, response shapes and OpenAPI schemas are
unchanged. The intentional security restriction is that `/api/test-wordpress`,
`/api/fetch-wordpress` and `/api/test-wordpress-normalized` accept only a
configured HTTPS origin (optional root slash and port 443). Other hosts,
arbitrary paths/query strings, userinfo, fragments and unsupported ports return
HTTP 403 before any outbound request. Configured sources resolving to a
non-public destination or redirecting outside their policy also fail safely.
No new authentication requirement or deployment setting is needed.

The normalized diagnostics now test the posts resource directly, avoiding an
unnecessary API-index preflight. `/api/test-wordpress` retains its existing
connection-probe and `{status, posts_found, connector, error?}` behavior.
Its connection probe must succeed before its ten-post check. Normalized routes
return HTTP 502 for classified upstream failures, with safe error text.

`normalize_source_batch` is shared by memory/PostgreSQL collection and diagnostics:

| Outcome | Collection result |
| --- | --- |
| HTTP 200, JSON `[]` | `status=success`, `articles_total=0`, `error=null`; INFO log `upstream_empty` |
| Some usable, some filtered entries | Success with the accepted count; WARNING log `normalization_filtered` with fetched/accepted counts |
| Nonempty entries, none usable | Failed source, `normalization_filtered` error; never reported as upstream-empty |
| HTML or invalid JSON | Failed source, `invalid_json` |
| Unexpected JSON/embedding structure | Failed source, `malformed_structure` |
| HTTP 403/429/5xx (or other non-200 status) | Failed source, `http_rejected` with numeric status |
| Deadline/connect/read timeout | Failed source, `timeout` |
| DNS/network failure | Failed source, `dns_error` / `network_error` |
| Blocked destination | Failed source, `unsafe_destination` |
| Oversized response / redirect limit / unsolicited compression | Failed source, `response_too_large` / `redirect_limit` / `unsupported_encoding` |

Codes prefix the existing nullable `error` string; no outcome field was added.
PostgreSQL persists failures in its existing per-source results. Distinguishing
partial filtering from a completely clean batch uses logs, not a new API field.
Source failures remain isolated. Existing memory replacement/retention behavior
and PostgreSQL complete retained story snapshots are unchanged. Memory remains
the default; PostgreSQL remains opt-in. There are no new schema migrations.

## Outbound security boundary

`SourceHTTPClient` uses the shared, direct HTTPS transport for WordPress and RSS
diagnostics. It enforces:

- Exact configured hostname, HTTPS, port 443 and no URL userinfo. Each redirect
  is checked manually; only same-host redirects are currently configured, with
  at most three hops. A future canonical host change needs explicit review.
- Every resolved A/AAAA address must be public before any socket is opened.
  Loopback, private, link-local/metadata, shared, multicast, reserved and
  IPv4-translation/tunneling destinations are rejected. DNS aliases receive the
  same checks on their resolved addresses.
- Connection to the validated numeric IP, with actual peer verification before
  HTTP/TLS. A second DNS lookup cannot substitute an internal address. Each new
  connection revalidates DNS, including redirect hops. TLS retains the original
  hostname/SNI and certificate verification. Public DNS alone is not trusted.
- No environment proxy routing (`trust_env=False`); no TLS-verification bypass.
- Explicit connect/read timeouts, one overall deadline across all hops, bounded
  streamed response reads, and an early Content-Length limit. Requests ask for
  identity encoding; unsolicited compression is rejected without decoding to
  avoid decompression bombs. HTTP rejection bodies are never exposed.
- Safe constant error messages. Response bodies, resolved IPs, connection
  exceptions and credentials are not returned to API callers.

This uses the public HTTPX transport and HTTPcore network-backend interfaces.
`httpcore==1.0.9` is now an explicit dependency alongside `httpx==0.28.1`.
Run the transport regressions when upgrading either library.

## Content safety

Article/media URLs must be absolute HTTP(S) URLs without userinfo or unsupported
ports; invalid article links are filtered and unsafe media links become null.
Obvious localhost/non-public literal IP URLs are rejected. Content links are not
fetched or DNS-resolved by the backend. Historical PostgreSQL reads also validate
article/media URLs before returning them.

WordPress rendered fields are extracted as plain text, excluding script/style
and other inactive container contents. The original upstream payload remains in
`raw` for attribution/debugging and is untrusted. React currently renders text
through JSX and does not use `dangerouslySetInnerHTML`. Plain-text extraction is
not an HTML sanitizer: future rich rendering must use a suitable sanitizer.
RSS diagnostic parsing rejects DTD/entity declarations and uses bounded input.

## Settings and verification

Defaults work without changing Render or Vercel settings. Native backend
overrides are documented in `backend/.env.example`:

| Setting | Default |
| --- | --- |
| `SOURCE_HTTP_CONNECT_TIMEOUT_SECONDS` | 5 |
| `SOURCE_HTTP_READ_TIMEOUT_SECONDS` | 10 |
| `SOURCE_HTTP_REQUEST_DEADLINE_SECONDS` | 20 |
| `SOURCE_HTTP_MAX_RESPONSE_BYTES` | 5242880 (5 MiB; configurable 1 KiB–32 MiB) |
| `SOURCE_HTTP_MAX_REDIRECTS` | 3 (configurable 0–5) |

Time limits must be positive and finite. `DISCOVERY_TIMEOUT_SECONDS` is accepted
as a legacy environment setting; discovery now uses the shared `SOURCE_HTTP_*`
limits. Bounds apply to each outbound GET, including its redirects, not the whole
multi-source discovery/collection operation. Docker environment overrides can be
passed explicitly with `docker compose run -e SOURCE_HTTP_...=...`; Compose and
deployment definitions are unchanged.

```bash
# Backend unit/API/transport regressions (PostgreSQL tests skip without opt-in):
cd backend
python -B -m unittest discover -s tests -v

# From repository root, with protected local test credentials prepared per
# docs/postgresql.md; this uses only the disposable test service:
docker compose --profile test run --rm --build database-tests

cd frontend
npm test
npm run typecheck
npm run build
```

Tests use deterministic transports, DNS resolvers and network streams, including
the real HTTPcore connection path with numeric IP and TLS hostname assertions.
PostgreSQL integration tests exercise the real connector over a mock HTTP
transport, identity-preserving recollection, retained feeds after failures and
safe historical media reads. They use the existing restricted runtime role.

## Remaining limitations

- No automatic retries, `Retry-After` scheduler, authentication or rate limiting
  is introduced. Existing publicly callable collection/diagnostic operations
  still need deployment access controls as part of the authentication work.
- New redirect hosts and nonstandard encodings fail closed. Source operators
  must preserve public HTTPS endpoints or coordinate explicit policy changes.
- The response cap may reject large embedded batches; reduce the batch size or
  review the bound, without disabling it. Only the existing latest-post batch
  is fetched; pagination/backfill is outside this sprint.
- Persisted story/archive reads remain unpaginated; archive growth remains work
  for the subsequent performance sprint. Collection locking/transactions and
  migration revisions are unchanged.
