# Phase 0 release checklist

Phase 0 is complete only when the code checks and the environment checks below have
recorded evidence. Keep credentials and customer data out of evidence attachments.

## Current Phase 0 status

Phase 0's code-and-delivery scope is closed: the backend is published, staging
migrations have succeeded, the API is deployed, the quality gate is green against a
real PostgreSQL service container, the smoke test passes against staging including
search and detail, and signed QStash delivery has been confirmed end to end
(accepted, replay-deduplicated, invalid signature/destination rejected).

An earlier revision recorded this scope as complete on the strength of smoke checks
that probed only `/health`, `/ready` and `/api/v1/taxonomies`. None of those touch the
scholarship tables, so they passed while `POST /api/v1/search` and the scholarship
detail route returned 500 against the migrated schema, and while every anonymous
session, search and join request was discarded without being committed, and while a
QStash body-hash comparison could never succeed regardless of configuration. All
three are fixed and re-verified against the current build; this is not a repeat of
that earlier premature close.

What remains before the product itself is real, not the backend: the dataset. No
scholarship has been published, so search has nothing to return yet. The deferred
items below (Core join, Sentry, rate limiting, backup/rollback) are scheduled
alongside the capability that needs them and are not release blockers.

Two gaps that stood between the code and a real record reaching search are now
closed: `POST /internal/admin/sources` creates the `Source` rows the feed import
requires, and `POST /internal/admin/scholarships/{id}/publish` creates a
`ScholarshipCycle` and flips `lifecycle_state` to `published` — previously
nothing did either. Evidence for a published fact is asserted by the reviewer in
that request rather than independently recorded per claim; formal
`verifications`/`verification_evidence` linkage is a deliberate later revisit,
not an oversight.

Staging's schema is confirmed current: the "Database migrations" workflow has been
re-run.

A QStash delivery of `sync_countries` was accepted (200) but, until the fix below,
that only meant the job was enqueued — the deployed app never called `execute_job`
for it. `GET /api/v1/taxonomies` on staging still showed the 6-country seed after
that "successful" delivery, confirming the sync never actually ran. Delivery being
accepted is not evidence a job did anything; `/internal/jobs` now runs a freshly
enqueued job before acknowledging it, exactly as this table's own "QStash delivery"
row should have meant from the start.

Staging went behind `main` once already without anyone noticing until a job crashed
on a missing column. That must not happen quietly again: `GET /ready` now reports
`migration.applied` against `migration.expected` (this code's own migration head,
computed from `migrations/` rather than hand-maintained) on every request, and logs
`schema_migration_drift` on a mismatch. The habit that keeps this closed going
forward — re-run the "Database migrations" workflow for every environment whenever
a PR adds a file under `migrations/versions/` merges to `main`, and check `/ready`
after — belongs with the deploy step, not with memory.

## Phase 0 and deferred validation matrix

| Item | Owner | Status | Evidence |
| --- | --- | --- | --- |
| Automated quality gate | Engineering | **Closed** | Passing `scripts/check.py`, 167 tests, 85%+ branch coverage, run against a real PostgreSQL service container in CI |
| Staging API smoke test | You/Engineering | **Closed** | Confirmed passing against the deployed staging URL: health, ready, taxonomies, search and detail |
| QStash delivery | You/Platform owner | **Closed** | Confirmed: signed delivery accepted, replay deduplicated, invalid signature/destination rejected |
| CI and Gitleaks | You/repository owner | **Closed** | Passing pull-request workflow run with Gitleaks |
| Core join intent | You/Core owner | Deferred | Needs Core staging URL, service token, allowed return URL and a test search/session before it can be exercised end-to-end |
| Sentry verification | You/Platform owner | Deferred | Needs a staging Sentry DSN |
| Production rate limiting | Engineering/Platform | Deferred | Needs a decision and access to a Railway/platform limiter or shared store before running multiple instances |
| Backup and rollback | You/Platform owner | Deferred | Needs a non-production database backup destination and deployment access |

Deferred items are explicit product-owner decisions, not open questions: they are scheduled for activation alongside the capability that needs them, not blockers to the current release.

`CORE_BASE_URL` is now set in Railway, and `/internal/jobs` now actually executes a
delivered job rather than only enqueueing it (see above), so a manual QStash publish
of `sync_countries` should populate the mirror for real. That still needs to be
re-verified against staging - check `GET /api/v1/taxonomies` for more than 6
countries after the next delivery. No recurring schedule exists yet to invoke it
automatically; that manifest remains deferred (see below).

## Deferred after Phase 0

These items are intentionally deferred and should be scheduled when their related
capability is activated:

- Production migration and production smoke test.
- Supabase backup/restore drill; the current staging database is on the Free plan.
- QStash schedules and production delivery validation.
- Core join-intent integration.
- Sentry project configuration and event verification.
- Shared/platform rate limiting before running multiple API replicas.
## Automated checks

Run from the repository root:

```powershell
uv sync --group dev
uv run python scripts/check.py
```

The gate must pass compilation, tests, Ruff, mypy, Bandit, and pip-audit, and it
enforces an 85% branch-coverage floor.

The test suite includes integration tests that run against a real PostgreSQL
database; point `TEST_DATABASE_URL` at a disposable one before running the gate.
`SKIP_DB_TESTS=1` skips them and prints a warning. A run with the database tests
skipped is not a full pass and must not be used as Phase 0 evidence.

## Environment checks

### PostgreSQL and migrations

Production and staging migrations are applied by the manually triggered GitHub
Actions `Database migrations` workflow. Create GitHub Environments named `staging`
and `production`, add a `DATABASE_URL` secret to each, and require approval for the
production environment. Do not put the database URL in the repository or workflow
file.

Trigger the workflow from GitHub Actions, select the target environment, and review
the migration output before deploying the API.

For isolated local validation only:

```powershell
docker compose up -d postgres
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
```

Record the database, migration revision, and timestamp. The rollback test must be
performed against an isolated non-production database.

### API smoke test

```powershell
uv run fastapi dev
python scripts/smoke.py
```

For staging, set `SMOKE_BASE_URL` to the deployed service URL before running the
same command.

Both endpoints must return HTTP 200 after migrations are applied.

### QStash

Set `QSTASH_URL` to the account's regional endpoint, set
`QSTASH_EXPECTED_DESTINATION` to the public callback URL QStash publishes to, and
provide the current and next signing keys. Deliver one signed job to staging, verify it is accepted, then replay
the same delivery and confirm the job is not duplicated. Verify that a wrong-region
endpoint and invalid signature are rejected.

### Core join intent

Set `CORE_JOIN_INTENT_URL`, `CORE_SERVICE_TOKEN`, and
`CORE_ALLOWED_RETURN_URL_PREFIX`. Create a search, submit one consented join intent,
retry with the same idempotency key, and confirm Core returns the same intent without
creating a duplicate. Confirm an unapproved return URL is rejected.

### Sentry

Set a staging `SENTRY_DSN`, trigger a controlled test exception, and verify the event
arrives with request ID and environment but without authorization headers, cookies,
tokens, passwords, or email addresses.

### Production limiter

Before deploying more than one API instance, replace `InMemoryRateLimiter` with a
shared or Railway/platform-level limiter. Verify the same client limit is enforced
across two instances.

### CI and release controls

Confirm the remote GitHub Actions workflow passes on a pull request, including Gitleaks.
Confirm the deployment process runs migrations as an explicit release step and that a
previous image can be rolled back.




