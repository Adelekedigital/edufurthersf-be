import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TaxonomyItem(BaseModel):
    code: str
    label: str


class TaxonomiesResponse(BaseModel):
    version: str
    #: Every country a student may state as their origin.
    countries: list[TaxonomyItem]
    #: The subset with verified coverage, which is where a search can be run.
    destinations: list[TaxonomyItem]
    degrees: list[TaxonomyItem]
    #: Broad ISCED-F 2013 fields (11 codes) - what a search form offers.
    fields: list[TaxonomyItem]
    #: Narrow ISCED-F 2013 fields (29 codes) - what a scholarship is actually
    #: tagged with at publish time; not a search filter itself.
    narrow_fields: list[TaxonomyItem]
    award_types: list[TaxonomyItem]
    #: How much of the cost an award covers - distinct from `award_types`.
    funding_types: list[TaxonomyItem]


class SearchRequest(BaseModel):
    origin_country: str = Field(min_length=2, max_length=3)
    # Validated against the taxonomy rather than pinned here, so accepted
    # aliases ("phd") resolve to the canonical Core-aligned code in one place.
    program_level: str = Field(min_length=1, max_length=40)
    #: Optional broad ISCED-F field code (see GET /taxonomies `fields`).
    #: Omit (or send null) for no field preference.
    field: str | None = Field(default=None, max_length=100)
    target_countries: list[str] = Field(min_length=1, max_length=10)
    limit: int = Field(default=20, ge=1, le=50)
    cursor: str | None = None


class SearchResult(BaseModel):
    scholarship_id: uuid.UUID
    cycle_id: uuid.UUID
    name: str
    provider: str
    award_type: str
    status: str
    #: A display-only refinement of `status`: "open"/"closing_soon" for
    #: open_verified, "opening_soon"/"likely_to_reopen" for
    #: expected_to_reopen (the latter two distinguished only when a reviewer
    #: has real evidence of roughly when), "status_unknown" otherwise. Never
    #: use this in place of `status` for eligibility logic - it's presentation
    #: detail, not the business state.
    status_detail: str
    fit: Literal["confirmed", "possible"]
    official_url: str
    last_verified_at: datetime | None = None
    #: A real restriction origin_mode/field_mode cannot represent
    #: structurally (an exclude-one rule, an immigration status, a
    #: demographic restriction) - a distinct field so a frontend can render
    #: it as its own label, not lost inside generic matching/freshness
    #: caveats.
    eligibility_note: str | None = None
    #: The source's own course/subject wording ("MSc Development Economics"),
    #: alongside (never instead of) the normalised ISCED-F `fields` codes
    #: used for matching - a distinct field for the same reason as
    #: `eligibility_note`: a frontend shouldn't need to parse `facts` to show
    #: the specific programme name.
    field_names: list[str] = Field(default_factory=list)
    #: This scholarship's own destination code(s), from `facts["destinations"]`
    #: - one of the `GET /taxonomies` `destinations` codes. A frontend must
    #: not infer a result's country from the search's own `target_countries`
    #: (e.g. showing every card the first selected destination): a search can
    #: target several countries at once, and which one(s) this specific award
    #: actually covers is a fact about the award, not about the query.
    destinations: list[str] = Field(default_factory=list)
    #: Null when this award has no fixed deadline (rolling, or not yet set).
    deadline_at: datetime | None = None
    #: Whether `deadline_at` is evidenced down to the minute or only the day
    #: - render "by 12 Sep 2026" for `"date"`, not a fabricated time of day.
    #: Meaningless (and always omitted from `facts`) when `deadline_at` is
    #: null.
    deadline_precision: Literal["date", "datetime"] | None = None
    #: TAXONOMY.degrees codes this cycle accepts, from `facts["levels"]` -
    #: not to be confused with `field`/`fields`, which is subject not level.
    degree_levels: list[str] = Field(default_factory=list)
    #: A cyclic month number (1-12), never a year - the source rarely commits
    #: to a specific year for "reopens around February." Pair with
    #: `status_detail == "opening_soon"`/`"likely_to_reopen"` for copy; null
    #: means no such evidence exists, not "unknown year."
    expected_reopen_month: int | None = Field(default=None, ge=1, le=12)
    #: One of `GET /taxonomies` `funding_types`, or null when the reviewer
    #: had no evidence of coverage level. Distinct from `award_type` - see
    #: that field's own note.
    funding_type: str | None = None
    #: Where the *provider* institution/organization is based - a fact about
    #: the provider, not this award's study destination (see
    #: `destinations`). Null for a provider registered before this existed;
    #: never guessed from `destinations`.
    provider_country: str | None = None
    caveats: list[str] = Field(default_factory=list)


class SearchMeta(BaseModel):
    search_id: uuid.UUID
    # Identifies the exact response page, so a later view or click event can be
    # tied to what was actually shown rather than to the search as a whole.
    response_id: uuid.UUID
    evaluated_at: datetime
    #: No default - deliberately required. The one construction site is
    #: expected to pass MATCH_POLICY_VERSION/TAXONOMY.version explicitly, the
    #: same source of truth used for the stored Search row and the analytics
    #: event; a silently-matching default here previously let those three
    #: copies drift out of sync with no test to catch it.
    match_policy_version: str
    taxonomy_version: str
    #: Still deliberately required here - POST /search always aggregates
    #: these fresh from the whole matched set, so widening this base type to
    #: Optional would let a frontend client generated from POST's own schema
    #: null-check something that can never actually be null on that endpoint,
    #: and would let a future POST-handler bug that forgets to set them pass
    #: validation silently instead of failing loudly. GET /search/{search_id}
    #: (which *can* legitimately have neither, replaying a search stored
    #: before this pair started being persisted) uses ReplaySearchMeta below
    #: instead of widening this shared type.
    confirmed_counts: dict[str, int]
    possible_match_count: int
    warnings: list[str] = Field(default_factory=list)


class ReplaySearchMeta(SearchMeta):
    """`SearchMeta` with `confirmed_counts`/`possible_match_count` widened to
    optional - only `GET /search/{search_id}` can legitimately have neither,
    replaying a search stored before this pair started being persisted.

    mypy flags widening a field's type in a subclass as an LSP violation
    (a `SearchMeta`-typed reference could statically expect a non-None
    value); safe in practice since Pydantic validates the actual instance
    and no code treats a `ReplaySearchMeta` as a plain `SearchMeta`.
    """

    confirmed_counts: dict[str, int] | None  # type: ignore[assignment]
    possible_match_count: int | None  # type: ignore[assignment]


class SearchResponse(BaseModel):
    data: list[SearchResult]
    next_cursor: str | None = None
    meta: SearchMeta


class SearchReplayResponse(SearchResponse):
    """`GET /search/{search_id}`'s own response shape - extends
    `SearchResponse` (not a fully separate schema) so a future change to
    `data`/`next_cursor` doesn't have to be mirrored by hand into two
    classes; `meta` is narrowed to `ReplaySearchMeta` and `filters` is new,
    neither of which touches `SearchResponse`'s own contract for POST
    /search."""

    meta: ReplaySearchMeta
    #: The exact filters this search ran with - Search.filters verbatim
    #: (origin_country, target_countries, program_level, field). A superset
    #: of what POST /scholarships/{id}'s MatchProfileRequest declares (it has
    #: no target_countries field) but safe to pass through unmodified: that
    #: model doesn't forbid extra fields, so restoring a personalized modal
    #: explanation from this dict needs no trimming.
    filters: dict
