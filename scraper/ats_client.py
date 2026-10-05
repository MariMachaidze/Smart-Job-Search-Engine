"""
scraper/ats_client.py

Three-tier ATS detection, cheapest first, plus the Greenhouse/Lever public
JSON API fetchers.

  Tier 1 (cheapest): guess the ATS board token as a slug of the company name
    and probe Greenhouse then Lever directly. Covers the common case where a
    company's listed careers_url is just a marketing page in front of a
    standard-named ATS board -- e.g. Anthropic's companies.csv row points at
    https://www.anthropic.com/careers/jobs (not a greenhouse.io URL at all),
    but its Greenhouse board token is simply "anthropic", so this tier finds
    it with one direct API probe and never needs to touch the HTML.

  Tier 2: regex-match the stored careers_url itself for known ATS URL shapes
    (*.greenhouse.io/*, jobs.lever.co/*, *.myworkdayjobs.com/*), in case the
    company list already points straight at the ATS.

  Tier 3 (most expensive): fetch the careers page HTML and regex-scan it for
    an embedded ATS link. Handles pages that embed e.g. a
    job-boards.greenhouse.io/<token> link in their markup/JS without that
    URL ever being the company's stored careers_url, and without tier 1's
    token guess happening to match (e.g. the company name doesn't slug down
    to the same token the ATS board actually uses).

Anything that doesn't resolve through tiers 1-3 -- including Workday, which
has no public per-tenant JSON API usable without session/cookie handling --
resolves to {"platform": "unknown", "board_token": None}, and the caller
(scraper/discovery.py) falls back to the existing Playwright scraper.

Verified live against the real Greenhouse and Lever APIs during
implementation (see module docstring history / task report) -- both work
with no auth:
  https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
  https://api.lever.co/v0/postings/{token}?mode=json
Both APIs return a clean 404 for an unknown/nonexistent token, which is what
makes the tier-1 "guess and probe" approach safe -- a wrong guess fails
cleanly rather than returning garbage.
"""
import re
from datetime import datetime, timezone
from typing import Literal, Optional, TypedDict

import httpx
from bs4 import BeautifulSoup

from storage.schemas import JobPosting

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
LEVER_API = "https://api.lever.co/v0/postings/{token}"

_TIMEOUT = 15.0
_USER_AGENT = (
    "SmartJobSearchEngine/0.1 (personal job-hunting tool; "
    "contact: motus.haptic.suit@gmail.com)"
)

_GREENHOUSE_URL_RE = re.compile(
    r"(?:boards|job-boards)\.greenhouse\.io/([a-zA-Z0-9\-_]+)", re.IGNORECASE
)
_LEVER_URL_RE = re.compile(r"jobs\.lever\.co/([a-zA-Z0-9\-_]+)", re.IGNORECASE)
_WORKDAY_RE = re.compile(r"([a-zA-Z0-9\-_]+)\.myworkdayjobs\.com", re.IGNORECASE)


class ATSInfo(TypedDict):
    platform: Literal["greenhouse", "lever", "workday", "unknown"]
    board_token: Optional[str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug_variants(company: str) -> list[str]:
    """
    A few plausible board-token spellings for `company`, cheapest/most
    likely first. Board tokens are picked by each company at ATS signup
    time and aren't fully standardized, so this is a best-effort guess tier
    1 tries and verifies against the live API -- not a guarantee.
    """
    lower = company.lower().strip()
    no_sep = re.sub(r"[^a-z0-9]+", "", lower)
    hyphenated = re.sub(r"[^a-z0-9]+", "-", lower).strip("-")

    variants = []
    for v in (no_sep, hyphenated):
        if v and v not in variants:
            variants.append(v)
    return variants


async def _probe_greenhouse(client: httpx.AsyncClient, token: str) -> bool:
    try:
        resp = await client.get(GREENHOUSE_API.format(token=token), params={"content": "true"})
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


async def _probe_lever(client: httpx.AsyncClient, token: str) -> bool:
    try:
        resp = await client.get(LEVER_API.format(token=token), params={"mode": "json"})
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def _match_known_url(text: str) -> Optional[ATSInfo]:
    gh = _GREENHOUSE_URL_RE.search(text)
    if gh:
        return {"platform": "greenhouse", "board_token": gh.group(1)}

    lv = _LEVER_URL_RE.search(text)
    if lv:
        return {"platform": "lever", "board_token": lv.group(1)}

    wd = _WORKDAY_RE.search(text)
    if wd:
        return {"platform": "workday", "board_token": wd.group(1)}

    return None


async def resolve_ats(company: str, careers_url: str) -> ATSInfo:
    """
    Resolve which ATS `company` uses, cheapest check first. Never raises --
    any failure at a given tier (network error, no match, non-200) just
    falls through to the next tier, and total failure resolves to
    {"platform": "unknown", "board_token": None} so callers always get back
    a usable ATSInfo and know to fall back to the Playwright scraper.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
        # Tier 1: guess the board token from the company name and probe directly.
        for token in _slug_variants(company):
            if await _probe_greenhouse(client, token):
                return {"platform": "greenhouse", "board_token": token}
            if await _probe_lever(client, token):
                return {"platform": "lever", "board_token": token}

        # Tier 2: regex-match the stored careers_url itself.
        matched = _match_known_url(careers_url)
        if matched:
            return matched

        # Tier 3: fetch the careers page HTML and scan for an embedded ATS link.
        try:
            resp = await client.get(careers_url, follow_redirects=True)
            if resp.status_code == 200:
                html_matched = _match_known_url(resp.text)
                if html_matched:
                    return html_matched
        except httpx.HTTPError:
            pass

    return {"platform": "unknown", "board_token": None}


def _clean_html(raw: Optional[str]) -> str:
    """Greenhouse's `content` field is HTML-entity-escaped HTML; unescape and
    strip tags down to plain text for JobPosting.description."""
    if not raw:
        return ""
    import html as html_module

    unescaped = html_module.unescape(raw)
    text = BeautifulSoup(unescaped, "html.parser").get_text(separator="\n")
    return text.strip()


def _infer_remote_from_text(location_text: Optional[str]) -> Optional[bool]:
    if not location_text:
        return None
    return "remote" in location_text.lower()


def _infer_remote_greenhouse(raw_job: dict, location_text: str) -> Optional[bool]:
    for meta in raw_job.get("metadata") or []:
        name = str(meta.get("name", "")).lower()
        if name in ("location type", "work location", "remote", "workplace type"):
            value = str(meta.get("value", "")).lower()
            if value:
                return "remote" in value
    return _infer_remote_from_text(location_text)


async def fetch_greenhouse_jobs(board_token: str, company: str) -> list[JobPosting]:
    """
    Fetch every current posting for a Greenhouse board via its public JSON
    API (no auth): GET boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true

    `job_id` is deterministic (f"greenhouse:{board_token}:{ats_job_id}") so
    that discovery's new/seen/closed diffing (persist_jobs_node, plan
    section 11, owned by workstream F) sees the same job_id across runs for
    the same posting rather than minting a fresh one every day.

    `location_lat`/`location_lng` are intentionally left None here -- they're
    geocoded once at persist time (see `scraper/discovery.py:enrich_job_location`),
    not per-fetch, to avoid hammering the geocoding provider's rate limit
    across every job in a board that can run into the hundreds (638 for a
    real board observed during implementation).
    """
    url = GREENHOUSE_API.format(token=board_token)
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
        resp = await client.get(url, params={"content": "true"})
        resp.raise_for_status()
        data = resp.json()

    now = _now_iso()
    jobs: list[JobPosting] = []

    for raw_job in data.get("jobs", []):
        ats_job_id = str(raw_job.get("id"))
        location_text = (raw_job.get("location") or {}).get("name") or "Unknown"

        department = None
        departments = raw_job.get("departments") or []
        if departments:
            department = departments[0].get("name")

        job: JobPosting = {
            "job_id": f"greenhouse:{board_token}:{ats_job_id}",
            "company": company,
            "title": raw_job.get("title") or "Unknown",
            "location": location_text,
            "url": raw_job.get("absolute_url") or "",
            "description": _clean_html(raw_job.get("content")),
            "source": "greenhouse",
            "ats_job_id": ats_job_id,
            "department": department,
            "posted_at": raw_job.get("first_published"),
            "discovered_at": now,
            "last_seen_at": now,
            "status": "new",
            "raw": raw_job,
            "location_lat": None,
            "location_lng": None,
            "is_remote": _infer_remote_greenhouse(raw_job, location_text),
        }
        jobs.append(job)

    return jobs


async def fetch_lever_jobs(board_token: str, company: str) -> list[JobPosting]:
    """
    Fetch every current posting for a Lever board via its public JSON API
    (no auth): GET api.lever.co/v0/postings/{token}?mode=json

    Same job_id-determinism and lazy-geocoding rationale as
    `fetch_greenhouse_jobs` above.
    """
    url = LEVER_API.format(token=board_token)
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
        resp = await client.get(url, params={"mode": "json"})
        resp.raise_for_status()
        data = resp.json()

    now = _now_iso()
    jobs: list[JobPosting] = []

    for raw_job in data:
        ats_job_id = str(raw_job.get("id"))
        categories = raw_job.get("categories") or {}
        location_text = categories.get("location") or raw_job.get("country") or "Unknown"
        department = categories.get("team")

        # Lever's *Plain fields are already plain text (no HTML to strip).
        description_parts = [
            raw_job.get("descriptionPlain") or "",
            raw_job.get("additionalPlain") or "",
        ]
        description = "\n\n".join(p for p in description_parts if p).strip()

        posted_at = None
        created_at_ms = raw_job.get("createdAt")
        if created_at_ms:
            try:
                posted_at = datetime.fromtimestamp(
                    int(created_at_ms) / 1000, tz=timezone.utc
                ).isoformat()
            except (ValueError, TypeError, OverflowError):
                posted_at = None

        workplace_type = str(categories.get("workplaceType") or "").lower()
        if workplace_type:
            is_remote = workplace_type == "remote"
        else:
            is_remote = _infer_remote_from_text(location_text)

        job: JobPosting = {
            "job_id": f"lever:{board_token}:{ats_job_id}",
            "company": company,
            "title": raw_job.get("text") or "Unknown",
            "location": location_text,
            "url": raw_job.get("hostedUrl") or "",
            "description": description,
            "source": "lever",
            "ats_job_id": ats_job_id,
            "department": department,
            "posted_at": posted_at,
            "discovered_at": now,
            "last_seen_at": now,
            "status": "new",
            "raw": raw_job,
            "location_lat": None,
            "location_lng": None,
            "is_remote": is_remote,
        }
        jobs.append(job)

    return jobs
