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
    (open/closing_soon/likely_to_open/status_unknown).
4. **The field taxonomy is product-owned** with 14 canonical codes returned by
   `/taxonomies` - see "Fields" below.
5. **`fields`, `field_names`, and `programme_names`** are returned on every
   search result and detail response. `fields` are canonical codes,
   `field_names` are their canonical labels, and `programme_names` preserves
   source-specific wording such as "MSc Development Economics".
6. **`POST /scholarships/{identifier}` is new** (`GET` still exists,
   unchanged) - same detail response, plus an AI-generated
   `match_explanation` when you send the searcher's profile. See below.
7. **`destinations` is new** on every search result and the detail response -
   fixes real observed behavior where a card showed `target_countries[0]`
   (the first destination the searcher selected) as if it were the award's
   own country, mislabeling awards from a multi-destination search (e.g. a
   Canada-only award showing as "United States"). See "Destination display"
   below - stop reading a result's country off the search filter.
8. **`deadline_at`, `deadline_precision`, `degree_levels`, and
   `expected_reopen_month` are new** on every search result - all four were
   already computed server-side for `status`/`status_detail` but never
   returned, so a card had no way to show an actual deadline date or degree
   badge without parsing `status_detail` copy.
9. **`funding_type` and `provider_country` are new** - both required real
   backend work, not just a schema tweak (a new taxonomy for the former, a
   new `Provider.country` column for the latter), so they landed a beat
   after the rest of the design-card fields. See "Funding type" and
   "Provider country" below - in particular, don't confuse `funding_type`
   with `award_type` (already existed), and don't confuse `provider_country`
   with `destinations` (the award's own study country) - they answer
   different questions and can legitimately differ on the same award (a
   UK-based foundation funding study in Canada).
10. **`GET /search/{search_id}` is new** - replays a search's stored page one
    (30-day retention) without a fresh `POST`, for a page refresh,
    back-navigation, or a shared/bookmarked results link. See below.
    `meta.confirmed_counts`/`possible_match_count` are now nullable on the
    shared meta shape - only ever `null` on a `GET` replay of a search made
    before this endpoint shipped, never on `POST /search` itself.
11. **`GET`/`POST /scholarships/{identifier}`'s `status` field changed** -
    it now returns the same display-refined value `/search` does
    (`open`/`closing_soon`/`likely_to_open`/`status_unknown`), not the raw
    internal state (`open_verified`/`expected_to_reopen`/`status_unknown`)
    it returned before. If you were branching on the old raw values from the
    detail endpoint specifically, update that logic - `status_detail` is
    unchanged and was already this display value on both endpoints.
12. **`/search` result ordering is now a global guarantee, not a per-status
    one** - a confirmed match always sorts above every possible match,
    regardless of which of their status buckets (open/closing_soon/
    likely_to_open) sorts earlier. Previously a possible match in an
    earlier-sorting bucket (e.g. `open`) could appear above a confirmed
    match in a later one (e.g. `closing_soon`); don't rely on the old
    ordering if you built anything around it.

## `GET /taxonomies`

The vocabularies a search form is built from:

```jsonc
{
  "version": "taxonomy-v3",
  "countries": [{ "code": "NG", "label": "Nigeria" }, ...],   // any origin
  "destinations": [{ "code": "CA", "label": "Canada" }, ...], // verified-coverage subset of countries
  "degrees": [{ "code": "masters", "label": "Master's" }, { "code": "mba", "label": "MBA" }, { "code": "doctorate", "label": "PhD" }],
  "fields": [{ "code": "technology", "label": "Technology" }, ...], // canonical product fields
  "award_types": [{ "code": "scholarship", "label": "Scholarship" }, ...], // what kind of instrument
  "funding_types": [{ "code": "fully_funded", "label": "Fully funded" }, ...] // how much of the cost is covered - see "Funding type" below
}
```

Fetch this once and cache it; it changes rarely. Use `fields` to populate the
field dropdown. There is no separate `narrow_fields` collection.

Current field codes are `technology`, `engineering`,
`mathematics_and_statistics`, `natural_sciences`,
`health_and_medical_sciences`, `business_and_management`,
`economics_and_development`, `social_sciences`, `law`,
`public_policy_and_governance`, `education`, `arts_humanities_and_design`,
`agriculture_and_food_systems`, and `environmental_and_climate_sciences`.

Optionally narrow the response with a repeated `types` query param -
`GET /taxonomies?types=fields` returns only that collection; every other key
comes back as `[]`, not omitted, so the shape
never changes. Omitting `types`, or sending it empty (`?types=`), both mean
"no filter" and return the full vocabulary - same result either way. Valid
values: `countries`, `destinations`, `degrees`, `fields`, `award_types`,
`funding_types`. An actual unrecognized value (e.g.
`?types=bogus`) is a `422`.

If your HTTP client serializes arrays with a bracket suffix
(`types[]=fields`) rather than FastAPI's plain repeated-key form, that's
accepted too - both forms filter identically, and neither silently falls
back to the full vocabulary when populated.

## `POST /search`

```jsonc
// request
{
  "origin_country": "NG",       // any real country, 2-3 chars
  "program_levels": ["masters"], // one or more of "masters" | "mba" | "doctorate"
  "target_countries": ["CA", "GB"], // 1-10 countries; may include uncovered ones, see below
  "field": "health_and_medical_sciences", // optional - omit/null for no field preference
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
      "status": "closing_soon",         // "open" | "closing_soon" | "likely_to_open" - display value, see "status vs status_detail" below
      "status_detail": "closing_soon",  // same display value today - never use either for eligibility logic
      "fit": "confirmed",               // "confirmed" | "possible"
      "official_url": "https://...",
      "last_verified_at": "2026-08-01T00:00:00Z",
      "eligibility_note": "Not open to UK nationals.", // present only for a restriction the schema can't otherwise represent
      "fields": ["economics_and_development"],
      "field_names": ["Economics and Development"],
      "programme_names": ["MSc Development Economics"],
      "destinations": ["CA"], // this award's own destination code(s) - see "Destination display" below
      "deadline_at": "2026-12-31T00:00:00Z", // null when rolling/not yet set
      "deadline_precision": "date", // "date" | "datetime" | null (null iff deadline_at is null) - "date" means don't render a time of day
      "degree_levels": ["masters"], // GET /taxonomies `degrees` codes this cycle accepts
      "expected_reopen_month": null, // 1-12, cyclic - never a year. Only meaningful with status "likely_to_open"
      "funding_type": "fully_funded", // one of GET /taxonomies `funding_types`, or null - see "Funding type" below
      "provider_country": "GB", // where the *provider* is based, or null - see "Provider country" below. NOT the study destination
      "caveats": ["Some eligibility conditions need checking."]
    }
  ],
  "next_cursor": "...",  // null when there's no next page
  "meta": {
    "search_id": "...", "response_id": "...", "evaluated_at": "...",
    "match_policy_version": "match-v2", "taxonomy_version": "taxonomy-v3",
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

### Destination display (per result)

`destinations` on each result is that award's own destination code(s) - a
subset of `GET /taxonomies` `destinations`, and typically one code today
(no published award currently covers more than one country, though the
schema allows it). **Don't infer a card's country from the search's own
`target_countries`** (e.g. always labeling every result with
`target_countries[0]`) - a search can target several countries at once, and
which one(s) a given award actually covers is a fact about the award, not
about the query. Look the code(s) up in the `destinations` you already
fetched from `GET /taxonomies` for the label, the same way you already do
for the search form.

### Deadline, degree, and reopen month (per result)

- `deadline_at` / `deadline_precision`: null/null together when there's no
  deadline (rolling, or not yet set). When present, `deadline_precision`
  `"date"` means render a date only ("by 31 Dec 2026") - the time-of-day
  component of `deadline_at` is not evidenced and must not be shown or used
  for a live countdown; `"datetime"` means the full instant is real.
- `degree_levels`: this cycle's accepted `GET /taxonomies` `degrees` codes
  (e.g. `["masters", "doctorate"]`) - not the same taxonomy as `fields`.
- `expected_reopen_month`: a bare month number, 1-12, cyclic - there is no
  year in the data (`"reopens around February"`, not a specific date), so
  don't render one. Only meaningful when `status` is `"likely_to_open"`;
  null otherwise.

### Funding type

`funding_type` is how much of the cost is covered - `fully_funded` /
`partial_funding` / `tuition_only` / `stipend_only`, from `GET /taxonomies`
`funding_types`. **Don't confuse it with `award_type`** (already existed:
`scholarship` / `fellowship` / `assistantship` / `studentship` / `grant`) -
that's what *kind* of instrument the award is, a separate axis. A
scholarship and a fellowship can each independently be fully-funded or
partial; render both badges, don't collapse one into the other. Optional
and null for most records today (only just started being captured at
publish time, same rollout curve as `field_names`/`eligibility_note` when
those launched).

### Provider country

`provider_country` is where the *provider* institution/organization is
based - a fact about the provider, shared across every award it funds.
**Don't confuse it with `destinations`** (the award's own study
country/countries) - a UK-based foundation funding study in Canada
legitimately has `provider_country: "GB"` and `destinations: ["CA"]` at the
same time; neither implies the other. Null for a provider that hasn't had
its country looked up and entered yet - most of the current catalog, since
this just started being captured. Don't infer or guess it from
`destinations`.

### Fields

`field` is optional and, when given, is one of the canonical product codes
from `GET /taxonomies`' `fields` list (e.g. `technology`,
`health_and_medical_sciences`). Omitting it means "no field preference" -
this is a legitimate, common choice, not a degraded one; don't force a
selection. Catalog coverage for the new fields must be measured again after
the data backfill; the previous ISCED-F coverage report is historical.

### status vs status_detail

Both `/search` results and the `GET`/`POST /scholarships/{identifier}`
detail response expose only the user-facing `status` values `open`,
`closing_soon`, and `likely_to_open` (plus `status_unknown`, detail only -
see below). Internal records may retain `open_verified`,
`expected_to_reopen`, or `status_unknown`; `status_detail` mirrors the same
display refinement as `status` on both endpoints today:

- `open_verified` -> `"open"` normally, `"closing_soon"` inside 14 days of
  the deadline.
- `expected_to_reopen` -> `"likely_to_open"`.

**`status_unknown` is search-only-excluded, not detail-only-excluded**: a
record whose internal state evaluates to `status_unknown` is dropped from
`/search` results entirely, but the detail endpoint still returns it (with
`status`/`status_detail` both `"status_unknown"`) for a direct/shared link -
handle that value on the detail page even though you'll never see it from a
search result card.

Use `status`/`status_detail` for wording/badges only. Eligibility and
filtering key off the internal evaluated state before the public result is
built.

### Pagination

A fresh search (no `cursor`) always starts a new `search_id`; pass
`next_cursor` back as `cursor` for the next page of the *same* search - don't
resubmit the original filters as a new search per page, since that would
count as a new search event.

## `GET /search/{search_id}`

Replays a search's stored page one - same `SearchResult`/`meta` shape as
`POST /search`, plus a `filters` field:

```jsonc
// response
{
  "data": [ /* same shape as POST /search's data */ ],
  "next_cursor": "...",
  "meta": { /* same shape as POST /search's meta - confirmed_counts/possible_match_count nullable, see above */ },
  "filters": {
    "origin_country": "NG", "target_countries": ["CA", "GB"],
    "program_levels": ["masters"], "field": "health_and_medical_sciences"
  }
}
```

Use `filters` to restore the searcher's profile for `POST
/scholarships/{identifier}`'s personalized `match_explanation` (it has
`origin_country`/`program_levels`/`field` - `target_countries` is extra,
ignore it there) without needing the original search form state around.

Requires the same session cookie the original `POST /search` set - **not** a
bare shareable link like `GET /scholarships/{identifier}` is. A search made
in a different browser/session, an unknown `search_id`, or one past its
30-day retention all come back as a plain `404` - same shape as any other
not-found, nothing distinguishes "never existed" from "not yours." Response
carries `Cache-Control: private, no-store` - don't let a shared cache/CDN
serve one visitor's replayed search to another.

A scholarship withdrawn since the original search is silently omitted from
the replayed `data` - `meta.total_match_count` stays as originally recorded
(an accurate history of what the search found at the time), only the
displayed rows reflect current withdrawal state.

## `GET` / `POST /scholarships/{identifier}`

Same URL, same `ScholarshipDetailResponse` shape either way - the method is
what decides whether a personalised AI explanation gets generated.

- **`GET`** - no body, no AI Router call, ever. Use this for a bare/shared
  link, SEO, or anywhere you don't have the searcher's profile handy.
  `match_explanation` is always `null`.
- **`POST`** - body is the searcher's profile:
  ```jsonc
  { "origin_country": "NG", "program_levels": ["masters"], "field": "technology" }
  ```
  (`field` optional, same broad code as `/search`; no `target_countries` -
  the destination is already fixed by whichever scholarship this is.) If the
  profile is a genuine deterministic match for this scholarship (same rules
  `/search` uses), the response includes:
  ```jsonc
  "match_explanation": "This scholarship suits your profile because ..."
  ```
  If the profile *isn't* a match at all (wrong degree level, ineligible
  origin, wrong field), `match_explanation` stays `null` - there's nothing
  true to explain about a non-match, so no AI call is even attempted. It can
  also be `null` when it *is* a match but the AI Router is temporarily
  unavailable - treat an absent explanation as "not available right now,"
  never as a sign the scholarship doesn't fit.

Call `POST` only when you actually have profile context (e.g. the searcher
just came from a `/search` submission) and want the explanation - it has its
own, tighter rate limit than search (a cache miss is a real paid call, not a
free DB query), so don't call it speculatively for every card in a list.

**Recommended loading pattern for the detail page**: call `GET` first and
render the scholarship's details immediately - it's always fast, never
touches the AI Router. Call `POST` in parallel (or right after) purely to
fill in `match_explanation`, and show a loading state for *just that
section* while it resolves, since a cache miss makes a real synchronous AI
call (bounded to 10s server-side, then it gives up and returns `null` rather
than hanging). Don't block the whole page on `POST` - the explanation is a
nice-to-have addition to a page that already has everything else it needs
from `GET`.

**Currently behind a feature flag, off by default** (`match_explanation`
will always be `null` from `POST` until the team turns it on) - don't build
against it landing "any day"; there's no ETA yet.

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
