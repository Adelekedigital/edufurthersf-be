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

**Finland-doctorate / Canada-federal** (2026-09-05) - researched per the
[50-profile coverage test](coverage-test-50-profile-2026-09-05.md)'s
recommendation to prioritize these over more GB volume; **not pursued
further, documented rather than silently dropped**:

- *Finland*: the gap is structural, not a sourcing failure. Aalto
  University's own funding page (fetched directly) states doctoral funding
  is "employment-based... work contract(s) as an employed doctoral
  researcher," not a scholarship - named third-party grants that do exist
  (Kordelin, Wihuri) are broad Finnish foundations, not international-student
  targeted schemes. EDUFI Fellowships, the one centralized government award
  that did fit the "scholarship" shape, was discontinued in October 2025
  (page now 404s). Finland doctoral funding maps onto paid employment
  (`award_type="assistantship"`), not a recurring named scheme - a
  fundamentally different, much higher-churn sourcing pattern (one-off
  Euraxess.fi/department postings, not a stable page to verify against).
- *Canada*: the federal layer is likely already consolidated into CGRS-D
  (already landed). Vanier Canada Graduate Scholarships - the obvious next
  federal candidate - is itself discontinued: UBC's grad-school page states
  plainly it was "merged into the Canada Graduate Research Scholarship –
  Doctoral (CGRS-D) program as part of a tri-agency funding harmonization
  initiative," the same wave that likely absorbed the other legacy federal
  awards (Banting/Best, Bell, Bombardier CGS - not independently confirmed).
  Registering Vanier would have been a duplicate of an already-superseded
  program, the same trap as the CGRS-D duplicate resolved earlier this
  session. Remaining Canada depth is at the university/foundation level,
  where the catalogue already has reasonable coverage (UBC x2, Alberta,
  McGill, Killam, Trudeau, Arrell).

Net: no new `Source` registered for either gap. Revisit Finland only if the
product decides to source assistantship-style postings (a different pattern
entirely, not a scope decision to make lightly); revisit Canada only if a
genuinely new university/foundation candidate surfaces, not by re-checking
the now-defunct federal schemes.

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

## Update, 2026-09-12: Parse.bot marketplace, education-listing candidates

16 candidates were proposed for expanding beyond ScholarshipPortal/PhDScanner.
Every row below is **real, verified marketplace data** - pulled live via
`parse search` against the actual account (not brand-name guessing), so the
slug, endpoint count, and `source_url` are ground truth, not assumptions. Fit
is a rough first-pass read from that metadata alone; nothing here has had a
DAAD/CSC-style real-sample-pull verification yet - treat every "fit" call as
a prioritization signal for *which one to check next*, not a decision to
integrate.

| Candidate (as named) | Real marketplace listing | Endpoints | Fit | Why |
| --- | --- | --- | --- | --- |
| ScholarshipPortal API | `scholarshipportal-com-api` | 6 | **Already integrated** | This is the existing source - not a new addition. |
| — (not in the original 16, found alongside it) | `phdscanner-com-api` | 3 | **Already integrated** | Also existing - only 3 of its endpoints are currently synced; worth a follow-up check on whether more exist. |
| Mastersportal API | `mastersportal-com-api` | 1 | **High (~80%)** | Same StudyPortals network as the already-trusted ScholarshipPortal, masters-specific (matches a Finder degree level directly), strong EU/Finland presence - directly relevant to the documented Finland gap. Only 1 endpoint though - thin surface, verify what it actually returns before committing engineering time. |
| PhDportal API | `phdportal-com-api` | 2 | **High (~80%)** | Same trusted network, doctorate-specific - directly relevant to the Finland *doctoral* gap specifically (Finland's structural gap is doctoral funding, not masters). |
| Opportunity Desk API | `opportunitydesk-org-api` | 2 | **Medium-high (~65%)** | `source_url` resolves to the site's own "grants" category page - a good sign it's actually funding-relevant, not just general opportunities. Same Tier-C discovery-breadth bucket as the existing two sources. |
| Fastweb API | `fastweb-com-api` | 8 | **High for volume (~75%)** | One of the largest, most established US scholarship databases; richest endpoint surface of any pure-scholarship candidate found. Same geographic caveat as Scholarships.com: US-only, doesn't touch the Finland/GB skew. |
| CareerOneStop API (.org) | `careeronestop-org-api` | 2 | **Medium (~65%)** | `source_url` is literally CareerOneStop's own scholarship-finder tool page - confirmed genuinely scholarship-specific, not general career content. Only 2 endpoints (thin), US-only. |
| CareerOneStop API (.com) | `careeronestop-com-api` | 4 | **Low-medium (~50%)** | A *separate* listing from `.org` (confirmed real, not a duplicate) - `source_url` is just the bare homepage, so it's unverified whether these 4 endpoints are scholarship-specific or CareerOneStop's broader career/workforce content. Check before assuming it's the same shape as `.org`. |
| CollegeBoard API | `bigfuture-collegeboard-org-api` | 4 | **Medium (~60%)** | Actually BigFuture (College Board's search tool), not CollegeBoard generally. Historically an undergrad-admissions brand - worth confirming it has real *graduate*-level scholarship content before assuming fit, given Finder only covers masters/mba/doctorate. |
| US News API | `usnews-com-api` | 1 | **Medium (~55%)** | `source_url` confirms it's specifically the scholarships-search feature, not general rankings - but only 1 endpoint, very thin. Worth a quick check of what that one endpoint returns. |
| GradSchools API | `gradschools-com-api` | 6 | **Low-medium (~45%)** | A US grad-program directory, not primarily a scholarship database - may have some financial-aid content attached to program listings. US-only. |
| UCAS API | `ucas-com-api` | 8 | **Low-medium (~45%)** | Richest endpoint count among the ambiguous ones, but `source_url` is just the bare homepage - unclear if scholarship data is even modeled vs. general admissions data. Also GB-specific, and GB is *already* overrepresented per the catalog gap analysis - this would work against the stated Finland/Canada priority, not toward it. |
| TopUniversities API | `topuniversities-com-api` | 5 | **Low (~35%)** | QS rankings/profile site - scholarship content, if any, is likely secondary to rankings. |
| Times Higher Education API | `timeshighereducation-com-api` | 4 | **Low (~35%)** | Same profile as TopUniversities - rankings-first, not a scholarship database. |
| Hotcourses Abroad API | `hotcoursesabroad-com-api` | 2 | **Low (~25%)** | `source_url` resolves to a *rankings* page (`/study/rankings/hdi.html`), not a scholarship or funding page - the marketplace listing itself suggests this wraps country/ranking comparison data, not funding data. |
| TheGradCafe API | `thegradcafe-com-api` | 2 | **Low (~15%), not recommended** | Confirmed wrong data shape: GradCafe is a self-reported admissions-*results* tracker (who got accepted/rejected where), not a funding database. |
| ApplyBoard API | `id-applyboard-com-api` | 1 | **Very low (~10%), not recommended** | The only marketplace listing found is `id.applyboard.com` - their identity/login portal, not their program or scholarship catalog. ApplyBoard's actual catalog data doesn't appear to be exposed here. |
| Gov API (Turkiye) | `y-k-atlas-api` (YÖK Atlas, `yokatlas.yok.gov.tr`) | 5 | **Potentially high (~70-80%), but blocked** | Found it: Turkey's official Higher Education Council program atlas - a genuine government source (a real `authority_grade="A"` candidate, unlike every Tier-C aggregator above), not a random hit. **But Turkey ("TR") isn't in `SUPPORTED_DESTINATIONS` or `SEED_COUNTRIES`** (`src/app/domain/countries.py:16,20` - confirmed by reading the actual code) - it can't be used as a study-destination source until that's added, a separate small prerequisite change. Also unverified: whether YÖK Atlas actually models *scholarship/funding* data specifically, or just university/program listings - its name suggests the latter; worth checking before assuming it fills the funding-data role. |

**Bonus find, not in the original list:** `bachelorsportal-com-api` (2
endpoints) - same StudyPortals network as Mastersportal/PhDportal, but
undergraduate-only. Not applicable - Finder doesn't offer a `bachelors`
degree level.

**On the Turkey callout specifically:** confirmed, Turkey is missing from
both the destination list and the local origin-country seed. Worth its own
small decision independent of the YÖK Atlas question: is Turkey a market
worth adding coverage for at all, separate from whether this specific API is
the right way to source it once it is.

**Recommended next check, given all of the above:** Mastersportal and
PhDportal first (same trusted network already in production, directly
address the documented Finland gap) - a real sample pull against both,
matching the DAAD/CSC/ScholarshipPortal verification pattern already used in
this document, before committing to sync/integrate either.

## Update, 2026-09-12: Mastersportal confirmed, PhDportal ruled out

Real sample pull against both (`client.scholarships.search(destination_country=...)`
for Mastersportal across all seven supported destinations, `programme_summaries.search(query="scholarship")`
for PhDportal), not just brand-network reasoning:

**Mastersportal - confirmed, genuinely scholarship-shaped.** Real results
carry title, deadline, grant amount + currency, provider name, and
destination - e.g. `"Dr. Franco J. Vaccarino President's Scholarship" |
deadline='23 Jan 2027' | amount=42500 'CAD' | provider='University of
Guelph'`. Returned real results for all seven current destinations,
**including Turkey** (`"Tuition Fee Waivers", Eastern Mediterranean
University`) - useful the moment Turkey support ships. One real data-quality
note for whoever builds the connector: several "worldwide"/many-country
scholarships (Fulbright U.S. Student Program, a Blumenthal Performing Arts
award) appear identically across *every* destination's query - expected,
since a global scholarship legitimately matches any destination filter, but
it means the same award will be discovered repeatedly across destination
loops within one harvest run. The cross-source dedup fix already shipped
this session (`link_discovery`'s `normalized_identity_key` check) handles
this correctly - repeated discoveries of the same title collapse to one
review task rather than opening several.

**PhDportal - ruled out, wrong data shape.** Despite querying specifically
for `"scholarship"`, every one of 10 real results returned only
`tuition_fee_amount` / `tuition_fee_currency` / `tuition_fee_unit` - no
funding, grant, or scholarship field exists anywhere on the detail object
(checked every attribute containing "fund", "scholar", "grant", "tuition",
"fee", or "financ"). This is a PhD **program and tuition-cost** directory,
not a funding database - the "same trusted StudyPortals network as
ScholarshipPortal" reasoning that made this look like a strong candidate
doesn't hold for data shape, only for general site legitimacy. Removed from
the synced API set (`parse remove phdportal_com_api`) rather than left
half-integrated.

**Net**: build the Mastersportal harvest connector (same
`_harvest_parsebot`/`import_feed_records` pattern as the existing two
sources); do not build one for PhDportal. The Finland-doctoral gap this was
meant to help with remains open - Mastersportal is masters-focused, so it
doesn't close that specific gap either, only the general "more discovery
breadth, including Turkey" goal.
