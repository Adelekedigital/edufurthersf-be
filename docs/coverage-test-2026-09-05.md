# 20-profile coverage test, 2026-09-05

Run for issue #3 after the 75-150 published-scholarship target (#2) was met.
Full results also posted to
[issue #3](https://github.com/Adelekedigital/edufurthersf-be/issues/3) at
close time; recorded here too since a GitHub issue comment isn't discoverable
the way a repo doc is.

## Method

Ran against real staging search (`POST /api/v1/search`), 93 published
scholarships at time of test. The field taxonomy only has two real codes
(`public_health`, `computer_science`) - there is no literal "any field" API
value, so the 20 profiles are a full 5 destinations x 2 levels x 2 fields
grid (exactly 20), each paired with a different origin country for spread
rather than one repeated origin.

## Results

18 of 20 profiles returned at least one match. 2 returned zero.

| Destination | masters range (confirmed/possible) | doctorate range (confirmed/possible) |
| --- | --- | --- |
| CA | 1 / 2 | 1 / 6-7 |
| GB | 1-2 / **51** | 1 / 9 |
| US | 1 / 4 | 1 / 3 |
| DE | 0 / 6 | 0 / 8 |
| FI | 0 / 3 | **0 / 0** |

## Real gaps found, not just pass/fail

1. **Finland has zero doctoral-level coverage.** Both field variants tested
   (`public_health`, `computer_science`) for `FI` + `doctorate` returned
   nothing - not a field-specific artifact, a genuine hole. FI only has
   masters-level scholarships published (Aalto University).
2. **GB is heavily overrepresented.** 51 possible matches on a masters query
   vs. 2-9 for every other destination. Expected, given ScholarshipRegion's
   UK-heavy backlog plus the Commonwealth Scholarship Commission landing 3
   UK-specific schemes the same session - but it means the catalogue's actual
   balance skews hard toward one destination, not evenly across the five
   supported ones.
3. **Canada has the thinnest coverage** of the four non-FI destinations
   (2-7 matches per profile).
4. **"Confirmed" fit is rare even where matches exist** - most hits are
   "possible," not "confirmed." This tracks with how many records (DAAD's
   EPOS/GROW, CSC's Shared Scholarships) were honestly published with
   `origin_mode=unknown` rather than a guessed list, per
   `candidate-verification-standard.md`'s rule against forcing a
   false-confident `origin_mode`. Raising the confirmed-fit rate needs
   resolving more of those unresolved country lists, not more raw volume.

## What this should shape next

Before adding another data source purely for volume: Finland-doctorate and
Canada are the concrete gaps a next sourcing pass should target, not "more of
anything." A source that only deepens GB (e.g. Chevening) would make the
imbalance worse, not better - deprioritized in favor of Finland/Canada-
focused sourcing until this specific gap closes.
