# Candidate verification standard

This is the working standard behind every publish/reject decision made
against real ScholarshipRegion discoveries in this session (Maine, UCL x2,
Hornby, Bristol, Warwick, Göttingen, Washington, SENSS, UCL/King's
College/Cranfield Commonwealth Shared, Westminster - 12 published, 30
rejected, out of 44 fully verified). It exists so the next person, the next
session, or the eventual automated pipeline (see "Future automation" below)
makes the same calls for the same reasons, not a fresh judgment call each
time.

## Why this exists

ScholarshipRegion is a Tier C aggregator: useful for candidate discovery,
never trustworthy as the evidence itself. A rigorous pass against 44 of its
candidates this session found a **27% verified-publishable rate**. Trusting
its summaries directly, without independently fetching the real source it
claims to cite, would have published wrong funding figures (UCL: claimed
£13,000, real £16,750), a deadline over a year stale (UCL: claimed March
2026, real April 2027), and at least 16 candidates whose only "official"
source was actually the same third-party job board
(`jobs.rwfm.tamu.edu`) relabeled as if it belonged to whichever university
the position happened to sit at.

## The auto-publish bar

All of the following must hold. Any one missing means the candidate is not
confidently publishable, full stop - it goes to the "stays open" pile, not a
best-effort publish.

1. **A real official source was actually fetched and read**, not just cited.
   The aggregator naming a `.edu`/`.ac.uk` domain is not evidence; reading
   that page is. (UCL Mathematics, Arkansas Monticello, Mississippi,
   Manchester Bicentenary, Ferguson/UEA all failed here in different ways -
   see "Failure patterns" below.)
2. **Every asserted fact is directly stated on that real page**, never
   inferred, never carried over from the aggregator when the real page is
   silent on it. Hornby's £15,500 figure and King's College's specific field
   list were both aggregator claims not corroborated by the real page - only
   the corroborated facts were published, not the invented ones.
3. **`public_status` is chosen conservatively from the evidence actually
   found**, never guessed toward "open":
   - `open_verified` only when the real source explicitly confirms current
     acceptance (Hornby: "now open"; Westminster: live deadline, not
     lapsed).
   - `expected_to_reopen` for a confirmed *recurring* scheme whose current
     cycle has closed - either an explicit statement ("operates annually,"
     Bristol) or a government/consortium scheme's own structure implying
     recurrence (Commonwealth Shared Scholarships' 2026/27→2027/28 naming).
   - `status_unknown` when recurrence itself isn't evidenced.
4. **No taxonomy-forcing.** `field_mode=unknown` when the field doesn't
   cleanly map to the two real field codes (`public_health`,
   `computer_science`) - true for nearly everything checked this session,
   and that's fine, it's honest. `destinations` limited to the five actually
   supported (`CA`, `GB`, `US`, `DE`, `FI`); an Erasmus Mundus-style
   multi-country consortium only counts if the applicant's actual study
   country is *guaranteed* to be one of those five, not merely possible.
5. **`origin_mode` chosen honestly, with `eligibility_note` for what it
   can't represent.** `restricted` only with a real, independently-resolved
   enumerable list (never guessed from memory - see "Country-list
   resolution" below). `unrestricted` only when the source states no
   restriction, not merely silence. When a real restriction exists that
   doesn't fit an allow-list - an exclude-one rule ("not UK nationals":
   Bristol, Warwick), an immigration/residency status rather than
   nationality (Westminster's asylum-seeker/refugee restriction) - use
   `origin_mode=unknown` plus a plain-language `eligibility_note`, so the
   restriction is still visible to a searcher rather than silently dropped
   or falsely asserted as open.
6. **`award_type` reflects what the award actually is**, not what
   ScholarshipRegion calls it. A lab's paid research assistantship
   (Maine) is `assistantship`, not `scholarship`; a UK doctoral-funding
   consortium (SENSS) is `studentship`; an academic-community fellowship
   (Washington's McDonnell Academy) is `fellowship`. Every published record
   carries one of `scholarship` / `fellowship` / `assistantship` /
   `studentship` / `grant` - required at approval, not optional.

## The auto-reject bar

Objective, independently-verifiable facts only - never a subjective
"evidence feels thin" call:

- The cited official URL is a genuine dead link (404), with no working
  alternative found.
- The cited "official" source is not an institution at all - a job board,
  a personal faculty email, a Gmail address.
- The named award does not appear anywhere on the real official page that
  *was* found and fetched (Manchester Bicentenary, Illinois Graduate,
  Northern Illinois - a real domain confirmed, but the specific claimed
  award simply isn't there).
- The listing isn't a distinct institutional award at all (the generic
  "NOW OPEN: Commonwealth Shared Scholarship" post, not tied to one
  university, doesn't fit the provider/scholarship schema).

## Everything else stays open

Lapsed deadlines with no confirmed next cycle. Real sources that are only
thin directories, not a specific award's own page (Cambridge Trust). A
scheme whose 2026 cohort was explicitly cancelled with only an "expected"
future date (Erasmus Mundus PROMISE). A candidate whose verification was
skipped for time, not evidence (an ambiguous verdict must say so explicitly
- see King's College below). None of these get force-published, and none
get force-rejected either; they're left open with the specific blocking
reason recorded, for a human (or a future automated `prepare_review` job -
see below) to resolve with more evidence, not more guessing.

**A verdict that skipped verification must say so.** One batch's fork
explicitly reported it did not independently fetch King's College's page,
reasoning from a sibling candidate's pattern instead. That verdict was
treated as "not yet verified," not as evidence either way - it was checked
separately before any decision was made. Confidence never transfers between
candidates just because they look similar.

## Country-list resolution

Two restrictions this session needed an enumerable country list neither the
aggregator nor the university page provided in full: Hornby's OECD DAC
List of ODA Recipients, and the Commonwealth Scholarship Commission's own
eligible-country list (used for UCL, King's College, and Cranfield's
Commonwealth Shared Scholarships - the same UK government scheme, so
resolved once and reused, not re-derived three times). Both were fetched
from their real, authoritative primary source (`oecd.org`,
`cscuk.fcdo.gov.uk`) and matched against the mirrored country vocabulary
**programmatically** (exact-name matching against `countries.display_name`,
with a short, explicit alias table for ISO-official-name divergences),
never transcribed by hand into the `origins` list. A name that fails to
resolve (Kosovo, against our ISO-based mirror) is reported and excluded,
not guessed at.

**Two similarly-named classifications are not interchangeable.**
Göttingen's DAAD scholarship restricts to DAAD's own "developing and
newly-industrialised countries" list - a different classification from the
OECD DAC list, despite the superficial similarity. It was left
`origin_mode=unknown` rather than reusing the DAC list, because reusing it
would have been a real factual substitution, not a shortcut.

## Failure patterns worth recognizing early

- **The job-board tell**: `jobs.rwfm.tamu.edu` (Texas A&M's wildlife/
  fisheries recruitment board) appeared as the "official source" for 9+
  candidates spanning multiple, unrelated universities - Arkansas
  Monticello, Mississippi, Georgia Southern, Texas Tech, Idaho (x2), New
  Mexico State, Eastern Illinois, Louisiana State, Delaware. Recognizing
  this single URL pattern flags a large fraction of the backlog without a
  full fetch-and-cross-check pass.
- **The "real domain, absent award" tell**: a domain being genuinely
  institutional is necessary but not sufficient - Manchester Bicentenary,
  Illinois Graduate, and Northern Illinois's "scholarship" all resolved to
  real university pages that simply didn't contain the named award.
- **Duplicate discoveries**: the same University of Delaware listing
  appeared as two separate `review_task_id`s pointing at identical
  title/URL - a real deduplication gap in ingestion, not a verification
  problem, worth fixing independently.

## Future automation

None of this should stay a manual, one-session process. In rough order of
scope:

1. **Upgrade `extract_candidate`** (already a real job kind, currently a
   deterministic regex/keyword extractor - see `domain/extraction.py`) to
   call a real LLM for extraction instead. This is the smallest step: it
   only extracts and explains, per the stated automation boundary ("AI may
   extract structured candidate facts and explain deterministic matches").
   It needs a provider/API key/cost decision, not a policy decision -
   record that decision here once made.
2. **Build `prepare_review`** (also an already-reserved job kind with no
   handler) to run the *full* process this document describes - fetch the
   cited source, find and fetch the real official page, cross-check every
   claim, resolve country lists programmatically, apply the bars above -
   and attach the result as a **drafted, not executed** recommendation on
   the `ReviewTask` (proposed facts, proposed `award_type`, a verdict of
   confident-pass/ambiguous/reject, and the reasoning trail). A human
   reviewer then confirms or edits in one action, rather than starting from
   raw prose each time. This is the highest-leverage next step and does
   not cross the automation boundary: it explains and drafts, a human still
   decides and publishes.
3. **Only after (2) has run against real volume with a real track record**
   (proposals reviewed, percentage accepted unchanged vs. corrected vs.
   rejected) - revisit whether a scoped, high-confidence slice should skip
   the human confirmation click too. Not before; a single afternoon's
   manual track record, however careful, is not enough evidence to justify
   permanent unsupervised production automation.

The bars in this document (auto-publish, auto-reject, "stays open") are the
literal logic (2) should enforce in code - not a vibe for an LLM to
approximate, a checklist it must satisfy before a draft is even offered as
confident.
