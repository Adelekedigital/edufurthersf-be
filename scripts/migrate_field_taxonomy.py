"""Migrate cycle field tags to the product-owned taxonomy.

The command is intentionally dry-run by default. Existing field values are
copied to ``legacy_fields`` before a successful replacement, so the original
classification remains auditable in the JSONB facts document.

Usage:
  uv run python scripts/migrate_field_taxonomy.py --dry-run
  uv run python scripts/migrate_field_taxonomy.py --apply
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.domain.models import ScholarshipCycle
from app.domain.taxonomy import TAXONOMY
from app.infra.db import get_session_factory


async def migrate(*, apply: bool) -> None:
    updated = 0
    unmapped: dict[str, int] = {}
    async with get_session_factory()() as db:
        cycles = list(await db.scalars(select(ScholarshipCycle)))
        for cycle in cycles:
            facts = dict(cycle.facts or {})
            raw = facts.get("fields", [])
            if not isinstance(raw, list) or not all(isinstance(value, str) for value in raw):
                continue
            canonical, unresolved = TAXONOMY.normalize_fields(raw)
            for value in unresolved:
                unmapped[value] = unmapped.get(value, 0) + 1
            if unresolved or facts.get("field_taxonomy_version") == TAXONOMY.version:
                continue
            updated += 1
            if apply:
                facts.setdefault("legacy_fields", sorted(set(raw)))
                facts["fields"] = canonical
                old_names = facts.get("field_names", [])
                if isinstance(old_names, list) and old_names:
                    facts.setdefault("programme_names", old_names)
                facts["field_names"] = [TAXONOMY.fields[value] for value in canonical]
                facts["field_taxonomy_version"] = TAXONOMY.version
                cycle.facts = facts
        if apply:
            await db.commit()
    mode = "updated" if apply else "would update"
    print(f"{mode} cycles: {updated}")
    print(f"unmapped values: {unmapped or 'none'}")
    if unmapped:
        raise SystemExit(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write canonical fields")
    args = parser.parse_args()
    asyncio.run(migrate(apply=args.apply))
