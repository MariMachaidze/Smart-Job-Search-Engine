"""
Jobs / discovery / tailoring routes (workstream M, plan section 13).

  POST /discovery/run       -> invokes orchestrator.discovery_graph on demand
                                 (real Gemini calls, via matching.scorer.score_job)
  GET  /jobs                 -> jobs.json joined with scores.json, ranked by score
  POST /jobs/{id}/feedback   -> sets MatchScore.user_feedback/feedback_reason;
                                 writes a MemoryEntry when a reason is given
                                 (plan sections 5 and 12)
  POST /jobs/{id}/tailor     -> invokes orchestrator.tailoring_graph
                                 (real Gemini calls, via resume.tailor /
                                 resume.cover_letter)

*** LLM note ***: /discovery/run and /jobs/{id}/tailor both trigger real
Gemini calls through the graphs they invoke (discovery_graph -> score_job;
tailoring_graph -> tailor_resume/generate_cover_letter). That's the real,
intended pipeline -- these routes are not stubbed. The standing "no live
Gemini calls" instruction is honored in this workstream's *tests*
(test_main.py monkeypatches app.llm.call_llm only for the two tests that
exercise these two routes), not by changing anything here.
"""
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import get_current_user
from orchestrator.discovery_graph import discovery_graph
from orchestrator.tailoring_graph import tailoring_graph
from storage import json_store

router = APIRouter(tags=["jobs"])

_JOBS_ENTITY = "jobs"
_SCORES_ENTITY = "scores"
_MEMORY_ENTITY = "memory"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/discovery/run")
async def run_discovery(current_user: dict = Depends(get_current_user)):
    """Invokes orchestrator.discovery_graph.ainvoke for the current user on
    demand (plan section 11: "Manual override stays available ... invokes
    the same discovery_graph on demand, independent of the schedule").

    Returns a summary rather than the full persisted/scored job lists
    (those are available via GET /jobs) -- counts plus any per-company/
    per-job errors collected during the run (discovery_graph never raises
    on a single bad company/job, per its own error-isolation design)."""
    user_id = current_user["user_id"]
    result = await discovery_graph.ainvoke({
        "user_id": user_id,
        "companies": [],
        "discovered_jobs": [],
        "succeeded_companies": [],
        "persisted_jobs": [],
        "filtered_jobs": [],
        "profile": None,
        "scored_jobs": [],
        "errors": [],
    })
    return {
        "persisted_jobs_count": len(result.get("persisted_jobs") or []),
        "scored_jobs_count": len(result.get("scored_jobs") or []),
        "errors": result.get("errors") or [],
    }


@router.get("/jobs")
async def list_jobs(current_user: dict = Depends(get_current_user)):
    """Returns every JobPosting for this user, with its MatchScore fields
    (score, rationale, matched/missing skills, user_feedback,
    feedback_reason) joined in when one exists -- None for jobs that were
    excluded by the hard filter or haven't been scored yet. Sorted by score
    descending (unscored jobs last), matching the "ranked job list" wording
    in plan section 13's route table."""
    user_id = current_user["user_id"]
    jobs = json_store.load_all(user_id, _JOBS_ENTITY)
    scores_by_job_id = {s.get("job_id"): s for s in json_store.load_all(user_id, _SCORES_ENTITY)}

    joined = []
    for job in jobs:
        score = scores_by_job_id.get(job.get("job_id"))
        joined.append({
            **job,
            "match_id": score.get("match_id") if score else None,
            "score": score.get("score") if score else None,
            "rationale": score.get("rationale") if score else None,
            "matched_skills": score.get("matched_skills") if score else None,
            "missing_skills": score.get("missing_skills") if score else None,
            "user_feedback": score.get("user_feedback") if score else None,
            "feedback_reason": score.get("feedback_reason") if score else None,
            "scored_at": score.get("scored_at") if score else None,
        })

    joined.sort(key=lambda j: (j["score"] is None, -(j["score"] or 0)))
    return joined


class FeedbackRequest(BaseModel):
    feedback: Literal["relevant", "not_relevant"]
    reason: Optional[str] = None


@router.post("/jobs/{job_id}/feedback")
async def submit_feedback(
    job_id: str,
    body: FeedbackRequest,
    current_user: dict = Depends(get_current_user),
):
    """Sets MatchScore.user_feedback/feedback_reason for job_id. When a
    reason is given, also writes an explicit MemoryEntry (category
    "feedback") per plan section 5 ("not relevant alone tells the system
    nothing reusable, but 'not relevant -- too much travel' does ... it's
    also written as an explicit MemoryEntry so the chat agent itself
    references it in later conversation")."""
    user_id = current_user["user_id"]
    score = json_store.get_by_id(user_id, _SCORES_ENTITY, "job_id", job_id)
    if score is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No MatchScore found for this job_id -- has it been scored yet?",
        )

    score = {**score, "user_feedback": body.feedback, "feedback_reason": body.reason}
    json_store.upsert(user_id, _SCORES_ENTITY, score, "match_id")

    if body.reason:
        memory_entry = {
            "memory_id": str(uuid.uuid4()),
            "user_id": user_id,
            "category": "feedback",
            "content": f"Rated job_id={job_id} as {body.feedback}: {body.reason}",
            "created_at": _now_iso(),
            "source": f"rate_job:{job_id}",
        }
        json_store.upsert(user_id, _MEMORY_ENTITY, memory_entry, "memory_id")

    return score


@router.post("/jobs/{job_id}/tailor")
async def tailor_job(job_id: str, current_user: dict = Depends(get_current_user)):
    """Invokes orchestrator.tailoring_graph.ainvoke for one job_id -- fans
    out to tailor_resume + generate_cover_letter concurrently (workstream
    F's real parallel graph), returning whichever GeneratedDocument records
    came back plus any per-branch errors. 404s up front if the job_id
    doesn't belong to this user, rather than letting the graph's own
    load_job_node discover that and silently no-op both branches."""
    user_id = current_user["user_id"]
    job = json_store.get_by_id(user_id, _JOBS_ENTITY, "job_id", job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    result = await tailoring_graph.ainvoke({
        "user_id": user_id,
        "job_id": job_id,
        "job": None,
        "profile": None,
        "resume_doc": None,
        "cover_letter_doc": None,
        "errors": [],
    })
    return {
        "resume_doc": result.get("resume_doc"),
        "cover_letter_doc": result.get("cover_letter_doc"),
        "errors": result.get("errors") or [],
    }
