# EU / Germany job-source research

Research only — no code was written or modified. This surveys free, ToS-compliant job-posting
APIs for the German/European market as candidate discovery sources alongside the already-built
Greenhouse/Lever ATS integration (`scraper/ats_client.py`) and the Playwright scraper fallback
(section 3 of the design plan). Each section is self-contained: read one source's section and you
should know (a) whether it's worth integrating and (b) roughly how, without reading the others.

All "live test" results below were captured by making real HTTP calls on **2026-10-04**. API
responses can and will change — treat the example payloads as shape references, not permanent
contracts.

Target `JobPosting` shape (from `storage/schemas.py`, section 1 of the design plan) every mapping
below is normalizing onto:

```python
class JobPosting(TypedDict):
    job_id: str; company: str; title: str; location: str; url: str; description: str
    source: Literal["greenhouse", "lever", "workday", "scraper"]   # needs a new value per source added
    ats_job_id: Optional[str]; department: Optional[str]; posted_at: Optional[str]
    discovered_at: str; last_seen_at: str; status: Literal["new", "seen", "closed"]; raw: Optional[dict]
    location_lat: Optional[float]; location_lng: Optional[float]
    is_remote: Optional[bool]
```

Note up front: `source`'s `Literal` will need a new member for every source actually wired in
(e.g. `"arbeitsagentur"`, `"arbeitnow"`, `"adzuna"`, `"jobicy"`) — a one-line schema change, flagged
here rather than made, since this task is documentation only.

---

## Summary table

| Source | Auth | Free? | Live-tested? | Legal friction | Verdict |
|---|---|---|---|---|---|
| Bundesagentur für Arbeit (Jobsuche API) | Static public API key | Yes, no signup | Yes, works | Unofficial/undocumented by BA itself, but widely relied upon, no restrictive ToS found | **Top pick** |
| Arbeitnow | None | Yes, no signup | Yes, works | Simple attribution ask, "as-is" terms, revocable at will | **Top pick** |
| Adzuna (DE) | `app_id`+`app_key`, free signup | Yes, free tier | No (signup gate — see note) | Real ToS, but "personal research" explicitly permitted; redistribution/aggregation restricted | Good second-tier candidate |
| Jobicy | None | Yes, no signup | Yes, works | Fair-use attribution + canonical-URL rules; mostly remote-with-geo-eligibility, not DE-located jobs | Usable, narrower fit |
| Jooble | Free key via contact form | Yes, but gated by a request form | No (requires submitting contact info) | No published ToS/rate limits; form asks for company name, implying commercial orientation | Low priority |
| EURES | Officially restricted to recognized "EURES partner organisations"; unofficial reverse-engineered endpoints exist | Not legally open | No (ToS-blocked, see note) | Explicitly restricted to partner orgs by the EU; using the reverse-engineered endpoint would violate portal ToS | **Avoid** |

---

## 1. Bundesagentur für Arbeit — Jobsuche API

**What it is:** The German Federal Employment Agency's job search backend, the same one powering
the official `arbeitsagentur.de` jobsuche site and mobile app. Not officially published/supported
as a third-party developer product, but openly documented and used by the community
(`bundesAPI/jobsuche-api` on GitHub) — in practice the most complete free source of German-market
listings available, including public-sector/Mittelstand postings that never show up on
Greenhouse/Lever.

**Auth:** A single static, publicly known API key, sent as a header:
```
X-API-Key: jobboerse-jobsuche
```
No signup, no per-developer key, nothing to register. This is the mobile app's embedded key,
exposed and documented by the community — it is **not an officially sanctioned developer key**,
which is the main legal caveat (see below).

**Rate limits:** None documented anywhere (official or community). In practice this is the same
backend the public-facing site/app uses, so it can presumably absorb normal search traffic, but
there's no SLA and the agency could change/kill the key at any time without notice since it isn't
an official product.

**ToS / legal notes:** The Bundesagentur für Arbeit does not publish terms of service for this API
because it doesn't officially offer it as an API — the README of the most popular community
wrapper (`bundesAPI/jobsuche-api`) says exactly this. Practical implications:
- It's a federal government agency; the underlying job listings are public job postings (already
  public and freely viewable on the website/app), not scraped-and-resold third-party content, so
  the legal risk profile is low for personal, non-commercial use.
- There is no explicit redistribution/attribution clause to comply with, because there's no
  official ToS at all — but by the same token there's no explicit permission either, so this is
  "community-tolerated," not "legally blessed." Fine for a personal tool; would need a legal check
  before any commercial use.
- Because the key is shared/public, it could be rotated or shut off without notice — build with a
  graceful-failure path, not a hard dependency.

**Live test (2026-10-04):**
```
curl -H "X-API-Key: jobboerse-jobsuche" \
  "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs?was=Softwareentwickler&wo=Berlin&size=2"
```
→ HTTP 200, real results. Example (trimmed):
```json
{
  "ergebnisliste": [{
    "stellenangebotsTitel": "Softwareentwickler (m/w/d)",
    "firma": "Laurin Stankusch Vertriebsagentur",
    "referenznummer": "10001-1003644689-S",
    "arbeitszeitVollzeit": true,
    "homeofficemoeglich": true,
    "homeofficetyp": "NACH_VEREINBARUNG",
    "gehaltsspanneVon": 42000, "gehaltsspanneBis": 60000,
    "datumErsteVeroeffentlichung": "2026-09-03",
    "aenderungsdatum": "2026-09-03T07:36:56.853",
    "stellenlokationen": [{
      "adresse": {"ort": "Berlin", "region": "BERLIN", "land": "DEUTSCHLAND"},
      "breite": 52.492683263, "laenge": 13.402575309
    }]
  }],
  "maxErgebnisse": 204
}
```
Search results do **not** include the job description. A second call against a separate detail
endpoint is needed, with the reference number base64-encoded into the path:
```
curl -H "X-API-Key: jobboerse-jobsuche" \
  "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/MTAwMDEtMTAwMzY0NDY4OS1T"
```
→ HTTP 200, returns `stellenangebotsBeschreibung` with the full markdown-ish job text:
```json
{
  "stellenangebotsTitel": "Softwareentwickler (m/w/d)",
  "stellenangebotsBeschreibung": "## Ihre Aufgaben\n\n- Entwicklung und Weiterentwicklung unserer Shop- und Plattformsoftware...\n\n## Das bringen Sie idealerweise mit\n\n- Erste praktische Erfahrung in der Softwareentwicklung mit PHP...\n\n## Das bieten wir Ihnen\n\n- Einen unbefristeten Arbeitsvertrag..."
}
```
This is a genuine two-call pattern: `GET .../pc/v6/jobs?...` for search/listing,
`GET .../pc/v4/jobdetails/{base64(referenznummer)}` for full text — exactly mirroring the
Greenhouse/Lever "list then enrich" shape the discovery design already expects.

**Normalization sketch → `JobPosting`:**

| JobPosting field | Source field | Notes |
|---|---|---|
| `job_id` | `f"arbeitsagentur:{referenznummer}"` | `referenznummer` is BA's own stable job ID |
| `company` | `firma` | |
| `title` | `stellenangebotsTitel` | |
| `location` | `stellenlokationen[0].adresse.ort` (+ `region`) | compose a display string |
| `url` | `externeURL` if present, else `f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{referenznummer}"` | `externeURL` only present when the posting links out to an external ATS/site |
| `description` | `stellenangebotsBeschreibung` from the jobdetails call | requires the second call |
| `source` | `"arbeitsagentur"` (new Literal member needed) | |
| `ats_job_id` | `referenznummer` | duplicate of `job_id`'s suffix, kept for parity with Greenhouse/Lever shape |
| `department` | `None` | not provided |
| `posted_at` | `datumErsteVeroeffentlichung` | already ISO date |
| `location_lat` / `location_lng` | `stellenlokationen[0].breite` / `.laenge` | **provided directly by the API** — no Nominatim geocoding call needed for this source, unlike the generic `geocoding/client.py` path |
| `is_remote` | `homeofficemoeglich` | boolean already provided |
| `raw` | full search-result dict (optionally merged with the detail dict) | |

**Verdict:** Best single addition for DE coverage. Live-verified, free, no signup, gives exact
coordinates and a remote flag for free (saves a geocoding call per job), and surfaces employers
(German SMEs, public sector) that never appear on Greenhouse/Lever. Main risk is "unofficial key"
fragility — isolate it behind its own try/except in discovery so a future key rotation degrades
gracefully instead of breaking the whole discovery run.

---

## 2. Arbeitnow

**What it is:** A small, EU/DACH-leaning job board (arbeitnow.com) that explicitly publishes a
free public "Job Board API" for reuse, aimed at exactly this kind of use case.

**Auth:** None. No key, no signup, no header required.

**Rate limits:** Not formally specified as a number. The API's own metadata (returned inline, see
below) just says "please do not abuse" and that results refresh hourly — so hourly polling is
clearly within intended use; nothing suggests tighter limits than that for reasonable personal-tool
traffic.

**ToS / legal notes** (from `arbeitnow.com/terms` and the API response itself):
- Provided "as is"/"as available," no warranty, and Arbeitnow "may revoke the permission to use
  API at any time" — treat as a soft dependency, not guaranteed.
- Attribution requested: "please do not abuse. I would appreciate linking back to the site." No
  specific pixel/badge requirement like Adzuna's — just a link back somewhere in the product.
- No explicit redistribution/storage restriction found for the API specifically (the general site
  terms restrict reuse of *site content*, but the API is separately and explicitly offered for
  external consumption, with its own lighter-touch terms baked into the response payload).
- No commercial-vs-personal distinction drawn for the API path — low friction either way, but this
  is a personal tool, which further reduces any residual risk.

**Live test (2026-10-04):**
```
curl "https://www.arbeitnow.com/api/job-board-api?page=1"
```
→ HTTP 200, real results, 325 jobs per page. Example record (description trimmed):
```json
{
  "slug": "medizinische-fachangestellte-in-modernem-hausarztzentrum-frechen-339157",
  "company_name": "PraxisEins",
  "title": "Medizinische Fachangestellte (m/w/d) in modernem Hausarztzentrum - Frechen",
  "description": "<h2><strong>IHR START BEI PRAXISEINS.</strong></h2><p>...full HTML...</p>",
  "remote": false,
  "url": "https://www.arbeitnow.com/jobs/companies/praxiseins/medizinische-fachangestellte-in-modernem-hausarztzentrum-frechen-339157",
  "tags": ["MFA"],
  "job_types": ["Full Time"],
  "location": "Frechen",
  "created_at": 1791146412
}
```
Top-level response also includes pagination (`links.next`) and this inline notice in `meta`:
`"terms": "This is a free public API for jobs, please do not abuse. I would appreciate linking back to the site... Jobs are updated every hour..."` — i.e. the ToS is handed to you inline with every response, which is about as low-friction as API legal terms get.

One real finding: results are **not filtered to Germany** — this is a general EU/remote job board
that happens to have heavy German/DACH representation (visible in the example above), not a
Germany-only feed. A consumer would need to filter client-side on `location`/`tags` for DE-specific
use, same as it already filters company lists.

**Normalization sketch → `JobPosting`:**

| JobPosting field | Source field | Notes |
|---|---|---|
| `job_id` | `f"arbeitnow:{slug}"` | `slug` is unique and stable |
| `company` | `company_name` | |
| `title` | `title` | |
| `location` | `location` | plain string, e.g. `"Frechen"`; may be `"Worldwide"`/empty for remote |
| `url` | `url` | direct link to the listing |
| `description` | `description` | full HTML — same post-processing (HTML→text) the Playwright `extractor.py` path already does, reusable as-is |
| `source` | `"arbeitnow"` (new Literal member) | |
| `ats_job_id` | `slug` | |
| `department` | `None` | not provided; `tags` could optionally feed this |
| `posted_at` | `datetime.fromtimestamp(created_at).isoformat()` | `created_at` is a Unix timestamp |
| `location_lat` / `location_lng` | `None`, geocode via `geocoding/client.py` | not provided by this API, unlike BA |
| `is_remote` | `remote` | boolean provided directly |
| `raw` | full record | |

**Verdict:** Tied for best addition alongside BA. Zero friction (no key, no signup), live-verified,
clean JSON, full HTML descriptions, explicit pagination, and an unusually honest/simple ToS. The
only integration cost is a DE-relevance filter since the feed is EU-wide, not Germany-only.

---

## 3. Adzuna (DE region)

**What it is:** A commercial job-search aggregator with an official public API and per-country
endpoints, including `api.adzuna.com/v1/api/jobs/de/search/...` for Germany specifically.

**Auth:** `app_id` + `app_key`, both free, obtained by registering at `developer.adzuna.com`.
Registration is a short signup form (email + basic info) — not a lengthy approval process, but it
is a real signup gate, which is why **no live call was made** for this report (the task scope says
to test only sources that don't require a lengthy signup; a quick form still means the researcher
would be creating an account on the user's behalf, which wasn't done here). A future implementer
should expect this to take a few minutes, not days.

**Rate limits (free tier, documented):**
- 25 requests/minute
- 250/day
- 1,000/week
- 2,500/month
Higher limits available on request "where they see mutual commercial benefit" — not relevant for a
personal tool, but worth knowing the ceiling exists if usage ever scales up (e.g. per-user daily
discovery across many users would need to be budgeted against the shared app key).

**ToS / legal notes** (from `developer.adzuna.com/docs/terms_of_service`) — this is the source with
the most actual legal text, and it matters for this project specifically:
- Explicitly permitted uses include **"personal research."** This project is a personal job-search
  tool, not a commercial product, so it plausibly sits inside the permitted-use bucket as written
  — this is the one source where the personal/non-commercial framing has textual support, not just
  inference.
- Commercial/government/academic organizational use is restricted to a 14-day trial for
  *validating* coverage/quality — not for ongoing use — after which a license agreement is
  required. Not applicable here as long as this stays a personal tool, but flagged because if this
  project were ever productized/monetized, Adzuna's terms would need revisiting at that point, not
  assumed to still apply.
- Redistribution/aggregation restriction: data **cannot** be "used in its original format or in
  aggregation... to deliver any ongoing work or research" without written consent, and on
  termination all stored data/insertion codes must be removed immediately. Read literally, this
  is in tension with storing `JobPosting` records long-term in `data/users/{id}/jobs.json` the way
  Greenhouse/Lever jobs are — the safer reading for a personal tool is to treat Adzuna more like a
  live lookup/cache (short TTL, re-fetch rather than archive indefinitely) than a permanent store,
  unlike the BA/Arbeitnow sources above which have no such clause.
- If ever displaying raw Adzuna listings/branding, attribution requirements apply: "Jobs by Adzuna"
  badge (≥116×23px) linking back, for ad listings; a labeled icon for any salary-estimate data.

**Live test:** Not performed (signup gate — see Auth above). Response shape below is from Adzuna's
own published documentation/examples, not independently verified here — flagged accordingly,
unlike every other "verdict" in this doc.

**Expected response shape** (per Adzuna's public docs, `/v1/api/jobs/de/search/1`):
```json
{
  "results": [{
    "id": "1234567890",
    "title": "Backend Developer (m/w/d)",
    "company": {"display_name": "Example GmbH"},
    "location": {"display_name": "Berlin, Deutschland", "area": ["Deutschland", "Berlin"]},
    "description": "We are looking for...",
    "redirect_url": "https://www.adzuna.de/land/ad/1234567890",
    "created": "2026-10-01T08:00:00Z",
    "category": {"label": "IT Jobs"},
    "salary_min": 50000, "salary_max": 70000,
    "latitude": 52.52, "longitude": 13.405
  }]
}
```

**Normalization sketch → `JobPosting`:**

| JobPosting field | Source field | Notes |
|---|---|---|
| `job_id` | `f"adzuna:{id}"` | |
| `company` | `company.display_name` | |
| `title` | `title` | |
| `location` | `location.display_name` | |
| `url` | `redirect_url` | Adzuna's own tracked redirect, not the original posting — can't deep-link past Adzuna |
| `description` | `description` | Adzuna's descriptions are often truncated/summarized, not the full original text — a known quality gap vs. BA/Arbeitnow |
| `source` | `"adzuna"` (new Literal member) | |
| `ats_job_id` | `id` | |
| `department` | `category.label` | approximate — Adzuna's "category" is an industry label, not a company department |
| `posted_at` | `created` | |
| `location_lat` / `location_lng` | `latitude` / `longitude` | provided directly, like BA |
| `is_remote` | not directly provided | infer from `location.display_name`/description text, same heuristic path as the scraper fallback |
| `raw` | full record | |

**Verdict:** Credible second-tier addition — genuinely free for personal use with textual ToS
support for exactly that use case, and gives EU-wide coverage (not just Germany) if the project
ever wants to broaden beyond DE. Held back from "top pick" by: (1) the signup gate meaning it
wasn't live-verified here, (2) the redistribution clause arguing against archiving results the
same way as other sources, and (3) descriptions that are reportedly thinner than BA/Arbeitnow's
full text.

---

## 4. Jobicy

**What it is:** A remote-jobs board with geographic eligibility tagging (e.g. jobs open to
candidates based in a given country/region), with a free public API and a published GitHub repo
(`Jobicy/remote-jobs-api`) documenting it as an intentionally open integration surface.

**Auth:** None. No key, no signup.

**Rate limits:** No hard numeric cap published, but explicit guidance: cache responses, and "do not
schedule new automated synchronization passes more frequently than once per hour." A once-daily
discovery run is well within this.

**ToS / legal notes** (from the API's own `friendlyNotice` field and GitHub docs):
- Fair-use attribution required: must keep "Jobicy as the original source," preserve the canonical
  Jobicy job URL, and not present listings "as your own original job postings."
- Explicit restriction: **"Jobicy requests that job listings not be distributed to external job
  platforms such as Jooble, Google Jobs, LinkedIn, and others."** This specifically targets
  redistributing-to-other-aggregators, not personal-tool consumption — a solo job-search app
  displaying results to its own single user doesn't fit the thing this clause is aimed at, but it's
  worth being precise that this is the actual wording rather than a blanket "no storage" rule.
- "Excessive requests, intentional overloading, content misrepresentation, or abusive activity may
  result in restricted access" — standard fair-use language, not a special burden.
- No commercial/personal distinction drawn; the friendly, informal tone of the published terms
  ("You might be building something amazing, we wish you the best of luck!") suggests Jobicy is
  comfortable with exactly this kind of hobby/personal integration.

**Live test (2026-10-04):**
```
curl "https://jobicy.com/api/v2/remote-jobs?count=3&tag=germany"
```
→ HTTP 200, real results. Example (trimmed):
```json
{
  "apiVersion": "2.2.19",
  "documentationUrl": "https://jobi.cy/apidocs",
  "friendlyNotice": "Thanks for using Jobicy API! Please ensure Jobicy is clearly credited with a direct link to the source, and all application buttons redirect to the original job URL provided in this feed...",
  "jobCount": 3,
  "jobs": [{
    "id": 154479,
    "url": "https://jobicy.com/jobs/154479-enterprise-account-executive-dach-4",
    "jobTitle": "Enterprise Account Executive (DACH)",
    "companyName": "infisical",
    "jobIndustry": ["Sales"],
    "jobType": ["Full-Time"],
    "jobGeo": "Germany",
    "jobLevel": "Director",
    "jobExcerpt": "Infisical is the open source security infrastructure platform...",
    "jobDescription": "<p>...full HTML description...</p>"
  }]
}
```
Real finding: `tag=germany` does return jobs explicitly geo-tagged `"jobGeo": "Germany"`, which is
more precise than initially assumed — not just "anywhere/remote" noise — but this is still a
**remote-jobs board**, so the pool is "remote roles open to people in Germany," not "jobs located
in Germany" the way BA/Arbeitnow postings are. Complementary to the other sources (covers remote
roles at companies that wouldn't post to a German job board at all) rather than a substitute.

**Normalization sketch → `JobPosting`:**

| JobPosting field | Source field | Notes |
|---|---|---|
| `job_id` | `f"jobicy:{id}"` | |
| `company` | `companyName` | |
| `title` | `jobTitle` | |
| `location` | `jobGeo` | e.g. `"Germany"` — coarse, not a city |
| `url` | `url` | must stay the canonical Jobicy URL per ToS |
| `description` | `jobDescription` (HTML) | `jobExcerpt` available as a shorter fallback |
| `source` | `"jobicy"` (new Literal member) | |
| `ats_job_id` | `id` | |
| `department` | `jobIndustry[0]` | approximate, same caveat as Adzuna's `category` |
| `posted_at` | not in the trimmed example; full payload includes `pubDate` per Jobicy's docs | verify field name against a full response before wiring in |
| `location_lat` / `location_lng` | `None`, geocode only if `jobGeo` resolves to something more specific than a country | often not worth geocoding a whole-country string |
| `is_remote` | `True` (always, by construction) | every Jobicy listing is remote |
| `raw` | full record | |

**Verdict:** Worth adding as a *supplementary* remote-roles source, not a German-market source in
the geographic sense — low friction (no key, works today) but narrower fit for "jobs in Germany"
than BA/Arbeitnow. Good fit for a user whose `remote_preference` (section 3a of the design) is
`remote_only`.

---

## 5. Jooble (extra candidate found during research)

**What it is:** A large multi-country job search aggregator (60+ countries including Germany) with
a free developer API, surfaced here because it's a genuinely different aggregation source from
Adzuna with reasonable DE/EU coverage.

**Auth:** Free API key, but obtained only via a request form (`jooble.org/api/about`) that asks for
name, company, website, and phone number — not a self-serve instant key like Adzuna's dashboard.
This framing (company/website/phone) signals Jooble expects B2B/commercial applicants more than
hobbyists, even though the key itself is free.

**Rate limits:** Not publicly documented at all — no published numbers, no published pricing page.
A free key reportedly caps around 1,000 jobs/month in practice, but this isn't an official,
citable limit.

**ToS / legal notes:** No publicly available terms of service was found to cite with any
confidence — this is the one source in this report where "what are you actually agreeing to" could
not be pinned down from public documentation. That absence is itself the finding: integrating
without a clear ToS to point to is a real (if soft) legal-ambiguity cost, worse than Adzuna's
(restrictive but at least explicit and personal-research-friendly) terms.

**Live test:** Not performed — getting a key requires submitting a contact-info form, which this
research pass didn't do (same reasoning as skipping Adzuna's signup, but with the added concern
that the form explicitly solicits business-oriented info this project doesn't really have to give).

**Verdict:** Lowest priority of the sources actually investigated. No clean self-serve key, no
published ToS/rate limits, and a request-form flow oriented at companies rather than individual
developers. Not recommended as a near-term addition; only worth revisiting if both BA and Arbeitnow
coverage turn out to be insufficient in practice.

---

## 6. EURES (European Job Mobility Portal)

**What it is:** The EU's own official cross-border job mobility portal, run by the European
Commission — in principle the single most authoritative EU-wide job source, covering all member
states including Germany.

**Why it's not usable here:** Unlike every other source above, EURES is **not** open to the
general public for API-style data extraction. Per the EURES portal's own help/support pages:
restricted-content access requires an EU Login account *and* registration as a recognized
**"EURES partner organisation,"** explicitly approved by a EURES National Coordination Office.
There is no self-serve "sign up for an API key" path the way Adzuna or even Jooble offer — this is
an institutional partnership requirement, not a developer-portal gate.

A reverse-engineered, community-maintained OpenAPI spec does exist (documenting endpoints like
`POST /jv-searchengine/public/jv-search/search`) and is reportedly callable without a login/API key
at a technical level. That technical openness doesn't change the legal position: the EURES portal's
own terms restrict data *extraction* via API/similar technology to recognized partner
organisations specifically — calling the undocumented endpoint anyway would be using the service
outside its stated terms, regardless of whether it happens to respond. For that reason **no live
test call was made against EURES** for this report, unlike BA's similarly-"unofficial" key: the BA
situation is "no ToS exists to violate," while the EURES situation is "a ToS exists and explicitly
says this access path is restricted to approved partners" — a materially different legal posture
even though both involve an undocumented/non-official API surface.

**Normalization sketch:** Not provided. Mapping onto `JobPosting` would be straightforward in
principle (vacancy search results generally carry title/company/location/description/URL/date,
similar in shape to Adzuna) if access were ever obtained through the legitimate partner channel,
but doing that design work now would imply this is close to actionable, which it isn't without
that partnership status.

**Verdict: avoid.** Best EU-wide coverage on paper, but the only source here with an explicit,
unambiguous access restriction that a solo personal-tool developer has no realistic path to
satisfying (becoming a "EURES partner organisation" is an institutional process, not a signup
form). Revisit only if this project ever operates under an organization that could qualify as a
EURES partner — not a near-term option.

---

## Recommendation

**Add first, in this order:**

1. **Bundesagentur für Arbeit (Jobsuche API)** — the standout pick. Live-verified today, zero
   signup friction, no restrictive ToS to violate (because none exists), and it uniquely hands back
   exact lat/lng and a remote flag for free — the only source here that saves a `geocoding/client.py`
   round-trip per job. Its only real cost is the two-call (search → jobdetails) pattern, which is a
   small, well-understood shape given `scraper/ats_client.py` already does the analogous thing for
   Workday-style fallbacks conceptually.
2. **Arbeitnow** — ties for first on friction (no key at all) and is explicitly, cleanly offered for
   exactly this kind of reuse, with the lightest-touch ToS of any source surveyed (a requested link
   back, nothing else). Its only gap is that it isn't Germany-filtered, so it needs a client-side
   location/tag filter to be DE-specific, which is trivial.

Together, BA + Arbeitnow give solid DE-market coverage (public-sector/Mittelstand via BA, broader
DACH/startup-leaning listings via Arbeitnow) with the least legal and engineering friction of
anything surveyed, and both are already confirmed working end-to-end with real example payloads
captured above.

**Good second-tier, worth adding once the first two are wired in:**

- **Adzuna (DE)** — genuinely free for "personal research" per its own terms, which is a real fit
  for this project's stated personal-tool framing, but it costs a signup step and its ToS argues
  for treating results as a live lookup rather than a permanent archive — a real (if manageable)
  design constraint the other sources don't impose.
- **Jobicy** — zero-friction and live-verified, but it's a remote-jobs board with country
  eligibility tags, not a Germany-located-jobs board — best framed as a complementary "remote
  roles" source for users with `remote_preference == "remote_only"`, not a primary DE source.

**Lower priority / avoid for now:**

- **Jooble** — technically free but gated behind a business-oriented contact form, with no
  published ToS or rate limits to point to. Not worth the ambiguity unless BA+Arbeitnow+Adzuna
  coverage proves insufficient.
- **EURES** — best coverage on paper, explicitly restricted by its own terms to recognized partner
  organisations rather than open to individual developers; no legitimate self-serve path exists for
  a personal tool. Skip entirely unless the project's organizational status changes.
