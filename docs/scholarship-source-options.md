# Scholarship data source options

Researched 2026-09-04, after this session's verification pass found
ScholarshipRegion (the current sole feed) converting only ~27% of
candidates into publishable records. Checked against the existing planning
pack first (`README.md` and the `Edufurther-Scholarship-Finder-v1.2.zip` at
`.codex/.chatgpt-projects/.../docs/scholarship-finder/`) - both contain the
same 9 files, and neither names a specific scholarship-data API vendor.
This is new research, not a duplication of an existing decision.

## The goal

A mix of sources, each covering the countries it's actually strong in, so
sourcing, updating, and populating scholarships doesn't depend on one
unreliable aggregator. Our supported destinations are `CA`, `GB`, `US`,
`DE`, `FI`.

## What was found

**ScholarshipAPI.com** - a genuine first-party product: documented REST
API, daily automated ingestion from 50+ university sites, structured
fields (name, university, amount, currency, status, deadline; paid tiers
add citizenship requirements and geographic eligibility), free tier at 100
req/day. This is the best-*built* option checked. **Its live coverage is
Australia and New Zealand only** - Canada, US, and Europe are listed as
"expanding soon" with no date given. Zero overlap with our five supported
destinations today.

**"ScholarshipPortal API" and "Scholarships.com API"** (both surfaced via a
marketplace called Parse.bot) - **neither is an official first-party API.**
Digging past the marketplace listing: Scholarships.com "does not publish a
documented public developer API" at all, and no independent evidence was
found that ScholarshipPortal (StudyPortals) sanctions this repackaging
either. Parse.bot appears to be a third party scraping and reselling access
to these sites' public directories, not a partnership either site has
publicly confirmed. That doesn't mean the data is unusable, but it does
mean the reliability and ToS-legitimacy of *both* rests on one intermediary
neither original site has vouched for, not on two independent
relationships. ScholarshipPortal's claimed coverage is the broadest of
everything checked (global, StudyPortals' own directory), which is
genuinely why it looked promising - that claim just isn't independently
confirmed as legitimate.

**DAAD** (Germany's own national scholarship body, already a real source
in our data via the Göttingen candidate) - has a real, actively-maintained
scholarship database, but no documented public API or open-data access was
found. Direct outreach to DAAD would be needed to learn whether one exists
that isn't publicly documented.

**Scholarships.com specifically** - even setting the Parse.bot question
aside, its own coverage is US-only by design; it wouldn't help with
`GB`/`DE`/`FI`/`CA` regardless of access method.

## Honest bottom line

There is no clean, already-available mix of independently-legitimate APIs
that covers all five supported destinations today. The best-built option
doesn't serve our countries yet; the options that claim to are unverified
third-party repackaging. This isn't the "here are three plug-and-play
choices" answer that was hoped for - it's what a real check actually found.

## Recommended next steps, in order

1. **Contact ScholarshipAPI.com directly.** Their own pricing page offers
   Enterprise customers "early access to new country data as it becomes
   available" - worth asking now whether Canada/US/Europe have a real
   timeline, rather than waiting to discover it later.
2. **Confirm Parse.bot's actual data-sourcing legitimacy before relying on
   it** - a direct question to Parse.bot about their agreement with
   StudyPortals/Scholarships.com, not something resolvable from outside.
   If it checks out, ScholarshipPortal specifically is the strongest
   coverage fit found.
3. **Treat major national scholarship bodies as direct Tier A/B sources in
   the existing architecture, not as something waiting on a generic API.**
   DAAD (Germany), the Commonwealth Scholarship Commission (UK, already
   added as a `Source`-equivalent this session for the country-list
   resolution), Fulbright/EducationUSA-adjacent programmes (US) - these
   already publish their own real scholarship listings on real domains.
   The `Source`/`SourcePage` model already supports adding any of these
   directly with `authority_grade="A"` or `"B"`, no new integration needed
   beyond a normal `fetch_source_page`-style connector per site. This is
   closer to what this session's manual verification was already doing
   (reading each provider's own page directly) than to "wire in a
   third-party API," and doesn't depend on any vendor's roadmap.
4. **Keep ScholarshipRegion as the discovery-breadth source it's suited
   for** (Tier C, candidate discovery only, per the verification
   standard) while the above are pursued - its 27% hit rate is a real
   yield, not zero, and nothing above replaces it outright yet.

## Update, 2026-09-05: outcomes

**DAAD** - landed. Registered as a `Source` (`authority_grade="A"`), 11 real
programmes curated directly from `www2.daad.de`'s own database, verified,
approved and published (`data_scripts/daad_pilot_batch.csv`). Confirmed live
via real search queries against the deployed API.

**Commonwealth Scholarship Commission (UK)** - landed the same way. Registered
as a `Source` (`authority_grade="A"`), 3 real schemes verified directly from
`cscuk.fcdo.gov.uk` and published (`data_scripts/csc_pilot_batch.csv`):
Commonwealth PhD Scholarships (LDCs/vulnerable states, 17-country list),
Commonwealth Shared Scholarships (44-country list), Commonwealth Master's
Scholarships (43-country list - one country different from the Shared list,
kept independently resolved rather than reused). Two other real CSC schemes
(Professional/Academic Fellowships, Startup Fellowships) were deliberately
excluded: neither is a degree programme, so neither fits the platform's
masters/doctorate-only level taxonomy.

**Parse.bot / ScholarshipPortal / PhDScanner** - the legitimacy question from
above is now answered, not in the hoped-for direction: Parse.bot's own
marketplace listings self-describe both as "an independent, maintained REST
wrapper... not an official API from the source site." Both stay
`authority_grade="C"`, the same tier as ScholarshipRegion - useful for
discovery breadth, never evidence on their own. A real sample pull (not
marketing claims) found ScholarshipPortal returns hits for all five
destinations but with real cross-country leakage/duplicate noise; PhDScanner
returns genuinely high-quality funded-PhD postings for `GB`/`DE`/`FI` but
**zero results for `CA`/`US`** - a real gap, not a rounding error. A
scheduled `harvest_parsebot` connector (weekly, both APIs, all five
destinations, two independent kill switches) is built and quality-gate-clean
(PR #15), not yet deployed.

**Fulbright / EducationUSA** - researched, not landed; documented here rather
than silently dropped. Two separate problems, not one:

- *Structural*: the Foreign Student Program isn't one unified scheme the way
  DAAD or CSC are. It's ~160 separate country programs, each administered
  independently by a bi-national Fulbright Commission or US Embassy, each
  with its own deadline and process. There is no single "Fulbright" page to
  verify the way DAAD's or CSC's schemes have one - it would need to be
  handled as N independently-verified per-country candidates, not one.
- *Access*: every `*.usembassy.gov` page tried (Tunisia, Sierra Leone, Chad,
  Kenya) returned a hard block (403 or connection reset) - a real,
  consistent bot-mitigation wall, not a transient failure worth retrying or
  routing around. `foreign.fulbrightonline.org` (the general hub) is
  fetchable and confirms real facts - Master's/Doctorate levels, J-1 visa
  sponsorship, health benefits, embassy-administered - but doesn't expose
  concrete per-country deadlines in static-fetchable form (rendered
  per-country dynamically).

Net: enough confirmed to register Fulbright as a legitimate `Source`
(`authority_grade="A"`) in the future, not enough independently-verified,
dated facts to responsibly publish even one specific country's cycle today.
Revisit if: (a) someone with normal browser access pastes a specific
country's embassy-page content for verification, or (b) a non-embassy
mirror of country-specific deadlines is found and independently confirmed.

**Other candidates raised but not yet researched** (Mastercard Foundation,
Chevening, Rhodes, McGill, and similar) - see the "Other direct-source
candidates" note below for an initial scoping pass; none of these have been
independently verified yet, so none should be treated as confirmed.

## Other direct-source candidates (scoped, not yet verified)

Quick structural assessment only - none of these have had a DAAD/CSC-style
verification pass yet, so treat every claim below as unconfirmed until a real
fetch backs it up:

- **Chevening** (`chevening.org`) - looks like the best-shaped next
  candidate: a single UK-government-funded scheme with one centralized
  application site (unlike Fulbright), and scholarships.region data already
  surfaced real Chevening listings this session, so it's a known-real award.
  Likely has one global deadline and an enumerable eligible-country list, the
  same shape DAAD and CSC had. Worth verifying next.
- **Rhodes Scholarship** (`rhodeshouse.ox.ac.uk`) - centrally documented on
  one site even though selection is split into regional "constituencies"
  (unlike Fulbright's scattered embassy pages) - each constituency's
  deadline/quota is listed on the same domain. Plausibly tractable, not yet
  checked for bot-blocking the way `.usembassy.gov` was.
- **Mastercard Foundation Scholars Program** - structurally different from
  DAAD/CSC/Chevening/Rhodes: it's a funding *brand* that appears across many
  independently-run university programmes (Cambridge, Edinburgh, CMU-Africa,
  ASU, and others already seen as distinct listings in the ScholarshipRegion
  data this session), not one unified scheme with its own application portal.
  Registering "Mastercard Foundation" as a single `Source` the way DAAD is
  one wouldn't be accurate - each university's own Mastercard-funded program
  page would need its own verification pass, closer to how individual
  ScholarshipRegion candidates already get verified than to a new Source.
- **McGill University** - a single institution, not a national/foundation
  body spanning many programmes the way DAAD/CSC are. Adding McGill-specific
  scholarships is possible but is provider-level candidate verification (like
  the University of Maine example earlier this session), not a new
  direct-source integration - different scale of effort than this document
  is about.
