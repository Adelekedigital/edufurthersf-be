"""Enqueue extract_candidate for every discovery that predates the job.

extract_candidate had no worker handler until this pass added one, so no
discovery has ever had one queued. This is a one-off backfill, not a
recurring feature: it walks discoveries with extracted_facts IS NULL and
enqueues one job each, via the same enqueue_job the app itself uses -
nothing here writes to the database directly.

Usage: uv run python scripts/backfill_extraction_jobs.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.domain.models import Discovery
from app.infra.db import get_session_factory
from app.infra.jobs import enqueue_job


async def main(dry_run: bool) -> None:
    async with get_session_factory()() as db:
        discovery_ids = list(
            await db.scalars(
                select(Discovery.discovery_id).where(Discovery.extracted_facts.is_(None))
            )
        )
        print(f"discoveries needing extraction: {len(discovery_ids)}")
        if dry_run:
            return
        enqueued = 0
        for discovery_id in discovery_ids:
            _, created = await enqueue_job(
                db,
                "extract_candidate",
                f"extract_candidate:{discovery_id}",
                {"discovery_id": str(discovery_id)},
            )
            enqueued += 1 if created else 0
        print(f"jobs newly enqueued: {enqueued}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
