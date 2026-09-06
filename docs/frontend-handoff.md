# Frontend handoff

What the Finder backend (`edufurthersf-be`) actually offers today, for
whoever's building the search UI in the frontend repo/session. This
supersedes any earlier in-chat handoff notes - those weren't captured as a
doc, this is now the reference.

Base URL (staging): `https://edufurthersf-be-dev.up.railway.app/api/v1`

## Changes since the last handoff

1. **Destinations are never a hard refusal.** A search naming a real but
   unsupported destination country used to 422 the whole request. It now
   runs for whichever destinations *are* covered and reports the rest via
   `meta.warnings` - see "Destinations" below. Build the UI to *disclose*,
   not block.
2. **Errors are RFC7807 end to end**, including a real `Retry-After` header
   on 429s - see "Errors" below.
3. **`status_detail` is new** on every search result and the detail
   response - a presentation-only refinement of `status`
   (open/closing_soon/opening_soon/likely_to_reopen/status_unknown).
4. **The field taxonomy was rebuilt** from 2 flat codes to ISCED-F 2013 (11
   broad codes for search, 29 narrow codes used only for tagging) - see
   "Fields" below. Practically: expect `field` to now be a real dropdown of
   11 options, not a binary choice.
5. **`field_names` is new** on every search result and the detail response -
   the source's own course/subject wording ("MSc Development Economics"),
   verbatim, alongside the normalised broad/narrow codes. Use it to show the
   *specific* programme name; the `field` codes are for filtering, not for
   display copy. Empty for most records today (only just started being
   populated at publish time).

## `GET /taxonomies`

The vocabularies a search form is built from:

```jsonc
{
  "version": "taxonomy-v1",
  "countries": [{ "code": "NG", "label": "Nigeria" }, ...],   // any origin
  "destinations": [{ "code": "CA", "label": "Canada" }, ...], // verified-coverage subset of countries
  "degrees": [{ "code": "masters", "label": "Master's" }, { "code": "doctorate", "label": "PhD" }],
  "fields": [{ "code": "ict", "label": "Information and Communication Technologies (ICT)" }, ...], // 11 broad codes - use this for the search filter
  "narrow_fields": [{ "code": "health", "label": "Health" }, ...], // 29 codes, not a search filter - reference only
  "award_types": [{ "code": "scholarship", "label": "Scholarship" }, ...]
}
```

Fetch this once and cache it; it changes rarely. Use `fields` (broad) to
populate the field dropdown - `narrow_fields` exists for completeness/future
use (e.g. showing a scholarship's specific tagged programme on its detail
page) but isn't itself a valid `field` search value.

## `POST /search`

```jsonc
// request
{
  "origin_country": "NG",       // any real country, 2-3 chars
  "program_level": "masters",   // "masters" | "doctorate" (aliases like "phd" also accepted)
  "target_countries": ["CA", "GB"], // 1-10 countries; may include uncovered ones, see below
  "field": "health_and_welfare", // optional - omit/null for no field preference. One of the 11 broad codes from GET /taxonomies `fields`
  "limit": 20,                   // 1-50, default 20
  "cursor": "..."                // omit on a fresh search; pass back for the next page
}
```

```jsonc
// response
{
  "data": [
    {
      "scholarship_id": "...", "cycle_id": "...",
      "name": "...", "provider": "...", "award_type": "scholarship",
      "status": "open_verified",        // "open_verified" | "expected_to_reopen" | "status_unknown" - the business state
      "status_detail": "closing_soon",  // presentation refinement, see below - never use for eligibility logic
      "fit": "confirmed",               // "confirmed" | "possible"
      "official_url": "https://...",
      "last_verified_at": "2026-08-01T00:00:00Z",
      "eligibility_note": "Not open to UK nationals.", // present only for a restriction the schema can't otherwise represent
      "field_names": ["MSc Development Economics"], // source's own wording, for display - not a filter value
      "caveats": ["Some eligibility conditions need checking."]
    }
  ],
  "next_cursor": "...",  // null when there's no next page
  "meta": {
    "search_id": "...", "response_id": "...", "evaluated_at": "...",
    "match_policy_version": "match-v1", "taxonomy_version": "taxonomy-v1",
    "confirmed_counts": { "...": 0 },
    "possible_match_count": 0,
    "warnings": ["no_verified_coverage:FR,DE"]
  }
}
```

### Destinations

`target_countries` accepts any real country. A destination the index has no
verified coverage for is never rejected outright - the search still runs for
whichever destinations *are* covered, and `meta.warnings` carries
`no_verified_coverage:<comma-separated codes>` for the rest. **Render this
explicitly** ("We don't have verified coverage for France yet - showing
results for Canada" rather than silently dropping the country or erroring).

### Fields

`field` is optional and, when given, is one of the 11 broad ISCED-F codes
from `GET /taxonomies`' `fields` list (e.g. `ict`, `health_and_welfare`,
`business_administration_law`). Omitting it means "no field preference" -
this is a legitimate, common choice, not a degraded one; don't force a
selection. Heads up on impact: as of this test pass, only 2 of 99 published
scholarships are actually tagged with a specific field (`field_mode:
"restricted"`) - the rest are open to any field or not yet classified, so
picking a field narrows results by very little today. That will improve as
more scholarships get tagged at publish time; it's not a frontend concern to
solve.

### status vs status_detail

`status` is the business state search/eligibility already reflects.
`status_detail` is a display-only refinement for copy/badges:

- `open_verified` -> `"open"` normally, `"closing_soon"` inside 14 days of
  the deadline.
- `expected_to_reopen` -> `"likely_to_reopen"` normally, `"opening_soon"`
  when the expected reopen month is imminent (within 1 month).
- anything else -> `"status_unknown"`.

Use `status_detail` for wording/badges only. Eligibility and any
filtering/sorting logic must key off `status`, never `status_detail`.

### Pagination

A fresh search (no `cursor`) always starts a new `search_id`; pass
`next_cursor` back as `cursor` for the next page of the *same* search - don't
resubmit the original filters as a new search per page, since that would
count as a new search event.

## Errors

Every 4xx/5xx is `application/problem+json` (RFC7807):

```jsonc
{
  "type": "https://errors.edufurther.com/rate_limit_exceeded",
  "title": "Request failed",
  "status": 429,
  "detail": "Search rate limit exceeded",
  "code": "RATE_LIMIT_EXCEEDED",  // machine-readable - branch on this, not `status` or `title`
  "instance": "https://.../api/v1/search"
}
```

A 429 also carries a `Retry-After: 60` header - respect it (disable the
submit button / show a countdown) rather than retrying immediately. A 422
validation error additionally carries `errors.fields` with the specific
field-level problems (from Pydantic).

## Not yet a frontend concern

- **Join-intent** (`POST /join-intents`, the Core handoff) is deprioritized
  relative to the Substack e-book flow per current product priority - it's
  pending the new app release, so don't block on wiring it up now.
- **E-book download tracking** uses Substack's own native analytics for v1 -
  no Finder API involvement at all (see issue #14). Nothing to build here.

## Known catalog gaps (not a frontend bug if you see these)

- Finland has zero doctoral-level scholarships published - a real catalog
  hole, not a search bug.
- GB is heavily overrepresented (50+ masters matches vs. single digits for
  most other destinations) - reflects the current sourcing mix, being
  addressed by prioritizing Finland/Canada sourcing over more GB volume.
- Most matches are `"possible"` fit, not `"confirmed"` - many real records
  are honestly published with `origin_mode="unknown"` rather than a guessed
  eligibility list. Design the UI to present "possible" results as
  legitimate, not second-class - they're honesty, not incompleteness.
