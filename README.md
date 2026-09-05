# Edufurther Scholarship Finder Backend

Backend foundation for the standalone Edufurther Scholarship Finder. The service
helps international graduate students discover verified scholarship opportunities.

## Quick start

Requirements: Python 3.14+, `uv`, and Docker Desktop for local PostgreSQL.

```powershell
uv sync --group dev
docker compose up -d postgres
uv run alembic upgrade head
uv run fastapi dev
```

The API is available at `http://127.0.0.1:8000`. From the repository root,
`uv run fastapi dev` discovers the configured `app.main:app` entrypoint automatically.

## API surface

- `GET /health` — liveness check
- `GET /ready` — database readiness check; also reports schema drift (see below)
- `GET /api/v1/taxonomies` — supported search taxonomy
- `POST /api/v1/search` — search published scholarships
- `GET /api/v1/scholarships/{id-or-slug}` — scholarship details
- `POST /api/v1/internal/jobs` — stable QStash job callback

Search only reads published, approved data. Crawling, source processing, and review
are asynchronous workflows; no LLM is called synchronously by the search endpoint.

## Feed import

`POST /internal/import/feed` accepts the Sheet's five known columns per row: `url`
(Link), `title` (Title), `excerpt` (Description), `source_posted_at` (Source Posted
Date) and `feed_created_at` (Created Date). The two dates are discovery/publication
signals only — never application deadlines — and are carried through unchanged.

Every call opens one `CrawlRun` and every row lands in exactly one bucket:

- **imported** — a URL never seen before.
- **repeated** — an already known URL and unchanged content; only the page's
  `last_seen_at` moves.
- **changed** — an already known URL whose content moved. A new `Discovery`
  revision is created with `supersedes_discovery_id` pointing at the one it
  replaces; the earlier row is never deleted or overwritten, so a decision made
  from it stays explainable.
- **rejected** — could not become a `Discovery` at all (an unparsable URL, or a
  source id that does not resolve to an active `Source`). Preserved in
  `DiscoveryQuarantine` rather than dropped, so "quarantine unparsable rows"
  means the raw row survives, not just that it was counted.

The response carries the run's `crawl_run_id` alongside the four counts, and every
`ProcessingJob` the import enqueues records that id as its `correlation_id`.

Every new or changed row enqueues both a `normalize_discovery` job and a
`link_canonical` job. The second one matters as much as it sounds trivial:
without it nothing would ever call `link_discovery` for a freshly imported row,
which would sit at `processing_state=normalized` forever, invisible to any
reviewer, no matter how many rows import successfully.

`link_canonical` resolves a discovery to `linked` (exactly one existing
scholarship shares its name), `needs_review` (more than one candidate — an
ambiguity a reviewer must resolve before anything auto-links), or
`new_candidate` (no existing match). Against a young or empty catalogue,
`new_candidate` is the overwhelming majority outcome, and it opens a
`ReviewTask` exactly like `needs_review` does — a brand-new identity is still a
decision only a reviewer can make.

Before importing, a `Source` must exist: `POST /internal/admin/sources` (`name`,
`source_type`, an A–D `authority_grade`, `approved_domains`, `active`); `GET
/internal/admin/sources` lists what is registered.

Before approving anything, a `Provider` must exist too - the organization
responsible for an award, distinct from the sources that report on it:
`POST`/`GET /internal/admin/providers` (`name`, `approved_domains`).
`decide_review`'s approve path takes a `provider_id`.

### Bulk import from a CSV export

```powershell
uv run python scripts/import_feed_csv.py export.csv --source-id <uuid> `
  --base-url https://your-staging-url --token $env:INTERNAL_SERVICE_TOKEN
```

Every row is validated locally against the same contract the API enforces before
anything is sent. This matters specifically because the import endpoint validates
up to 500 records as one request: a single row with a blank Link or a non-http(s)
URL would otherwise reject the *entire* batch, not just that row. Rows failing
local validation are reported and skipped; only the survivors are sent, in batches
under the API's own 500-row cap. Add `--dry-run` to validate a file — useful for a
first pass over a new export — without sending anything.

## Review and publication

A record becomes public in two separate reviewer actions, matching the design's
`APPROVED -> PUBLISHED` state machine:

- `POST /internal/admin/reviews/{id}/decision` (`decision: approve`) creates the
  `Scholarship`, still at `lifecycle_state=needs_review` — this is linking a
  canonical identity, not publishing it.
- `POST /internal/admin/scholarships/{id}/publish` creates one `ScholarshipCycle`
  with the cycle's facts (destinations, levels, origin/field eligibility, funding
  evidence, deadline) and flips `lifecycle_state` to `published`. Destinations are
  validated against verified coverage, the same vocabulary search itself uses;
  levels and fields against the taxonomy. A scholarship may receive further
  cycles once published — a new intake is not a reason to unpublish the last one
  — but a withdrawn scholarship refuses new cycles until explicitly reactivated.

Evidence behind a published fact is asserted by the reviewer in the publish
request (`evidence_fresh`) rather than independently recorded per claim today.
Formal per-claim `verifications`/`verification_evidence` linkage, which the data
standard's 100%-evidence-compliance gate ultimately needs, is deferred.

### Deadlines never get an invented time of day

The data standard requires storing date, time, timezone and precision
separately, and never manufacturing midnight or a countdown from an unknown
timezone. `PublishCycleRequest.deadline_precision` (`"date"` by default, or
`"datetime"`) and `deadline_timezone` (an IANA zone, if the provider's is known)
travel with `deadline_at` into the cycle's `facts`.

For a `"date"` deadline, `evaluate_public_status` derives the actual cutoff
instant rather than comparing a bare midnight: with a known timezone, that
zone's own end of day; with an unknown one, the earliest place on Earth
(UTC+14) that calendar date ends - the conservative choice, since the failure
this prevents is claiming "Open now" past a deadline that has, somewhere,
already passed, not an early downgrade. A cycle published before this existed
has neither key in its stored facts and is read back as `"datetime"` (a literal
comparison, its original behaviour), so nothing already published silently
changes meaning.

`zoneinfo` has no bundled IANA database on Windows or in the `python:3.14-slim`
deployment image - the `tzdata` PyPI package is a required dependency for
exactly this reason. Without it, every known timezone silently resolves as if
it were unknown, with no error at all.

### Every job import creates is published to QStash

`import_feed_records` writes each `normalize_discovery`/`link_canonical`
`ProcessingJob` row, and once the batch's transaction has actually committed,
publishes a matching QStash message for it (`QStashPublisher`, keyed by the same
`dedupe_key` as both the app-level and QStash's own deduplication). QStash then
delivers it back to `/internal/jobs`, which executes it inline. Publishing only
ever happens after the commit succeeds: publishing first would risk QStash
delivering a callback for a `ProcessingJob` - and the `Discovery` its payload
references - that a rollback made never exist.

This is best-effort per job. If `QSTASH_TOKEN`/`QSTASH_EXPECTED_DESTINATION`
are not configured (local dev, tests), or QStash is briefly unreachable,
publishing is skipped or logged (`qstash_dispatch_failed`) rather than failing
the import - the local `ProcessingJob` row already exists either way.

`POST /internal/admin/jobs/run-due` (optional `?limit=`, default 200, max 1000)
remains the manual recovery path: it executes every job currently due -
queued, or `retry_wait` past its backoff - and reports `{completed, failed,
remaining}`. Safe to call repeatedly. This is what closed the gap that left
247 real discoveries with an empty review queue on staging before jobs were
published to QStash on creation at all - their rows existed, but nothing had
ever triggered execution for them.

## Configuration

Copy `.env.example` to `.env` for local configuration. The database URL must use the
SQLAlchemy asyncpg format:

```text
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/database
```

For staging and production, set secrets in the deployment platform rather than in
the repository. Core join intent and Sentry are optional integrations and may remain
unset until those integrations are activated.

### QStash

QStash is regional. Set `QSTASH_URL` to the region where the account was created and
use signing keys from that same region. For a US account, use:

```text
QSTASH_URL=https://qstash-us-east-1.upstash.io
```

Publish jobs to the stable callback URL:

```text
POST https://api.example.com/api/v1/internal/jobs
```

Put the job `kind` in the signed JSON body and set
`QSTASH_EXPECTED_DESTINATION` to the complete callback URL, not just the API base
URL. The older `/internal/jobs/{kind}` route remains for compatibility and expects
that same URL with the kind appended.

The job runs synchronously inside this request, before responding: a freshly
enqueued delivery is executed immediately, and the response's `state` reflects
the real outcome (`completed`, `retry_wait`, `failed_review`) rather than
`queued`. A replayed delivery for a `dedupe_key` that already has a job reports
that job's current state without re-running it. Acknowledge success only after
durable completion — enqueuing and returning 200 before anything ran would mean
every delivered job sat at `queued` forever, since nothing else calls
`execute_job`.

There is deliberately no periodic sweep yet that revisits a job sitting in
`retry_wait` past its `next_attempt_at` — that requires the recurring QStash
schedule manifest, which remains deferred (see the release checklist). A
transient failure on first delivery is recorded durably and visible, but is
not automatically retried until that scheduler exists.

`QSTASH_EXPECTED_DESTINATION` is required for any deployment behind a platform
proxy. QStash signs the public `https://` URL it was given, while the app is
reached over plain HTTP from a private address, so the request URL the app
reconstructs never matches the signature and every job is rejected with 401. Only
local runs that QStash reaches directly may leave it unset.

### Parse.bot harvest (ScholarshipPortal, PhDScanner)

`harvest_parsebot` is a recurring job that pulls candidates from two
Parse.bot-wrapped marketplace APIs — ScholarshipPortal (all five supported
destinations, both degree levels) and PhDScanner (funded PhD opportunities;
covers `GB`/`DE`/`FI` well, returns nothing for `CA`/`US`) — and feeds them
through the exact same `import_feed_records` pipeline as the CSV feed import,
so every result lands as an ordinary `Discovery` needing the same review
before publish. Set `PARSE_API_KEY` in the deployment platform; the SDK
(`parse_apis/`, generated by `uv run parse sync` and committed rather than
gitignored, since Railway builds from a git checkout with no network access
to Parse.bot at build time) reads it directly from the process environment.

Two independent, deliberately separate kill switches:

- **App-level (immediate, no redeploy):** `ScholarshipPortal (via Parse.bot)`
  and `PhDScanner (via Parse.bot)` are ordinary `Source` rows. Deactivating
  either (`POST /internal/admin/sources/{id}/deactivate`, or
  `scripts/manage_parsebot_sources.py deactivate --which ...`) stops that
  API's harvest on its very next run — `_harvest_parsebot` checks
  `Source.active` before making any network call, so a paused source spends
  zero Parse.bot credits, not just discards the result.
- **Schedule-level (hard stop):** `scripts/manage_parsebot_schedule.py pause`
  tells QStash to stop calling the app at all, independent of anything the
  app itself does. `create`/`status`/`resume`/`delete` are the other
  subcommands; a fresh schedule defaults to every Monday 06:00 UTC.

**Current deployment (development/staging, `edufurthersf-be-dev`):** a
schedule is live, `scheduleId=scd_551udc3u5Kp6ATYPqvDUVESYasDa`, created
2026-09-05. `status` doesn't need the ID (it lists every schedule on the
account); `pause`/`resume`/`delete` do. Ready-to-run, no placeholders to
fill in:

```powershell
railway run -s edufurthersf-be -e development -- `
  uv run python scripts/manage_parsebot_schedule.py status

railway run -s edufurthersf-be -e development -- `
  uv run python scripts/manage_parsebot_schedule.py pause `
  --schedule-id scd_551udc3u5Kp6ATYPqvDUVESYasDa

railway run -s edufurthersf-be -e development -- `
  uv run python scripts/manage_parsebot_schedule.py resume `
  --schedule-id scd_551udc3u5Kp6ATYPqvDUVESYasDa
```

If the schedule is ever deleted and recreated, `create` returns a new
`scheduleId` - update it here, since a stale ID in this doc would send
someone to pause a schedule that no longer exists while the real one keeps
running.

A QStash *schedule* redelivers one static request body on every firing.
`ProcessingJob.dedupe_key` is permanently unique, so naively reusing that
static body's key would let only the first-ever delivery actually run —
every later delivery would just report that first job's now-stale result
forever. `harvest_parsebot` is listed in `RECURRING_WEEKLY_KINDS`
(`app/api/routes.py`), which recomputes an ISO-week-scoped dedupe key
server-side instead of trusting the delivered payload: same-week retries
still dedupe correctly, but next week is a genuinely fresh run.

Both ScholarshipPortal and PhDScanner are unofficial, independently
maintained wrappers over public site data — Parse.bot's own listings say so
explicitly — so both `Source` rows carry `authority_grade="C"`, the same tier
as ScholarshipRegion: useful for discovery breadth, never evidence on their
own.

### Rate limiting

The anonymous search limiter is process-local and keys on the client IP, which the
deployment image resolves by trusting `X-Forwarded-For` only from the platform
proxy's own network (`FORWARDED_ALLOW_IPS=100.64.0.0/10`). It must not key on the
session cookie: an anonymous caller chooses that value and could mint a fresh
bucket per request. Suitable for local development or a single API instance;
before running multiple instances, use a platform-level limiter or a shared store. Before running multiple instances, use a
Railway/platform-level limiter or replace it with a shared-store implementation.

## Taxonomy and Core alignment

Degree codes are ISCED-aligned to match Core's `degree_levels` slugs
(`masters`, `doctorate`). A join intent forwards `program_level` to Core, which
cannot resolve a code it does not hold, so the Finder accepts `phd` as an input
alias and normalises it to `doctorate`. The user-facing label stays "PhD".

Countries are mirrored from Core's unauthenticated
`GET /api/v1/catalog/countries` into the local `countries` table by the
`sync_countries` job. The mirror is never read through Core at request time:
search has to keep answering while Core is down. Set `CORE_BASE_URL` to enable
the sync; until it runs, a small built-in seed stands in.

Origin and destination are separate lists. Origin accepts any country Core
publishes — restricting it to the countries the index covers would turn "we
have nothing for you yet" into "you do not exist". Destination is limited to
`is_supported_destination`, a Finder-owned column recording verified coverage
that the sync deliberately never overwrites.

Degree levels are **not** mirrored. Core's vocabulary is four closed rows that
users cannot add to, and the Finder deliberately offers two of them, so a
runtime fetch would import levels the product must not offer and put a network
call in front of four constants. The codes stay local and
`tests/test_core_contract.py` pins the agreement instead, failing in CI rather
than at a handoff.

Core has no field-of-study catalogue — programme names there are free text by
design — so the field taxonomy is Finder-owned, built on ISCED-F 2013
(UNESCO's field-of-education classification) at two tiers:

- **Broad** (11 codes, e.g. `ict`, `health_and_welfare`) — what `GET
  /api/v1/taxonomies` offers a search form under `fields`, and what
  `SearchRequest.field` accepts. Matches what a real searcher thinks in.
- **Narrow** (29 codes, e.g. `ict`, `health`, `welfare`, `law`) — what a
  scholarship is actually tagged with at publish time (`PublishCycleRequest.
  fields`), exposed for reference under `GET /api/v1/taxonomies`'
  `narrow_fields`. A search's broad choice is expanded to every narrow code
  beneath it (`Taxonomy.narrow_fields_under`) before matching against a
  scholarship's own narrow tags — see `domain/taxonomy.py` and
  `domain/matching.py`.

## Tests

The suite includes integration tests that run against a real PostgreSQL database,
because the defects that reach production are the ones pure functions cannot show:
a column type the ORM and the migration disagree on, or a request that never
commits. Start a disposable database and point `TEST_DATABASE_URL` at it:

```powershell
docker run -d --name finder-test -e POSTGRES_DB=scholarship_finder_test `
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -p 55433:5432 postgres:16-alpine
$env:DATABASE_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:55433/scholarship_finder_test"
uv run alembic upgrade head
uv run python scripts/check.py
```

`scripts/check.py` enforces an 85% branch-coverage floor. `SKIP_DB_TESTS=1` skips
the database tests and prints a warning; a run with them skipped is not a full
pass and does not clear a release gate.

## Database migrations

Local migration validation uses:

```powershell
uv run alembic upgrade head
```

Staging and production migrations are applied explicitly through the manually
triggered `Database migrations` GitHub Actions workflow. Configure `DATABASE_URL` as
a secret in the corresponding GitHub Environment and require approval for production.

The API container does not run migrations automatically at startup — deliberately;
this stays a human-triggered, reviewable action rather than something a deploy or a
QStash job can set off unattended. **The habit that keeps it from going stale: run
the workflow for every environment whenever a PR that adds a file under
`migrations/versions/` merges to `main`**, before relying on anything that depends on
it. Staging went several sessions behind head here before a job crashed on a column
that had not been added yet.

`GET /ready` makes drift visible without needing database access of your own: it
reports `migration.applied` (the revision found in that database's own
`alembic_version` table), `migration.expected` (this deployed code's own migration
head, computed from `migrations/` rather than hand-maintained), and
`migration.up_to_date`. A mismatch never turns `/ready` itself unhealthy — a database
that answers is still ready to serve, and restarting the process fixes nothing a
migration didn't already apply — but it is logged as `schema_migration_drift` and
visible on the next request to anyone checking the URL.

## Quality checks

Run the complete local quality gate:

```powershell
uv run python scripts/check.py
```

This runs compilation, tests, Ruff, mypy, Bandit, and pip-audit when those tools are
installed. The staging smoke test is separate because it requires a running service:

```powershell
$env:SMOKE_BASE_URL = "http://127.0.0.1:8000"
uv run python scripts/smoke.py
```

GitHub Actions runs the quality gate and Gitleaks on pushes and pull requests.

## Project documentation

The evidence-driven Phase 0 release checklist is available at
[`docs/phase0-release-checklist.md`](docs/phase0-release-checklist.md).
