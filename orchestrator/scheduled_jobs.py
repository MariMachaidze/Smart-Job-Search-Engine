"""
orchestrator/scheduled_jobs.py -- daily batch jobs (workstream K, plan section 9).

Each `run_daily_*_for_all_users()` function iterates every registered user
(`storage.json_store.load_users()`) and calls the corresponding per-user
function owned by another, independently-built workstream:
  - qualifications.updater.update_qualifications_prompt  (workstream R, real, landed)
  - discovery_graph.ainvoke({"user_id": ...})             (workstream F)
  - notifications.digest.build_and_send_daily_digest      (workstream L, real, landed)

Workstream F's `orchestrator/discovery_graph.py` had not landed yet when
this module was first written. Per the plan's section 11 contract,
`discovery_graph` is a compiled LangGraph `StateGraph` invoked as
`await discovery_graph.ainvoke({"user_id": ...})` -- an object exposing an
async `ainvoke(state: dict) -> dict`. Until the real module showed up on
disk, a local stand-in (`_StubDiscoveryGraph` below) matching exactly that
shape was used instead. The import is defensive (try/except ImportError),
mirroring the pattern `qualifications/updater.py` used for `stats.skill_gap`
and `tracker.service` while those workstreams were still in flight.

F's `discovery_graph.py` landed mid-task. Once it did, this was verified
directly (not just assumed) against the real compiled graph:
  - `await discovery_graph.ainvoke({"user_id": uid})` -- the exact bare-dict
    call shape this module uses, matching the plan's pseudocode -- runs
    successfully against the real graph. LangGraph tolerates the
    `DiscoveryState` TypedDict's other keys (companies, discovered_jobs,
    etc., all `total=False`) being absent from the initial dict, even with
    the `errors: Annotated[list[str], operator.add]` reducer field unset;
    F's own `orchestrator/run_discovery.py` CLI happens to pass a
    fully-keyed initial state instead, but that turned out to be a style
    choice, not a requirement -- both forms were run side by side against a
    throwaway user and produced equivalent results.
  - F's nodes already catch and collect per-company/per-job failures into
    `state["errors"]` internally (discover_jobs_node, persist_jobs_node,
    apply_hard_filters_node, score_jobs_node all wrap their risky calls), so
    a single bad company does NOT raise out of `ainvoke` -- this module's
    outer try/except is a second line of defense for failures F's nodes
    don't already swallow (e.g. a corrupted companies.json causing
    `json.JSONDecodeError` inside `load_companies_node`, which has no
    internal try/except since reading the user's own data isn't expected to
    fail the way a third-party network call is) -- confirmed by actually
    corrupting a test user's companies.json and observing `ainvoke` raise.

The `_StubDiscoveryGraph` fallback below is kept (not deleted) for the same
reason `qualifications/updater.py` keeps its `stats.skill_gap`/
`tracker.service` fallbacks even after those landed: defensive, in case this
module is ever imported before `orchestrator/discovery_graph.py` again
(e.g. a partial checkout).

Per-user errors are caught and logged, never allowed to abort the loop --
one user's bad data or a network blip must not stop the rest of the batch
from running. That isolation is the one piece of real logic this module
owns; the three per-user calls themselves are just delegation to other
workstreams' functions.
"""
import logging

from notifications.digest import build_and_send_daily_digest
from qualifications.updater import update_qualifications_prompt
from storage import json_store

logger = logging.getLogger(__name__)


class _StubDiscoveryGraph:
    """Stand-in for the real compiled `orchestrator.discovery_graph` LangGraph
    object (workstream F), used only until that module lands on disk.

    Matches the documented interface from plan section 11: an object with an
    async `ainvoke(state: dict) -> dict` that (per the real graph's intended
    pipeline) runs `load_companies -> discover_jobs -> persist_jobs ->
    apply_hard_filters -> load_profile -> score_jobs`.

    This stand-in does no real network/scraping/LLM work -- it only
    exercises the one thing orchestrator/scheduled_jobs.py actually needs to
    get right independent of F's internals: iterating a user's companies and
    raising if a company record is malformed (e.g. missing "careers_url"),
    so this module's per-user error isolation can be verified against a
    realistic failure mode without waiting on the real graph or making live
    HTTP calls.
    """

    async def ainvoke(self, state: dict) -> dict:
        user_id = state["user_id"]
        companies = json_store.load_all(user_id, "companies")
        discovered = 0
        for company in companies:
            # The real discover_jobs node would call
            # scraper.discovery.discover_company_jobs(...) here; this stand-in
            # just validates the shape, so a malformed company record fails
            # the same way a real ATS/network error would -- loudly, as an
            # exception the caller must isolate per-user.
            _ = company["careers_url"]
            discovered += 1
        return {"user_id": user_id, "companies_processed": discovered}


try:
    # Real implementation, once workstream F (LangGraph Orchestrator) lands.
    from orchestrator.discovery_graph import discovery_graph
except ImportError:  # pragma: no cover - only hit if discovery_graph.py isn't present yet
    discovery_graph = _StubDiscoveryGraph()
    logger.info(
        "orchestrator.discovery_graph not found on disk (workstream F not landed yet) -- "
        "using local _StubDiscoveryGraph stand-in matching the documented ainvoke(state) contract."
    )


async def run_daily_qualifications_update_for_all_users() -> None:
    """Regenerates every user's QualificationsProfile. Scheduled first
    (hour=5) so the fresh prompt is ready before that day's discovery/scoring
    run reads it."""
    for user in json_store.load_users():
        user_id = user.get("user_id")
        try:
            update_qualifications_prompt(user_id)
        except Exception:
            logger.exception(
                "run_daily_qualifications_update_for_all_users: failed for user_id=%s, "
                "continuing with remaining users",
                user_id,
            )


async def run_daily_discovery_for_all_users() -> None:
    """Runs job discovery for every user via the (real, once F lands, or
    stand-in) discovery_graph."""
    for user in json_store.load_users():
        user_id = user.get("user_id")
        try:
            await discovery_graph.ainvoke({"user_id": user_id})
        except Exception:
            logger.exception(
                "run_daily_discovery_for_all_users: failed for user_id=%s, "
                "continuing with remaining users",
                user_id,
            )


async def run_daily_digest_for_all_users() -> None:
    """Sends the daily relevant-but-unapplied digest to every user who
    hasn't opted out. `build_and_send_daily_digest` is itself already a
    no-op when there's nothing to report or the recipient is unknown; the
    `digest_enabled` check here additionally short-circuits the call
    entirely for opted-out accounts, matching the plan's pseudocode."""
    for user in json_store.load_users():
        if not user.get("digest_enabled", True):
            continue
        user_id = user.get("user_id")
        try:
            build_and_send_daily_digest(user_id)
        except Exception:
            logger.exception(
                "run_daily_digest_for_all_users: failed for user_id=%s, "
                "continuing with remaining users",
                user_id,
            )
