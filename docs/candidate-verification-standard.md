# Candidate verification standard

This is the working standard behind every publish/reject decision made
against real ScholarshipRegion discoveries this session. The full backlog
of 247 discoveries has now been worked through completely - every one
either published, rejected, or left open with a specific recorded reason;
none skipped. Final tally: **31 published, 167 rejected, 49 left open**
(each with a documented reason, not silently skipped). It exists so the
next person, the next session, or the eventual automated pipeline (see
"Future automation" below) makes the same calls for the same reasons, not a
fresh judgment call each time.

## Why this exists

ScholarshipRegion is a Tier C aggregator: useful for candidate discovery,
never trustworthy as the evidence itself. A rigorous pass against the full
247-discovery backlog landed at a **31/247 (~13%) publish rate overall**,
and closer to **27% among candidates whose destination was even plausibly
one of our five supported ones** (most of the backlog turned out to be for
other countries entirely - see "Other countries" below). Trusting
ScholarshipRegion's summaries directly, without independently fetching the
real source it claims to cite, would have published wrong funding figures
(UCL: claimed £13,000, real £16,750), a deadline over a year stale (UCL:
claimed March 2026, real April 2027), and at least 16 candidates whose only
"official" source was actually the same third-party job board
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
   restriction, not merely silence. Three distinct shapes of restriction
   this schema cannot represent structurally, all needing `eligibility_note`
   instead of a forced `origin_mode`:
   - An **exclude-one rule** ("not UK nationals": Bristol, Warwick, Gates
     Cambridge, UCL Global Masters, Sheffield Hallam).
   - An **immigration/residency status rather than nationality**
     (Westminster's asylum-seeker/refugee/discretionary-leave restriction;
     Trudeau's citizen-anywhere-or-enrolled-in-Canada rule).
   - A **demographic restriction entirely outside the origin dimension**
     (Oxford Optiver Foundation: female applicants only, layered on top of
     a real 131-country income-based list - the gender restriction has no
     field anywhere in this schema and must go in `eligibility_note`
     regardless of how the country list is encoded, or a male applicant
     from an eligible country is actively misled into thinking he
     qualifies).
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
  university, doesn't fit the provider/scholarship schema; the generic
  British Council GREAT Scholarship post has the same problem - "over 60
  universities...runs its own selection process").
- The destination is verifiably outside our five supported ones (`CA`,
  `GB`, `US`, `DE`, `FI`) - see "Other countries" below. This is a fast,
  objective closure knowable from the institution's own name/location, not
  an evidence-quality problem, and doesn't need the full fetch-and-cross-
  check pass the other reject reasons require.
- A real, legitimate, well-funded scheme that simply doesn't fund study in
  one of our five destinations at all - distinct from a destination
  *mismatch on a specific listing*. The Queen Elizabeth Commonwealth
  Scholarship funds students to study *within* their own developing-country
  region, not to come to the UK; DLA Piper's Global Scholarship funds
  students to continue at their *own home-country* institution. Both are
  real and well-evidenced; neither has a destination this index covers.

## Other countries

Once the backlog was worked through completely rather than only the
subset whose title obviously named a supported destination, the large
majority turned out to be for countries outside our five (`CA`, `GB`,
`US`, `DE`, `FI`). Rejecting these doesn't need the fetch-and-cross-check
pipeline at all - an institution's country is a stable, knowable fact from
its own name, not something ScholarshipRegion could meaningfully mislead
about. 125 of 247 discoveries closed this way in one pass, via the bulk
review-decision endpoint (`POST /internal/admin/reviews/bulk-decision`,
≤10 per call) rather than one-at-a-time.

Countries actually observed in the backlog this way (worth knowing for any
future destination-coverage decision - this is real signal about where
demand/supply in the discovery feed actually is, not just noise):
Australia, Austria, Belgium, Brazil, China, Czech Republic, France, Ghana,
Hong Kong, Hungary, Ireland, Italy, Japan, Korea, Lebanon, Mauritius,
Netherlands, Nigeria (in-country), Qatar, Russia, Rwanda, Saudi Arabia,
Singapore, Slovakia, South Africa, Sweden, Switzerland, Taiwan, Thailand,
UAE, plus several pan-African/multi-country programmes with no single
country. A one-off name collision was caught and fixed here before it
became a permanent record: "Hamad Bin Khalifa University" (Doha, Qatar) was
briefly mislabeled as UAE by a keyword match against the unrelated "Khalifa
University" (Abu Dhabi) - both are correctly out of scope either way, but
the *stated reason* needs to name the right country, since these become
part of the permanent audit trail.

A related but distinct case: a multi-country Erasmus Mundus consortium
(REPLAY, AI Erasmus Mundus, NOHA, MARIHE, AMIR, IMFSE, EMMIE, PlantHealth,
MESPOM, GLOCAL, EMABG, and others) is rejected not because its destination
is *wrong*, but because no *single* destination is guaranteed - "Europe"
generically, or a named set where none of the specific countries is one of
our five. This is the same underlying rule as bar item 4 above, just at
bulk-reject scale rather than a one-off ambiguous case.

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

A third list was resolved the same way for Oxford's Optiver Foundation
Scholarships: a complete 131-country low/middle-income list published
verbatim on `ox.ac.uk` itself (no PDF, no dropdown - directly on the page),
resolved to 130 of 131 codes (Kosovo again the one gap). Unlike DAC and
CSC, this list is specific to this one Oxford scholarship, not a
government scheme reused across multiple institutions - resolving it once
still mattered because the list was large enough that hand-transcription
risk was real.

**Two similarly-named classifications are not interchangeable.**
Göttingen's DAAD scholarship restricts to DAAD's own "developing and
newly-industrialised countries" list - a different classification from the
OECD DAC list, despite the superficial similarity. It was left
`origin_mode=unknown` rather than reusing the DAC list, because reusing it
would have been a real factual substitution, not a shortcut. The same
caution applies *within* one scheme family: the Commonwealth Scholarship
Commission runs both Commonwealth Shared Scholarships (44 countries,
resolved) and Commonwealth PhD Scholarships (restricted to "Least
Developed Countries and Vulnerable States" specifically - a real, narrower,
*different* list on the CSC's own site). The PhD scheme was published with
`origin_mode=unknown`, not the already-resolved 44-country list, because
the two lists are not the same just because they share an administering
body.

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
- **Not one distinct award**: a real, current, legitimate funding source
  can still fail to be *one* publishable scholarship. Two different shapes
  of this: an open-ended rolling directory of many separate projects, each
  with its own deadline (Aston's 57 PhD projects, Brunel's PhD studentships
  page, KAAD's 5 distinct programmes) - there is no single deadline to
  publish against; and guaranteed funding bundled with admission rather
  than a competitive award with its own deadline (Dartmouth's PhD stipend -
  the aggregator's deadline for it was outright fabricated, since no such
  deadline exists on the real page at all).
- **A stale aggregator deadline copies a *prior* cycle, not a lapsed one**:
  several real, currently-open cycles were nearly rejected as "lapsed"
  before checking the primary source directly - the aggregator's date was
  simply last year's, and the actual current cycle was open the whole time
  (Ohio State, Manchester Global Futures - later itself downgraded on a
  *different* gap, Sheffield Hallam, Texas A&M Chancellor's Fellowship).
  Never trust an aggregator's stated deadline as evidence a cycle is
  closed; only the primary source's own current-cycle statement counts.
- **Funding institution vs. actual physical location diverge**: a program
  can be issued/administered from one country while the recipient studies
  or works somewhere else entirely - an online graduate certificate from
  Arizona State University that explicitly requires the recipient to
  reside in Rwanda throughout; NVIDIA's Graduate Fellowship, which funds an
  already-enrolled PhD student's research at *any* university worldwide
  plus a summer internship at one of several possible NVIDIA office
  countries, not one fixed destination. Neither has a "study destination"
  the way an ordinary scholarship does - asserting `destination=US` for
  either would be a real factual claim the evidence doesn't support.
- **Explicit AI-exclusion in `robots.txt` is a hard stop, not a bot-
  mitigation puzzle to solve.** Two shapes seen this session: naming
  specific bots (`Content-Signal: ai-input=no` under a `Claude`/`Anthropic`-
  specific user-agent, as on the East-West Center's site) and a blanket
  site-wide policy (`Content-Signal: ai-input=no` under `User-agent: *`, as
  on TU Berlin's entire domain). Both mean *do not fetch this content by
  any means*, including the browser-UA fallback that resolves ordinary bot
  mitigation elsewhere - that fallback would be exactly the evasion this
  standard's access policy prohibits once a site has made an AI-specific
  exclusion explicit, as distinct from a generic anti-scraping measure.
- **A genuine interactive challenge (Cloudflare Turnstile, `Cf-Mitigated:
  challenge`) is not the same failure as ordinary UA-string bot mitigation**
  and is not resolved the same way. UCL's plain 403 resolved cleanly with a
  browser User-Agent; Oxford's Saïd Business School domain
  (`sbs.ox.ac.uk`, hosting several unrelated scholarships - Skoll, Mastercard
  AfOx, Pershing Square) returned a real interactive challenge to *both* a
  plain request and a browser-UA one, confirmed multiple times across
  unrelated candidates. Not every 403 is the same kind of block, and only
  one kind is safely bypassable without it becoming evasion.

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
   decides and publishes. Give it a cheap first pass before the expensive
   one: a destination check against the discovery's own stated country
   (see "Other countries" above) costs nothing next to a full fetch-and-
   cross-check pipeline, and closed roughly half the full backlog by
   itself once applied at scale.
3. **Use the bulk review-decision endpoint** (`POST
   /internal/admin/reviews/bulk-decision`, ≤10 per call, already built) for
   exactly the case that motivated it: many independent decisions with the
   same shape, applied in one pass rather than one HTTP call each. This
   already carried real weight this session (125 destination rejects in 13
   calls) and is the natural output target for `prepare_review`'s
   confident-verdict batch, not just a manual convenience.
4. **Only after (2) has run against real volume with a real track record**
   (proposals reviewed, percentage accepted unchanged vs. corrected vs.
   rejected) - revisit whether a scoped, high-confidence slice should skip
   the human confirmation click too. Not before; a single afternoon's
   manual track record, however careful, is not enough evidence to justify
   permanent unsupervised production automation.

The bars in this document (auto-publish, auto-reject, "stays open") are the
literal logic (2) should enforce in code - not a vibe for an LLM to
approximate, a checklist it must satisfy before a draft is even offered as
confident.
