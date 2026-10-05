"""
orchestrator/discovery_graph.py -- Graph 1 (plan section 11), owned by
workstream F.

    load_companies -> discover_jobs -> persist_jobs (diff by job_id:
    new/seen/closed, geocode each NEW job) -> apply_hard_filters ->
    load_profile -> [conditional: has profile?] -> score_jobs -> END

Every real dependency here is read from the actual modules other
workstreams built (not stubs):
  - storage.json_store / storage.schemas         (workstream A)
  - scraper.discovery.discover_company_jobs, enrich_job_location,
    apply_hard_filters                            (workstream B)
  - matching.scorer.score_job                     (workstream D)
  - qualifications.updater.get_latest_qualifications (workstream R)

Playwright tradeoff (see plan's instructions to this workstream): this
graph always opens `async_playwright() as playwright` for the duration of
discover_jobs, regardless of whether any company actually needs the
Playwright-scraper fallback. This turns out to be cheap rather than an
over-engineering tradeoff to fix: `async_playwright()` only starts the
lightweight Playwright driver process -- it does NOT launch a browser.
Looking at scraper/discovery.py confirms the actual expensive step,
`playwright.chromium.launch(...)`, only happens inside
`_discover_via_scraper`, i.e. only for companies that fall through to the
Workday/unknown-ATS fallback path, same as `discover_company_jobs`'s own
docstring. So the "don't start a browser unless something needs it"
optimization the plan asks about is already effectively in place one layer
down (per-company, inside workstream B's code) without this graph needing
to pre-resolve each company's ATS a second time (which would mean two
network round-trips per company -- once to decide, once for real -- for no
real savings, since the driver process itself is cheap to start).

Error handling: per-company discover_jobs failures and per-job scoring
failures are caught and appended to state["errors"] rather than raised, so
one bad company/job never aborts the whole run (explicit in the plan for
discovery; this module also catches around hard-filter and geocoding steps
for the same reason).
"""
import asyncio
from datetime import datetime, timezone
from typing import Optional

from langgraph.graph import END, StateGraph
from playwright.async_api import async_playwright

from matching.scorer import score_job
from qualifications.updater import get_latest_qualifications
from scraper.discovery import apply_hard_filters, discover_company_jobs, enrich_job_location
from storage import json_store

from orchestrator.state import DiscoveryState

# Nominatim's usage policy caps anonymous use at ~1 request/second (see
# geocoding/client.py's docstring). enrich_job_location() does nothing for
# a job that's already geocoded or is remote/unresolvable, so this pause is
# only paid for jobs that actually trigger a real network geocode call.
_GEOCODE_PACING_SECONDS = 1.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

async def load_companies_node(state: DiscoveryState) -> dict:
    user_id = state["user_id"]
    companies = json_store.load_all(user_id, "companies")
    return {"companies": companies}


async def discover_jobs_node(state: DiscoveryState) -> dict:
    """Runs scraper.discovery.discover_company_jobs for every company this
    user has configured. A single `async_playwright()` context is shared
    across all companies this run (see module docstring on why this is
    cheap even for companies that never touch the fallback path)."""
    companies = state.get("companies") or []
    new_errors: list[str] = []
    discovered: list[dict] = []
    succeeded_companies: list[str] = []

    async with async_playwright() as playwright:
        for company in companies:
            name = company.get("company")
            careers_url = company.get("careers_url")
            try:
                jobs = await discover_company_jobs(playwright, name, careers_url)
            except Exception as exc:  # noqa: BLE001 - deliberate: never let one company abort the run
                new_errors.append(
                    f"discover_jobs: company={name!r} careers_url={careers_url!r} failed: {exc}"
                )
                print(f"[orchestrator.discovery_graph] {new_errors[-1]}")
                continue
            discovered.extend(jobs)
            succeeded_companies.append(name)

    return {
        "discovered_jobs": discovered,
        "succeeded_companies": succeeded_companies,
        "errors": new_errors,
    }


async def persist_jobs_node(state: DiscoveryState) -> dict:
    """Diffs discovered_jobs against the existing jobs.json by job_id and
    writes back the merged status new/seen/closed, per plan sections 1/3a:
      - job_id in discovered but not previously stored -> status "new",
        geocoded once (enrich_job_location), discovered_at/last_seen_at=now.
      - job_id in both -> status "seen", last_seen_at refreshed, but
        discovered_at and any already-geocoded coordinates are preserved
        from the existing record (never re-geocode, never re-stamp
        discovered_at).
      - job_id previously stored but NOT in this run's discovered set, for
        a company that *successfully* resolved this run -> status "closed"
        (record kept, never deleted).
      - job_id previously stored, belonging to a company whose discovery
        FAILED this run -> left completely untouched (no signal either way,
        see state["succeeded_companies"]).
    """
    user_id = state["user_id"]
    discovered = state.get("discovered_jobs") or []
    succeeded_companies = set(state.get("succeeded_companies") or [])
    new_errors: list[str] = []

    existing_jobs = json_store.load_all(user_id, "jobs")
    existing_by_id = {j["job_id"]: j for j in existing_jobs}
    discovered_by_id = {j["job_id"]: j for j in discovered}

    now = _now_iso()
    merged: list[dict] = []
    # Tracks whether a REAL network geocode call has happened yet in this
    # node's run, independent of how many remote/already-geocoded jobs (which
    # never touch the network) are interspersed between network calls -- see
    # _enrich_with_pacing below.
    pacer = {"made_network_call": False}

    async def _enrich_with_pacing(job: dict) -> None:
        """Wraps enrich_job_location with Nominatim pacing (see
        geocoding/client.py's ~1 req/sec usage-policy docstring). Determines
        whether this call WILL hit the network using the same short-circuit
        conditions enrich_job_location itself checks (already geocoded,
        remote, empty/placeholder location text) so pacing is applied
        between real network calls only, never between two cache-hit/no-op
        calls regardless of what's interleaved between them."""
        already_has_coords = job.get("location_lat") is not None and job.get("location_lng") is not None
        location_text = (job.get("location") or "").strip().lower()
        will_hit_network = (
            not already_has_coords
            and not job.get("is_remote")
            and location_text not in ("", "unknown", "error")
        )
        if will_hit_network and pacer["made_network_call"]:
            await asyncio.sleep(_GEOCODE_PACING_SECONDS)
        enrich_job_location(job)
        if will_hit_network:
            pacer["made_network_call"] = True

    for job_id, fresh in discovered_by_id.items():
        existing = existing_by_id.get(job_id)

        if existing is None:
            fresh = dict(fresh)
            fresh["status"] = "new"
            try:
                await _enrich_with_pacing(fresh)
            except Exception as exc:  # noqa: BLE001
                new_errors.append(f"persist_jobs: geocoding failed for job_id={job_id!r}: {exc}")
            merged.append(fresh)
        else:
            updated = dict(fresh)
            updated["status"] = "seen"
            updated["discovered_at"] = existing.get("discovered_at", fresh.get("discovered_at"))
            updated["last_seen_at"] = now
            if existing.get("location_lat") is not None and existing.get("location_lng") is not None:
                updated["location_lat"] = existing["location_lat"]
                updated["location_lng"] = existing["location_lng"]
            else:
                try:
                    await _enrich_with_pacing(updated)
                except Exception as exc:  # noqa: BLE001
                    new_errors.append(f"persist_jobs: geocoding failed for job_id={job_id!r}: {exc}")
            merged.append(updated)

    for job_id, existing in existing_by_id.items():
        if job_id in discovered_by_id:
            continue  # already handled above
        if existing.get("company") in succeeded_companies:
            closed = dict(existing)
            closed["status"] = "closed"
            merged.append(closed)
        else:
            merged.append(existing)

    json_store.save_all(user_id, "jobs", merged)
    return {"persisted_jobs": merged, "errors": new_errors}


async def apply_hard_filters_node(state: DiscoveryState) -> dict:
    """Runs scraper.discovery.apply_hard_filters (plan section 3a) between
    persist_jobs and score_jobs, and also excludes closed jobs and jobs that
    already have a MatchScore from a previous run -- scoring is a paid LLM
    call per job, so (like geocoding) it's only spent once per job, not
    re-spent on every daily run for a job that hasn't changed."""
    user_id = state["user_id"]
    persisted = state.get("persisted_jobs") or []
    new_errors: list[str] = []

    preferences = _load_preferences(user_id)

    existing_scores = json_store.load_all(user_id, "scores")
    already_scored_ids = {s.get("job_id") for s in existing_scores}

    candidates = [
        job
        for job in persisted
        if job.get("status") != "closed" and job.get("job_id") not in already_scored_ids
    ]

    try:
        filtered = apply_hard_filters(candidates, preferences)
    except Exception as exc:  # noqa: BLE001
        new_errors.append(f"apply_hard_filters failed, scoring all candidates unfiltered: {exc}")
        filtered = candidates

    return {"filtered_jobs": filtered, "errors": new_errors}


async def load_profile_node(state: DiscoveryState) -> dict:
    user_id = state["user_id"]
    profile = json_store.load_profile(user_id)
    return {"profile": profile}


def _has_profile(state: DiscoveryState) -> str:
    """Conditional edge after load_profile: plan section 11 -- "[conditional:
    has profile?]". No profile yet (user hasn't uploaded a resume) means
    there's nothing to score against, so the run ends here rather than
    calling score_jobs with no CandidateProfile."""
    return "score_jobs" if state.get("profile") else END


async def score_jobs_node(state: DiscoveryState) -> dict:
    """One matching.scorer.score_job call per filtered job, preferring the
    latest synthesized qualifications prompt (workstream R) over the raw
    profile when one exists (plan section 8a). Each MatchScore is persisted
    immediately via json_store.upsert so a mid-run failure doesn't lose
    already-scored jobs."""
    user_id = state["user_id"]
    profile = state.get("profile")
    jobs = state.get("filtered_jobs") or []
    new_errors: list[str] = []
    scored: list[dict] = []

    qualifications = get_latest_qualifications(user_id)
    qualifications_prompt: Optional[str] = (
        qualifications.get("prompt_text") if qualifications else None
    )

    for job in jobs:
        try:
            match = score_job(profile, job, qualifications_prompt=qualifications_prompt)
            json_store.upsert(user_id, "scores", match, "match_id")
            scored.append(match)
        except Exception as exc:  # noqa: BLE001
            new_errors.append(f"score_jobs: job_id={job.get('job_id')!r} failed: {exc}")
            continue

    return {"scored_jobs": scored, "errors": new_errors}


# ---------------------------------------------------------------------------
# Preferences loading
# ---------------------------------------------------------------------------

def _load_preferences(user_id: str) -> dict:
    """UserPreferences (plan section 1/3a) doesn't have a dedicated owning
    module yet -- no other workstream has landed `/preferences` routes or a
    storage helper as of this writing. Reads the "preferences" entity
    directly via json_store (consistent with storage/paths.py's own
    docstring, which already lists "preferences" among the entity names
    user_entity_path expects) and takes the first record found for this
    user. Falls back to a conservative default (no commute limit, no remote
    requirement, not willing to relocate) when nothing has been set yet --
    which, per apply_hard_filters's own docstring, means nothing gets
    excluded until the user actually sets a preference."""
    records = json_store.load_all(user_id, "preferences")
    if records:
        return records[0]
    return {
        "user_id": user_id,
        "home_location": None,
        "home_lat": None,
        "home_lng": None,
        "max_commute_km": None,
        "remote_preference": "no_preference",
        "willing_to_relocate": False,
        "updated_at": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_discovery_graph():
    graph = StateGraph(DiscoveryState)

    graph.add_node("load_companies", load_companies_node)
    graph.add_node("discover_jobs", discover_jobs_node)
    graph.add_node("persist_jobs", persist_jobs_node)
    graph.add_node("apply_hard_filters", apply_hard_filters_node)
    graph.add_node("load_profile", load_profile_node)
    graph.add_node("score_jobs", score_jobs_node)

    graph.set_entry_point("load_companies")
    graph.add_edge("load_companies", "discover_jobs")
    graph.add_edge("discover_jobs", "persist_jobs")
    graph.add_edge("persist_jobs", "apply_hard_filters")
    graph.add_edge("apply_hard_filters", "load_profile")
    graph.add_conditional_edges(
        "load_profile", _has_profile, {"score_jobs": "score_jobs", END: END}
    )
    graph.add_edge("score_jobs", END)

    return graph.compile()


discovery_graph = build_discovery_graph()
