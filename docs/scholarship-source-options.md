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
