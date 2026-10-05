"""
orchestrator/tailoring_graph.py -- Graph 2 (plan section 11), owned by
workstream F.

    load_job -> load_profile -> fan out to tailor_resume + generate_cover_letter
    (real concurrent branches) -> join -> END

Real parallel branches, not a sequential fake: `load_profile` has TWO
outgoing edges (to `tailor_resume` and to `cover_letter`), and `join` has
two incoming edges. LangGraph's Pregel-style executor runs every node whose
dependencies are satisfied within the same "superstep" concurrently when
invoked via `ainvoke`/`astream` -- both branch nodes here are scheduled as
concurrent asyncio tasks in the same superstep, and each wraps its
underlying blocking call (`resume.tailor.tailor_resume` /
`resume.cover_letter.generate_cover_letter`, both synchronous `call_llm`
invocations) in `asyncio.to_thread(...)` specifically so the two Gemini
calls actually overlap in wall-clock time rather than one blocking the
event loop while the other waits.

Error handling: rather than a conditional "has job?"/"has profile?" edge
that short-circuits the whole graph to END (which would also skip the
*other* branch even if it could have succeeded), load_job/load_profile are
unconditional and the two branch nodes each independently guard against a
missing job/profile -- if either is missing, that branch no-ops (appends an
error, leaves its own *_doc field None) rather than crashing, consistent
with this codebase's "per-item errors logged, not fatal" convention
(scraper/discovery.py's per-company catch, matching/scorer.py's per-job
catch). This also means a single job missing doesn't need two separate
"skip" paths -- both branches reach the same conclusion independently.

Real-concurrency finding worth flagging for workstream A: running these two
branches as genuinely concurrent threads (not sequential/fake) surfaced a
real race in storage.json_store.upsert. Both tailor_resume() and
generate_cover_letter() independently call
`json_store.upsert(user_id, "documents", record, "document_id")` against
the SAME documents.json file. json_store's atomic-write pattern (write a
shared `<path>.tmp` sibling, then `os.replace` it into place) is not safe
against two threads doing this for the same path at (near) the same
instant: thread A writes `documents.json.tmp`, thread B immediately
overwrites the same `.tmp` path with its own content and renames it away,
and thread A's own subsequent `os.replace` then fails with
`FileNotFoundError` because its `.tmp` file was already consumed by B's
rename. This was observed live during this workstream's own end-to-end
test (orchestrator/test_graphs.py) -- confirming the fan-out here is
genuinely concurrent (a sequential-but-labeled-parallel implementation
would never trigger this), but also exposing a real cross-workstream bug.
Since storage/json_store.py isn't this workstream's file to modify, the
mitigation lives here instead: each branch retries its underlying call
ONCE, after a small jittered delay, specifically on this failure signature
(a FileNotFoundError mentioning the shared `.tmp` suffix) before giving up
and logging an error -- a second collision on the same two ~millisecond
write windows is exceedingly unlikely. This does mean a retry re-runs the
*entire* tailor_resume/generate_cover_letter call (a fresh LLM call +
re-render + re-upload), which is wasteful but correct; a proper fix
belongs in storage/json_store.py (e.g. a per-path lock), and should be
raised with workstream A.
"""
import asyncio
import random

from langgraph.graph import END, StateGraph

from resume.cover_letter import generate_cover_letter
from resume.tailor import tailor_resume
from storage import json_store

from orchestrator.state import TailoringState


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

async def load_job_node(state: TailoringState) -> dict:
    user_id = state["user_id"]
    job_id = state["job_id"]
    job = json_store.get_by_id(user_id, "jobs", "job_id", job_id)
    if job is None:
        return {"job": None, "errors": [f"load_job: no job found for job_id={job_id!r}"]}
    return {"job": job}


async def load_profile_node(state: TailoringState) -> dict:
    user_id = state["user_id"]
    profile = json_store.load_profile(user_id)
    if profile is None:
        return {
            "profile": None,
            "errors": [f"load_profile: no CandidateProfile found for user_id={user_id!r}"],
        }
    return {"profile": profile}


def _is_concurrent_json_store_write_race(exc: Exception) -> bool:
    """Heuristic for the storage.json_store.upsert race documented in this
    module's docstring: two threads concurrently upserting into the same
    user+entity JSON file can make one thread's `os.replace(tmp, path)`
    fail with FileNotFoundError because the other thread's own replace
    already consumed/renamed away the shared `.tmp` sibling."""
    return isinstance(exc, FileNotFoundError) and ".tmp" in str(exc)


async def tailor_resume_node(state: TailoringState) -> dict:
    job = state.get("job")
    profile = state.get("profile")
    if not job or not profile:
        return {
            "resume_doc": None,
            "errors": ["tailor_resume: skipped (missing job or profile)"],
        }
    try:
        doc = await asyncio.to_thread(tailor_resume, state["user_id"], profile, job)
        return {"resume_doc": doc}
    except Exception as exc:  # noqa: BLE001 - one branch failing must not sink the other
        if _is_concurrent_json_store_write_race(exc):
            await asyncio.sleep(random.uniform(0.05, 0.2))
            try:
                doc = await asyncio.to_thread(tailor_resume, state["user_id"], profile, job)
                return {"resume_doc": doc}
            except Exception as retry_exc:  # noqa: BLE001
                exc = retry_exc
        return {
            "resume_doc": None,
            "errors": [f"tailor_resume failed for job_id={job.get('job_id')!r}: {exc}"],
        }


async def cover_letter_node(state: TailoringState) -> dict:
    job = state.get("job")
    profile = state.get("profile")
    if not job or not profile:
        return {
            "cover_letter_doc": None,
            "errors": ["generate_cover_letter: skipped (missing job or profile)"],
        }
    try:
        doc = await asyncio.to_thread(generate_cover_letter, state["user_id"], profile, job)
        return {"cover_letter_doc": doc}
    except Exception as exc:  # noqa: BLE001
        if _is_concurrent_json_store_write_race(exc):
            await asyncio.sleep(random.uniform(0.05, 0.2))
            try:
                doc = await asyncio.to_thread(generate_cover_letter, state["user_id"], profile, job)
                return {"cover_letter_doc": doc}
            except Exception as retry_exc:  # noqa: BLE001
                exc = retry_exc
        return {
            "cover_letter_doc": None,
            "errors": [f"generate_cover_letter failed for job_id={job.get('job_id')!r}: {exc}"],
        }


async def join_node(state: TailoringState) -> dict:
    """No-op merge point: both branches already wrote their own *_doc field
    directly into state by the time this node runs (LangGraph only runs a
    node once every edge into it has been satisfied), so there's nothing
    left to combine -- this node exists purely to give the fan-out a single
    place to converge before END, per the plan's explicit graph shape."""
    return {}


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_tailoring_graph():
    graph = StateGraph(TailoringState)

    graph.add_node("load_job", load_job_node)
    graph.add_node("load_profile", load_profile_node)
    graph.add_node("tailor_resume", tailor_resume_node)
    graph.add_node("cover_letter", cover_letter_node)
    graph.add_node("join", join_node)

    graph.set_entry_point("load_job")
    graph.add_edge("load_job", "load_profile")

    # Fan out: two outgoing edges from the same node -> both branches run
    # concurrently in the same superstep.
    graph.add_edge("load_profile", "tailor_resume")
    graph.add_edge("load_profile", "cover_letter")

    # Fan in: two incoming edges into "join" -> it runs once both branches
    # have completed.
    graph.add_edge("tailor_resume", "join")
    graph.add_edge("cover_letter", "join")

    graph.add_edge("join", END)

    return graph.compile()


tailoring_graph = build_tailoring_graph()
