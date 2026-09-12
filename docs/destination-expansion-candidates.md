# Destination expansion candidates

Researched 2026-09-12, per the user's direction to broaden destination
coverage globally - "not only Asia but other continents with top/well
ranked study destinations and university option with funding across the
globe... we need to do a better job to have the list of top study
destinations." This supersedes an earlier same-day quick pass (documented
only in chat, not persisted) with real per-country verification against
official sources. **Research only - no `SUPPORTED_DESTINATIONS` change is
made by this document.** Any destination added from this list still needs
the same "share a plan + checklist" step as any other build.

Current supported destinations: `CA`, `GB`, `US`, `DE`, `FI`, `AU`, `TR`.
**Australia is already supported** - it was named again in this round's
request but is not a new candidate.

## What "worth adding" means here

Matches the bar this project already applies elsewhere
(`docs/scholarship-source-options.md`, `docs/candidate-verification-standard.md`):
a candidate destination needs **both** (a) a real, currently-active
government or major-institutional funding program open to *international*
masters and/or PhD students specifically - Finder only supports
`masters`/`mba`/`doctorate`, so undergrad-only or domestic-only aid doesn't
count - **and** (b) genuine higher-education strength (globally-ranked
universities a searcher would actually look for). A country with only a
thin, narrow, or institution-specific program is named honestly as such,
not silently promoted to the same tier as a strong national scheme.

## Prioritized shortlist

Strongest, most defensible additions first - a real national program, real
global university reputation, broad eligibility:

1. **Japan** - MEXT (Monbukagakusho) Scholarship, masters + PhD, full
   tuition + stipend + airfare, via embassy recommendation (open broadly by
   nationality through the local Japanese embassy) or university
   recommendation. Official: `studyinjapan.go.jp`, `mext.go.jp`. Globally
   top-ranked universities (University of Tokyo, Kyoto University, Tokyo
   Institute of Technology).
2. **South Korea** - Global Korea Scholarship (GKS, formerly KGSP),
   administered by NIIED, ~2,000+ scholars/year from 155+ countries, masters
   + PhD, full tuition + stipend + airfare + Korean-language training.
3. **China** - Chinese Government Scholarship (CSC), Ministry of Education
   via the China Scholarship Council, 290+ participating universities,
   masters + PhD, full tuition + stipend + housing + insurance. Official:
   `campuschina.org` / `csc.edu.cn`.
4. **France** - Eiffel Excellence Scholarship, French Foreign Ministry via
   Campus France, masters (age ≤29) + PhD (age ≤35), €2,100/month stipend +
   services (does not cover tuition itself, but a real, well-funded
   flagship national scheme). Official: `campusfrance.org`.
5. **Saudi Arabia** - real and broader than it first looks. Two distinct
   layers, both verified directly:
   - A genuine **national** program: the Saudi Ministry of Education's
     inbound scholarship for international students at Saudi public
     universities, confirmed directly on `moe.gov.sa`
     (`/en/education/ResidentsAndvisitors/Pages/PublicUniversitiesScholarships.aspx`) -
     explicitly covers "Bachelor - Higher Diploma - Masters - PhD," age
     limits 30 (masters) / 35 (PhD), full/partial/paid-grant tiers, health
     care, housing, arrival grant, annual travel. (Careful: a *different*
     MOE page, `/en/education/highereducation/Pages/Scholarship.aspx`, is
     the outbound "Custodian of the Two Holy Mosques" program that funds
     *Saudi* citizens to study *abroad* - the opposite direction, and easy
     to confuse with the inbound one by URL alone.)
   - **KAUST** (King Abdullah University of Science and Technology) - a
     separate, institution-specific, extremely well-funded program:
     confirmed directly on `admissions.kaust.edu.sa`, "over 90% of admitted
     students receive full tuition support, a monthly stipend, housing,
     medical coverage, and relocation assistance," no nationality
     restriction found. KAUST is a strong, internationally-ranked
     research university, but this is one institution's funding, not the
     national scheme above - relevant to how a connector would be built
     (a direct `Source` for KAUST specifically, distinct from the
     national MOE program), not to whether Saudi Arabia belongs on the
     destination list at all.
6. **New Zealand** - Manaaki New Zealand Scholarships (MFAT), masters + PhD,
   full tuition + living allowance (~NZD 27,600/year) + airfare. **Caveat**:
   restricted to citizens of a listed set of ~100 "developing countries" -
   a real, meaningful eligibility gate (the same shape as the Commonwealth
   Shared Scholarships' country list, not a design flaw).

## Real, but narrower - PhD-only or institution-level, not a clean national masters+PhD scheme

- **Switzerland** - Swiss Government Excellence Scholarships (`admin.ch` /
  SBFI), CHF 2,450/month + tuition exemption. **PhD/postdoc only** - requires
  an already-completed master's, no masters-level government scholarship
  found under this scheme. ETH Zurich and EPFL are top-10-globally research
  universities.
- **Singapore** - SINGA (A\*STAR, jointly with NUS/NTU/SUTD/SMU/SIT), full
  PhD funding (S$2,200-2,700/month + fees). **PhD-only**, and scoped to
  Biomedical Sciences/Computing/Engineering/Physical Sciences.
- **Qatar** - real, but fragmented across institutions rather than one
  national body, verified directly against two official sources:
  - **Hamad Bin Khalifa University (HBKU)**, confirmed on `hbku.edu.qa/en/scholarship`:
    PhD gets a 100% tuition waiver, Master's gets a partial waiver (60-75%
    depending on program), both get a monthly stipend (PhD 9,000 QAR,
    Master's 7,000 QAR) plus one round-trip airfare. Real, but Master's is
    *partially*, not fully, funded, and this is Qatar Foundation/HBKU's own
    program, not a national scheme.
  - **Qatar University** also runs its own graduate scholarships (masters,
    PhD, PharmD across 29 masters/20 PhD programs, per `qu.edu.qa`), a
    second, independently-run institutional program.
  - Net: real funding exists and is worth pursuing, but as direct
    institution-level `Source`s (the same DAAD/CSC/KAUST pattern), not as
    one clean national program the way Japan/Korea/China/France are.
- **Saudi/Qatar/UAE all share this same shape**: real, well-funded, but
  the strongest individual offers (KAUST, HBKU, Khalifa University/MBZUAI -
  UAE's candidates from the earlier pass) are single-institution programs,
  not a national scholarship body. That's a reason to pursue them as direct
  `Source`s once a country is added, not a reason to exclude the destination
  - Saudi Arabia clears the bar independently via its real MOE national
    program either way.

## Rejected or ruled out - checked and found wanting

- **Norway** - real, current, and negative: not a scholarship-friendly
  destination right now, despite it being commonly assumed one.
  - Norway's historical government-funded Quota Scheme was scrapped in
    2016. Its replacements have also wound down: NORPART is being phased
    out, and NORSTIP (introduced in 2023 specifically to offset new tuition
    fees) was cancelled from the 2026 budget. Multiple independent sources
    converge on the same conclusion: there is currently no Norwegian
    government scholarship open to individual international applicants.
  - Since the 2023/24 academic year, non-EU/EEA students pay real tuition
    (NOK 130,000-340,000/year) at Norwegian public universities - the
    long-standing "Norway is tuition-free" reputation no longer holds for
    non-EU/EEA masters students.
  - PhD funding in Norway is **structurally employment-based**: doctoral
    candidates are hired as paid university employees (positions posted on
    `jobbnorge.no`), not scholarship recipients - tuition-exempt, but not a
    "scholarship" in Finder's sense. This is the exact same structural
    pattern already documented for Finland's doctoral gap
    (`docs/scholarship-source-options.md`'s 2026-09-05 update) - not a
    one-off Finland quirk, but a real Nordic-region pattern (see Sweden,
    below, too).
  - Net: do not add. Revisit only if a real, currently-active Norwegian
    government scheme reappears - not one of the discontinued ones under a
    new name.
- **Sweden** - real program exists, but narrow, and the same Nordic PhD
  pattern as Norway/Finland applies:
  - Swedish Institute Scholarships for Global Professionals (SISGP) is
    real and government-backed (the Swedish Institute is a Swedish
    government agency), but **masters-only**, restricted to a specific list
    of ~34 eligible countries (mostly designated developing economies -
    Bangladesh, Kenya, Vietnam, and similar), and requires 3,000+ hours of
    prior work experience - a career-professional program, not a
    fresh-graduate one. (Direct fetch of the official `si.se` scholarship
    page was blocked, 403 - the country list and eligibility details above
    are corroborated across multiple independent sources describing the
    same specific figures, not a single unverified claim.)
  - PhD funding in Sweden is also **structurally employment-based** -
    doctoral students are salaried university employees (33,000+ SEK/month)
    with standard employment benefits, not scholarship recipients. Same
    Nordic pattern as Norway and Finland.
  - Net: a real but narrow masters-only scheme, on a destination whose PhD
    funding doesn't fit Finder's scholarship shape at all. Weaker than
    every candidate in the shortlist above; not recommended for now.
- **Netherlands** - the national NL Scholarship (formerly Holland
  Scholarship, Nuffic/Dutch Ministry of Education) is real but thin: only
  €5,000, one year, not full tuition. Real per-university schemes exist
  (Orange Tulip, Amsterdam Merit) but there's no single strong flagship -
  would need per-university curation (the Göttingen/McGill pattern), not a
  clean national-scheme addition.
- **Ireland** - the Government of Ireland International Education
  Scholarships (`hea.ie`) are genuinely well-funded (full fee waiver +
  €10,000 stipend, masters + PhD) but tiny in scale: only 60 awards/year
  nationwide. Real, but orders of magnitude smaller than every shortlisted
  candidate.
- **UAE** - Khalifa University and MBZUAI both offer genuinely
  comprehensive, fully-funded graduate packages (AED 15,500-20,000/month +
  full tuition), verified in an earlier pass. But both are
  **institution-linked scholarships at 1-2 specific universities**, not a
  national scholarship body - the same shape as KAUST/HBKU above. MBZUAI is
  also narrowly AI-only. Not a clean destination-level candidate on its
  own; would be a direct-`Source` addition at most, the same as KAUST/HBKU,
  if the destination is added for other reasons.
- **Latin America and Africa** - no government-run graduate scholarship
  program was found that is both (a) open broadly to international
  students at scale and (b) attached to globally top-ranked universities,
  at a level comparable to the shortlist above. This was **not** an
  exhaustive per-country sweep (South Africa, Brazil, and Mexico
  specifically were not individually verified) - flagged as a real gap in
  this research, not a confirmed "nothing exists." Inbound funded programs
  in these regions tend to be bilateral/donor-funded rather than attached
  to one national body a `Source` could point at.
- **Qatar/Saudi outbound-vs-inbound trap** - worth naming explicitly since
  it nearly caused a wrong finding during this research: several official
  Saudi MOE pages describe the Custodian of the Two Holy Mosques program,
  which funds *Saudi citizens* to study *abroad* - the opposite direction
  from what this document is evaluating. Anyone extending this research
  later should confirm a "government scholarship" page is describing
  inbound funding for international students, not a country's own
  citizens studying elsewhere, before citing it as evidence.

## Net

Five clear, well-grounded additions - Japan, South Korea, China, France,
Saudi Arabia - each backed by a real, currently-active national program
verified against an official source, at globally-recognized universities.
New Zealand is a sixth strong candidate with one real, named eligibility
caveat (restricted-country list). Switzerland and Singapore are real but
PhD-only. Qatar is real but fragmented across institutions rather than one
national scheme. Norway is a **rejected** candidate this round - both its
national scholarship layer and its "tuition-free" reputation have
materially eroded since 2023, and its PhD funding is structurally the same
non-scholarship shape as Finland's already-documented gap. Sweden is real
but narrow (masters-only, restricted-country, work-experience-gated) with
the same Nordic employment-based PhD pattern.
