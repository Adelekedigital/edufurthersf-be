import uuid
from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class FeedRecord(BaseModel):
    """The Sheet's five known columns, plus which Source produced the row.

    ``source_posted_at``/``feed_created_at`` are the feed's own Source Posted
    Date and Created Date. They mean publication or discovery, never an
    application deadline, and are carried through unchanged rather than
    interpreted here.
    """

    source_id: uuid.UUID
    url: HttpUrl
    title: str = Field(min_length=1, max_length=500)
    excerpt: str | None = Field(default=None, max_length=5000)
    source_posted_at: datetime | None = None
    feed_created_at: datetime | None = None


class FeedImportRequest(BaseModel):
    records: list[FeedRecord] = Field(min_length=1, max_length=500)


class FeedImportResponse(BaseModel):
    crawl_run_id: uuid.UUID
    #: A previously unseen URL became a new Discovery.
    imported: int
    #: An already known URL reported again with unchanged content.
    repeated: int
    #: An already known URL reported again with different content; a new
    #: Discovery was created, superseding the previous one.
    changed: int
    #: Could not become a Discovery at all; preserved in DiscoveryQuarantine.
    rejected: int
