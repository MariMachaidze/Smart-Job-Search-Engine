"""
scraper/discovery.py

Routes each company to the cheapest working job source: ATS public API
first (Greenhouse/Lever via scraper.ats_client), falling back to the
existing Playwright scraper (scraper.scraper + scraper.extractor, imported
as library functions and never modified) for anything resolve_ats can't
place -- Workday or a genuinely unknown ATS.

Also owns, per plan section 3a:
  - enrich_job_location(): the geocoding bridge that should be called once
    per NEW job at persist time (see its docstring for exactly where this
    plugs into orchestrator/discovery_graph.py's persist_jobs_node, owned
    by workstream F).
  - apply_hard_filters(): the commute/remote-preference hard filter, exposed
    as a plain importable function so F can wire it into discovery_graph as
    a node between persist_jobs and score_jobs.
"""
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional

from storage.schemas import JobPosting, UserPreferences
from scraper.ats_client import resolve_ats, fetch_greenhouse_jobs, fetch_lever_jobs
from scraper.scraper import scrape_company
from scraper.extractor import extract_job_details
from geocoding.client import geocode, haversine_km


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _infer_remote(location_text: Optional[str]) -> Optional[bool]:
    if not location_text:
        return None
    return "remote" in location_text.lower()


async def discover_company_jobs(playwright, company: str, careers_url: str) -> list[JobPosting]:
    """
    Resolve `company`'s ATS and return its current job postings as
    JobPosting records. Tries Greenhouse/Lever's public JSON APIs first (no
    browser needed); falls back to the existing Playwright
    scraper.scrape_company + extractor.extract_job_details for
    Workday/unknown-ATS companies.

    `playwright` is an already-started playwright context (from
    `async_playwright() as playwright`), only touched on the fallback path.
    Callers batching many companies (e.g. the daily discovery graph) should
    resolve_ats for all of them first and only start a browser at all if at
    least one company actually needs the fallback path -- that's the whole
    point of trying the ATS APIs first.
    """
    ats = await resolve_ats(company, careers_url)

    if ats["platform"] == "greenhouse" and ats["board_token"]:
        return await fetch_greenhouse_jobs(ats["board_token"], company)

    if ats["platform"] == "lever" and ats["board_token"]:
        return await fetch_lever_jobs(ats["board_token"], company)

    # Workday + unknown -> existing scraper.py + extractor.py, unmodified.
    return await _discover_via_scraper(playwright, company, careers_url)


async def _discover_via_scraper(playwright, company: str, careers_url: str) -> list[JobPosting]:
    """Fallback path: use the existing (unmodified) Playwright scraper to
    find job links, then the existing (unmodified) extractor to pull
    title/location/description off each one."""
    link_dicts = await scrape_company(playwright, company, careers_url)
    if not link_dicts:
        return []

    browser = await playwright.chromium.launch(
        headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
    )
    context = await browser.new_context()
    page = await context.new_page()

    now = _now_iso()
    company_slug = _slugify(company)
    jobs: list[JobPosting] = []

    try:
        for link in link_dicts:
            url = link["url"]
            details = await extract_job_details(page, url, company)

            if details.get("title") in (None, "Error"):
                continue  # extractor hit an error on this URL -- skip it

            location_text = details.get("location") or "Unknown"
            job_id = "scraper:" + company_slug + ":" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]

            job: JobPosting = {
                "job_id": job_id,
                "company": company,
                "title": details.get("title") or "Unknown",
                "location": location_text,
                "url": url,
                "description": details.get("description") or "",
                "source": "scraper",
                "ats_job_id": None,
                "department": None,
                "posted_at": None,
                "discovered_at": now,
                "last_seen_at": now,
                "status": "new",
                "raw": None,
                "location_lat": None,
                "location_lng": None,
                "is_remote": _infer_remote(location_text),
            }
            jobs.append(job)
    finally:
        await browser.close()

    return jobs


def enrich_job_location(job: JobPosting) -> JobPosting:
    """
    Geocode `job`'s location string in place (mutates and returns `job`).

    *** Where this plugs into the pipeline ***
    This is a plain, synchronous, one-job-at-a-time function -- deliberately
    NOT called automatically inside discover_company_jobs / fetch_greenhouse_jobs
    / fetch_lever_jobs, because those return a company's FULL current job
    list in one shot (638 jobs for a single real Greenhouse board, observed
    during implementation) and OSM Nominatim's usage policy caps anonymous
    use at ~1 request/second. Geocoding every returned job inline on every
    discovery run would both blow that rate limit and re-geocode postings
    whose location never changes run over run.

    Per plan sections 3a/11, this should be called by workstream F's
    `persist_jobs_node` (orchestrator/discovery_graph.py) ONCE PER JOB THAT
    IS ACTUALLY NEW -- i.e. after diffing the freshly-discovered jobs
    against the existing jobs.json by job_id, call this only for records
    that don't already carry a geocoded location_lat/location_lng. That
    keeps the Nominatim call volume down to "new postings today" rather than
    "every open posting every day", which is exactly the "cache geocoded
    coordinates on the record rather than re-geocoding on every run"
    behavior the plan calls for. Callers geocoding a batch of new jobs in a
    loop should still pace the calls (e.g. a short sleep between calls, or a
    1-req/sec limiter) to stay within Nominatim's usage policy.
    """
    if job.get("is_remote") is None:
        job["is_remote"] = _infer_remote(job.get("location"))

    if job.get("location_lat") is not None and job.get("location_lng") is not None:
        return job  # already geocoded -- don't re-spend a lookup

    if job.get("is_remote"):
        return job  # remote jobs have no meaningful commute coordinate

    location_text = job.get("location")
    if not location_text or location_text.strip().lower() in ("unknown", "error", ""):
        return job

    coords = geocode(location_text)
    if coords:
        job["location_lat"], job["location_lng"] = coords

    return job


def apply_hard_filters(jobs: list[JobPosting], preferences: UserPreferences) -> list[JobPosting]:
    """
    Plan section 3a. Deterministic pre-filter meant to run (as a LangGraph
    node owned by workstream F) between persist_jobs and score_jobs in
    discovery_graph: drops jobs that are excluded on purely computable
    grounds (remote preference / commute distance) before they ever reach
    an LLM scoring call. Exposed here as a plain function so F's graph node
    can just import and call it.

    A job is EXCLUDED when either:
      - preferences["remote_preference"] == "remote_only" and the job is
        not remote, OR
      - preferences["max_commute_km"] is set, AND the job is not remote,
        AND the user is not willing_to_relocate, AND the haversine distance
        from the user's home_lat/home_lng to the job's
        location_lat/location_lng exceeds max_commute_km.

    Jobs missing coordinates (geocoding failed or hasn't run yet) or a user
    missing a geocoded home location are never excluded by the commute
    rule -- there's no computable distance in that case, so this stays
    conservative and leaves the decision to scoring/the user rather than
    silently dropping jobs over an unresolvable comparison.
    """
    remote_only = preferences.get("remote_preference") == "remote_only"
    max_commute_km = preferences.get("max_commute_km")
    willing_to_relocate = bool(preferences.get("willing_to_relocate", False))
    home_lat = preferences.get("home_lat")
    home_lng = preferences.get("home_lng")

    filtered: list[JobPosting] = []

    for job in jobs:
        is_remote = bool(job.get("is_remote"))

        if remote_only and not is_remote:
            continue

        can_check_distance = (
            max_commute_km is not None
            and not is_remote
            and not willing_to_relocate
            and home_lat is not None
            and home_lng is not None
            and job.get("location_lat") is not None
            and job.get("location_lng") is not None
        )
        if can_check_distance:
            distance_km = haversine_km(home_lat, home_lng, job["location_lat"], job["location_lng"])
            if distance_km > max_commute_km:
                continue

        filtered.append(job)

    return filtered
