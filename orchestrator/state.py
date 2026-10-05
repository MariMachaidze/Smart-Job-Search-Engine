"""
orchestrator/state.py -- LangGraph state shapes for the two graphs this
workstream owns (plan section 11).

Both states carry an `errors` list that nodes append to rather than raising
on -- per-item/per-step failures should not crash the whole run (explicit in
the plan for discovery_graph's per-company failures, and extended here to
tailoring_graph's two branches for the same reason: one document generation
failing shouldn't take down the other).

`errors` uses an `Annotated[..., operator.add]` reducer because
tailoring_graph genuinely runs two branches concurrently in the same
LangGraph "superstep" (tailor_resume + generate_cover_letter). Without a
reducer, LangGraph's default merge behavior is "last writer wins" on a key,
so two concurrent branches each returning their own full error list could
silently clobber one another's errors. With `operator.add`, every node
should return only the *new* errors it produced (a delta), and LangGraph
concatenates deltas from parallel branches instead of overwriting -- so
nodes must NOT re-return the accumulated history, just what's new this node.
Discovery_graph's nodes run sequentially (no parallel writers), so this
reducer is harmless there too and keeps both state shapes consistent.
"""
import operator
from typing import Annotated, Optional, TypedDict


class DiscoveryState(TypedDict, total=False):
    user_id: str

    # storage.schemas.CompanySource records for this user, loaded by
    # load_companies.
    companies: list[dict]

    # storage.schemas.JobPosting records freshly fetched this run (one
    # discover_company_jobs call per company), before any new/seen/closed
    # diffing against jobs.json. Written by discover_jobs.
    discovered_jobs: list[dict]

    # Company names discover_jobs successfully queried this run (even if it
    # returned zero jobs for them) -- used by persist_jobs to know which
    # existing jobs are safe to mark "closed" (a company whose discovery
    # *failed* this run gives no signal either way, so its existing jobs are
    # left untouched rather than wrongly marked closed).
    succeeded_companies: list[str]

    # The full post-diff job list for every job touched this run (new +
    # seen + closed), as written back to jobs.json by persist_jobs.
    persisted_jobs: list[dict]

    # Subset of persisted_jobs that (a) aren't closed, (b) don't already
    # have a MatchScore from a previous run, and (c) survive
    # scraper.discovery.apply_hard_filters's commute/remote exclusion --
    # i.e. exactly the jobs eligible for an LLM scoring call this run.
    filtered_jobs: list[dict]

    # storage.schemas.CandidateProfile, loaded by load_profile. None if the
    # user hasn't uploaded a resume yet -- the conditional edge after
    # load_profile routes straight to END in that case, since there's
    # nothing to score against.
    profile: Optional[dict]

    # storage.schemas.MatchScore records produced (and persisted) this run.
    scored_jobs: list[dict]

    errors: Annotated[list[str], operator.add]


class TailoringState(TypedDict, total=False):
    user_id: str
    job_id: str

    # storage.schemas.JobPosting, loaded by load_job. None if job_id doesn't
    # exist for this user -- tailor_resume/generate_cover_letter no-op
    # (append an error, leave their *_doc field None) rather than crashing.
    job: Optional[dict]

    # storage.schemas.CandidateProfile, loaded by load_profile. None if the
    # user hasn't uploaded a resume yet -- same no-op behavior as above.
    profile: Optional[dict]

    # storage.schemas.GeneratedDocument, written by the two parallel
    # branches. These are two distinct keys (no concurrent-write conflict),
    # so they use LangGraph's default "last/only writer wins" merge -- no
    # reducer needed.
    resume_doc: Optional[dict]
    cover_letter_doc: Optional[dict]

    errors: Annotated[list[str], operator.add]
