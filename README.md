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
- `GET /ready` — database readiness check
- `GET /api/v1/taxonomies` — supported search taxonomy
- `POST /api/v1/search` — search published scholarships
- `GET /api/v1/scholarships/{id-or-slug}` — scholarship details
- `POST /api/v1/internal/jobs` — stable QStash job callback

Search only reads published, approved data. Crawling, source processing, and review
are asynchronous workflows; no LLM is called synchronously by the search endpoint.

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
URL. The older `/internal/jobs/{kind}` route remains for compatibility.

### Rate limiting

The current anonymous search limiter is process-local and suitable for local
development or a single API instance. Before running multiple instances, use a
Railway/platform-level limiter or replace it with a shared-store implementation.

## Database migrations

Local migration validation uses:

```powershell
uv run alembic upgrade head
```

Staging and production migrations are applied explicitly through the manually
triggered `Database migrations` GitHub Actions workflow. Configure `DATABASE_URL` as
a secret in the corresponding GitHub Environment and require approval for production.

The API container does not run migrations automatically at startup.

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
