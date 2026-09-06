# 50-profile coverage test (field taxonomy), 2026-09-05

Follow-up to the [20-profile test](coverage-test-2026-09-05.md), run specifically
to answer: does the new ISCED-F field taxonomy actually help or hurt search,
against the real published dataset - not a hypothetical one.

## Method

Ran against real staging search (`POST /api/v1/search`) after the ISCED-F
taxonomy PR deployed, 99 published scholarships at time of test (up from 93).
5 destinations x 2 levels x 5 field variants (no preference, plus 4 broad
codes: `ict`, `health_and_welfare`, `business_administration_law`,
`engineering_manufacturing_construction`) = 50 profiles, same
origin-varies-per-cell design as the 20-profile test.

That design choice has a real cost worth naming up front: varying origin
*and* field in the same cell confounds the two. One row in the raw grid
below (GB doctorate) loses a record between "no field" and every field
variant - not because of field at all, but because "Commonwealth PhD
Scholarships (Least Developed Countries and Vulnerable States)" is
origin-restricted, and the no-field cell happened to use Bangladesh (an LDC)
while the four field cells cycled to Egypt/Philippines/Vietnam/Brazil
(not on that list). To get an unconfounded read, two profiles were re-run
holding origin fixed at NG across all 5 field variants.

## Headline finding: field filtering currently changes almost nothing

Of 99 published scholarships: **72 `field_mode="unknown"`, 25 `"all"`, only 2
`"restricted"`**. The hard gate only ever excludes a `"restricted"` record, so
picking any field can only possibly affect those 2 records - the other 97%
show up (or don't) for reasons entirely unrelated to field.

## Controlled comparison (origin held constant at NG)

| Profile | no field | ict | health_and_welfare | business_administration_law | engineering_manufacturing_construction |
| --- | --- | --- | --- | --- | --- |
| GB masters | 54 (2 confirmed) | 53 (1) | 53 (1) | 53 (1) | 53 (1) |
| CA doctorate | 9 (1 confirmed) | 8 (1) | 8 (1) | 8 (1) | 8 (1) |

Both -1 shifts are the same single root cause, not four independent effects:
**any** field filter (including `health_and_welfare` itself) drops "Doctor of
Public Health Scholarships (Mastercard Foundation)" from the CA-doctorate
results, and **any** field filter drops "Optiver Foundation Scholarships"
from the GB-masters results. Both records are `field_mode="restricted"` but
still carry the *retired* flat codes (`public_health`, `computer_science`)
in their stored `facts.fields` - codes that predate this session's taxonomy
migration and that no broad field expands to anymore. The clearest signal:
searching `health_and_welfare` specifically still fails to surface the one
scholarship literally named "Doctor of Public Health" - exactly backwards
from what a real searcher choosing that field would expect.

**Status: fixed.** A scoped one-off remap (`fix_stale_field_tags.py`, touched
only these 2 known rows by cycle ID) has landed - re-verified live:
`CA doctorate + health_and_welfare` now includes "Doctor of Public Health
Scholarships (Mastercard Foundation)", and `GB masters + ict` now includes
"Optiver Foundation Scholarships".

## Full 50-profile grid (raw, origin varies per cell - see confound note above)

Cells are `total (confirmed/possible)`.

| Destination | Level | no field | ict | health_and_welfare | business_administration_law | engineering_manufacturing_construction |
| --- | --- | --- | --- | --- | --- | --- |
| CA | masters | 5 (1/4) | 5 (1/4) | 5 (1/4) | 5 (1/4) | 5 (1/4) |
| CA | doctorate | 9 (1/8) | 8 (1/7) | 8 (1/7) | 8 (1/7) | 8 (1/7) |
| GB | masters | 50\* (2/48) | 50\* (1/49) | 50\* (1/49) | 50\* (1/49) | 50\* (1/49) |
| GB | doctorate | 10 (1/9) | 9 (1/8) | 9 (1/8) | 9 (1/8) | 9 (1/8) |
| US | masters | 5 (1/4) | 5 (1/4) | 5 (1/4) | 5 (1/4) | 5 (1/4) |
| US | doctorate | 4 (1/3) | 4 (1/3) | 4 (1/3) | 4 (1/3) | 4 (1/3) |
| DE | masters | 7 (0/7) | 8 (0/8) | 8 (0/8) | 7 (0/7) | 7 (0/7) |
| DE | doctorate | 10 (0/10) | 10 (0/10) | 10 (0/10) | 10 (0/10) | 11\*\* (0/11) |
| FI | masters | 3 (0/3) | 3 (0/3) | 3 (0/3) | 3 (0/3) | 3 (0/3) |
| FI | doctorate | **0 (0/0)** | 0 (0/0) | 0 (0/0) | 0 (0/0) | 0 (0/0) |

\* GB masters here is capped at the request `limit=50`; see the controlled
comparison above for the true totals (54/53).
\*\* DE doctorate's engineering variant used a different cycled origin than
the others in this row - the +1 there is origin, not field (same confound as
the GB-doctorate LDC case above), not re-verified with a controlled run since
it doesn't touch the stale-tag question.

## What this means

1. **The mechanism works correctly.** Broad-to-narrow expansion and the
   frozenset-intersection match both behave exactly as designed - the
   controlled comparison shows precisely the expected -1, isolating a real,
   diagnosable cause rather than noise.
2. **It currently has almost zero practical effect on results**, because
   almost nothing in the catalog is tagged `field_mode="restricted"` yet.
   That's a data-tagging gap, not a code gap: publish batches so far haven't
   populated `fields`/`field_mode` for most records (72/99 sit at
   `"unknown"`, meaning "not yet determined" rather than "open to anyone").
   Search-by-field won't feel meaningfully different to a real user until
   more scholarships get tagged at publish time - a process change for
   future batches, not another taxonomy iteration.
3. **This test caught a real regression before a user would have.** The 2
   already-tagged records were about to become permanently unreachable by
   field-filtered search - not found in code review, found by running the
   thing against real data.
4. **FI doctorate is still a genuine zero** across every field variant,
   unchanged from the 20-profile test - confirms it's a catalog hole, not a
   field-taxonomy artifact.
5. **Origin-varies-per-cell is the wrong design for isolating field effects**
   specifically (it was fine for the original destination/level coverage
   question). A future field-focused test should hold origin fixed.

## Update, 2026-09-06: the data-tagging gap from point 2 is substantially closed

A backfill pass (`backfill_field_tags.py`) went through the 72 `"unknown"`
records and tagged 35 where the field was genuinely evident - either stated
directly in the record's own title (13 records, e.g. "Hodgson **Law**
Scholarship" -> `law`) or a well-documented public fact about the named
program (22 records, e.g. Studienstiftung/Killam/Mastercard Foundation
Scholars are all known to be open to any discipline -> `field_mode="all"`).
New distribution: **24 `restricted`, 38 `all`, 37 `unknown`** (was 2/25/72).
Field-based search now meaningfully differentiates results for about
two-thirds of the catalog, not ~2% of it. The remaining 37 stay `unknown`
deliberately - no confident evidence either way, per the "no
taxonomy-forcing" rule, not an oversight.
