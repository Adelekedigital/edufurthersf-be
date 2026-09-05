"""Enqueue prepare_review for every open review task that predates the job.

prepare_review had no worker handler until this pass added one, and the
insert-time trigger in linking.py only fires for a task created from here on.
This is a one-off backfill, not a recurring feature: it walks open review
tasks with draft_recommendation IS NULL and enqueues one job each, via the
same enqueue_job the app itself uses - nothing here writes to the database
directly, and nothing here decides or publishes anything either.

Usage: uv run python scripts/backfill_prepare_review_jobs.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.domain.models import ReviewTask
from app.infra.db import get_session_factory
from app.infra.jobs import enqueue_job


async def main(dry_run: bool) -> None:
    async with get_session_factory()() as db:
        review_task_ids = list(
            await db.scalars(
                select(ReviewTask.review_task_id).where(
                    ReviewTask.state == "open",
                    ReviewTask.resolution.is_(None),
                    ReviewTask.draft_recommendation.is_(None),
                )
            )
        )
        print(f"open review tasks needing a draft: {len(review_task_ids)}")
        if dry_run:
            return
        enqueued = 0
        for review_task_id in review_task_ids:
            _, created = await enqueue_job(
                db,
                "prepare_review",
                f"prepare_review:{review_task_id}",
                {"review_task_id": str(review_task_id)},
            )
            enqueued += 1 if created else 0
        print(f"jobs newly enqueued: {enqueued}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
