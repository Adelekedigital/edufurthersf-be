# Phase 0 release checklist

Phase 0 is complete only when the code checks and the environment checks below have
recorded evidence. Keep credentials and customer data out of evidence attachments.

## Current Phase 0 status

The current Phase 0 scope is complete: the backend is published, staging migrations
have succeeded, the API is deployed, staging smoke checks pass, and the GitHub quality
gate is green.

## Phase 0 and deferred validation matrix

| Item | Owner | What is needed to close it | Evidence |
| --- | --- | --- | --- |
| Automated quality gate | Engineering | Already implemented | Passing `scripts/check.py` output |
| Staging API smoke test | You/Engineering | A running staging URL and deploy access | `SMOKE_BASE_URL=... python scripts/smoke.py` returns three PASS lines |
| Core join intent | You/Core owner | Core staging URL, service token, allowed return URL, and a test search/session | One successful request plus same-key retry with no duplicate Core intent |
| QStash delivery | You/Platform owner | Region, QStash URL, current/next signing keys, and a staging callback URL | Accepted signed delivery and rejected replay/invalid-region or signature case |
| Sentry verification | You/Platform owner | Staging Sentry DSN and permission to inspect the project | Scrubbed test event visible in Sentry |
| Production rate limiting | Engineering/Platform | Decision and access to Railway/platform limiter or shared store | Same client limit observed across two instances |
| Backup and rollback | You/Platform owner | Non-production database backup destination and deployment access | Restore, migration rollback, and previous-image rollback records |
| CI and Gitleaks | You/repository owner | GitHub repository access and Actions enabled | Passing pull-request workflow run with Gitleaks |

The matrix records both completed Phase 0 evidence and deferred operational follow-up. Deferred items are not current Phase 0 blockers.

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

The gate must pass compilation, tests, Ruff, mypy, Bandit, and pip-audit.

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




