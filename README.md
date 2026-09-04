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
design — so the field taxonomy is Finder-owned.

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
