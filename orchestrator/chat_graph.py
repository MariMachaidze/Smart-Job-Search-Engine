"""
orchestrator/chat_graph.py -- Graph 3 (plan section 11), workstream H.

A Gemini **native** function-calling loop over every tool listed in plan
section 11, each wired to the REAL underlying function other workstreams
built (discovery_graph/tailoring_graph, tracker.service, stats.aggregator/
skill_gap, qualifications.updater, rag.retriever, geocoding.client,
storage.json_store). This is deliberately NOT `app.llm.call_llm` (a plain
text-prompt wrapper) -- the loop needs google-genai's structured
FunctionDeclaration/Tool/FunctionCall/FunctionResponse plumbing, not a text
response to parse by hand.

*** STANDING CONSTRAINT -- READ BEFORE CHANGING ANYTHING GEMINI-RELATED ***
The user has a standing instruction that NO live Gemini API calls happen
right now (independent of whether the free-tier quota has reset -- this is
a hold, not a quota workaround). Every call this module makes to
`google.genai.Client.models.generate_content` is therefore implemented for
REAL (see below) but has only ever been exercised in this codebase against
MOCKED `google.genai.types.GenerateContentResponse` objects --
specifically, REAL `types.Candidate`/`types.Content`/`types.Part` instances
constructed the way the SDK itself builds them (verified by reading
google-genai==2.28.0's own installed source: `types.py`'s
`FunctionDeclaration`/`FunctionCall`/`FunctionResponse`/`Part` classes, and
`chats.py`/`_extra_utils.py`'s own automatic-function-calling loop, which
appends `response.candidates[0].content` then a
`types.Content(role="user", parts=func_response_parts)` turn -- exactly the
pattern `run_chat_turn` below follows manually since tool execution here
needs to go through this codebase's real functions, not AFC's generic
python-callable dispatch). See orchestrator/test_chat_graph.py for the
mock-construction notes. **This has NOT been proven against the real
Gemini API** -- re-verify end-to-end once the hold is lifted.

Everything downstream of the Gemini call itself (every tool handler below)
is real and is tested live against real storage/tracker/stats/qualifications
modules in orchestrator/test_chat_graph.py -- only the
`client.models.generate_content` call is ever mocked.
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types

from geocoding.client import geocode
from orchestrator.discovery_graph import discovery_graph
from orchestrator.tailoring_graph import tailoring_graph
from qualifications.updater import get_latest_qualifications, update_qualifications_prompt
from stats import aggregator as stats_aggregator
from stats import skill_gap as stats_skill_gap
from storage import json_store
from tracker import service as tracker_service
from rag.retriever import retrieve_relevant_chunks

load_dotenv()

MODEL_NAME = "gemini-2.5-flash"
MAX_TOOL_ITERATIONS = 10

_VALID_MEMORY_CATEGORIES = ("preference", "feedback", "fact")
_VALID_FEEDBACK = ("relevant", "not_relevant")
_VALID_REMOTE_PREFERENCES = ("remote_only", "hybrid_ok", "onsite_ok", "no_preference")

_PREFERENCES_ENTITY = "preferences"
_DEFAULT_PREFERENCE_FIELDS = {
    "home_location": None,
    "home_lat": None,
    "home_lng": None,
    "max_commute_km": None,
    "remote_preference": "no_preference",
    "willing_to_relocate": False,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Gemini client (lazy -- never constructed at import time, and always
# injectable, so nothing in this module ever needs a real GEMINI_API_KEY to
# be imported or unit-tested; see module docstring on the standing hold).
# ---------------------------------------------------------------------------

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _client


# ---------------------------------------------------------------------------
# save_memory -- the reusable helper the plan calls out as not yet built by
# anyone else. Used both by the save_memory tool itself and by rate_job's
# "write a MemoryEntry when a reason is given" logic (plan sections 5/12).
# ---------------------------------------------------------------------------

def save_memory(user_id: str, content: str, category: str = "fact", source: Optional[str] = None) -> dict:
    """Creates and persists a storage.schemas.MemoryEntry. Raises ValueError
    for an invalid category rather than silently coercing it, since a typo'd
    category would otherwise corrupt data qualifications/updater.py later
    reads and trusts."""
    if category not in _VALID_MEMORY_CATEGORIES:
        raise ValueError(
            f"category must be one of {_VALID_MEMORY_CATEGORIES}, got {category!r}"
        )
    entry = {
        "memory_id": str(uuid.uuid4()),
        "user_id": user_id,
        "category": category,
        "content": content,
        "created_at": _now_iso(),
        "source": source,
    }
    json_store.upsert(user_id, "memory", entry, "memory_id")
    return entry


# ---------------------------------------------------------------------------
# Tool handlers -- one async function per tool, each `(user_id, args) -> dict`.
# All exceptions propagate to run_chat_turn's per-call try/except, which
# turns them into `{"error": str(exc)}` FunctionResponses rather than
# aborting the whole turn (one bad tool call must not kill the conversation).
# ---------------------------------------------------------------------------

async def _tool_run_discovery(user_id: str, args: dict) -> dict:
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
    persisted = result.get("persisted_jobs") or []
    return {
        "new_jobs_count": sum(1 for j in persisted if j.get("status") == "new"),
        "persisted_jobs_count": len(persisted),
        "scored_jobs_count": len(result.get("scored_jobs") or []),
        "errors": result.get("errors") or [],
    }


async def _tool_list_jobs(user_id: str, args: dict) -> dict:
    filt = args.get("filter") or {}
    jobs = json_store.load_all(user_id, "jobs")
    scores_by_job_id = {s.get("job_id"): s for s in json_store.load_all(user_id, "scores")}

    joined = []
    for job in jobs:
        score = scores_by_job_id.get(job.get("job_id"))
        joined.append({
            **job,
            "score": score.get("score") if score else None,
            "rationale": score.get("rationale") if score else None,
            "matched_skills": score.get("matched_skills") if score else None,
            "missing_skills": score.get("missing_skills") if score else None,
            "user_feedback": score.get("user_feedback") if score else None,
            "feedback_reason": score.get("feedback_reason") if score else None,
        })

    status_filter = filt.get("status")
    if status_filter:
        joined = [j for j in joined if j.get("status") == status_filter]
    company_filter = filt.get("company")
    if company_filter:
        joined = [j for j in joined if (j.get("company") or "").lower() == company_filter.lower()]
    min_score = filt.get("min_score")
    if min_score is not None:
        joined = [j for j in joined if (j.get("score") or 0) >= min_score]

    joined.sort(key=lambda j: (j["score"] is None, -(j["score"] or 0)))
    return {"jobs": joined, "count": len(joined)}


async def _tool_get_job(user_id: str, args: dict) -> dict:
    job_id = args["job_id"]
    job = json_store.get_by_id(user_id, "jobs", "job_id", job_id)
    if job is None:
        raise ValueError(f"No job found with job_id={job_id!r}")
    score = json_store.get_by_id(user_id, "scores", "job_id", job_id)
    return {"job": job, "score": score}


async def _tool_rate_job(user_id: str, args: dict) -> dict:
    """Upserts MatchScore.user_feedback/feedback_reason for job_id -- unlike
    the REST route (app/routes_jobs.py:submit_feedback), which 404s if no
    MatchScore exists yet, this tool creates a placeholder MatchScore when
    none exists (score=0.0, empty rationale) rather than failing: a chat
    conversation can reasonably reference a job that was hard-filtered out
    or never scored, and the feedback is still worth recording either way.
    When `reason` is given, also writes an explicit MemoryEntry (category
    "feedback") per plan sections 5/12."""
    job_id = args["job_id"]
    feedback = args["feedback"]
    reason = args.get("reason")
    if feedback not in _VALID_FEEDBACK:
        raise ValueError(f"feedback must be one of {_VALID_FEEDBACK}, got {feedback!r}")

    existing = json_store.get_by_id(user_id, "scores", "job_id", job_id)
    if existing is not None:
        record = {**existing, "user_feedback": feedback, "feedback_reason": reason}
    else:
        profile = json_store.load_profile(user_id)
        record = {
            "match_id": str(uuid.uuid4()),
            "job_id": job_id,
            "profile_id": (profile or {}).get("profile_id", ""),
            "score": 0.0,
            "rationale": "No automated score on file for this job -- this MatchScore "
                         "was created directly by the rate_job chat tool.",
            "matched_skills": [],
            "missing_skills": [],
            "scored_at": _now_iso(),
            "user_feedback": feedback,
            "feedback_reason": reason,
        }
    json_store.upsert(user_id, "scores", record, "match_id")

    memory_entry = None
    if reason:
        memory_entry = save_memory(
            user_id,
            content=f"Rated job_id={job_id} as {feedback}: {reason}",
            category="feedback",
            source=f"rate_job:{job_id}",
        )

    return {"match_score": record, "memory_entry": memory_entry}


async def _tool_tailor_resume_for_job(user_id: str, args: dict) -> dict:
    job_id = args["job_id"]
    result = await tailoring_graph.ainvoke({
        "user_id": user_id,
        "job_id": job_id,
        "job": None,
        "profile": None,
        "resume_doc": None,
        "cover_letter_doc": None,
        "errors": [],
    })
    return {"resume_document": result.get("resume_doc"), "errors": result.get("errors") or []}


async def _tool_generate_cover_letter_for_job(user_id: str, args: dict) -> dict:
    # tailoring_graph unconditionally fans out to BOTH branches (plan's fixed
    # graph shape -- there's no way to run only one), so this and
    # tailor_resume_for_job both invoke it; each just surfaces its own half
    # of the result to keep the two tool contracts narrow for the model. No
    # extra cost either way: one graph invocation produces both documents.
    job_id = args["job_id"]
    result = await tailoring_graph.ainvoke({
        "user_id": user_id,
        "job_id": job_id,
        "job": None,
        "profile": None,
        "resume_doc": None,
        "cover_letter_doc": None,
        "errors": [],
    })
    return {"cover_letter_document": result.get("cover_letter_doc"), "errors": result.get("errors") or []}


async def _tool_get_profile(user_id: str, args: dict) -> dict:
    profile = json_store.load_profile(user_id)
    if profile is None:
        return {"profile": None, "message": "No resume/profile has been uploaded yet."}
    return {"profile": profile}


async def _tool_list_companies(user_id: str, args: dict) -> dict:
    return {"companies": json_store.load_all(user_id, "companies")}


async def _tool_add_company(user_id: str, args: dict) -> dict:
    record = {
        "company_id": str(uuid.uuid4()),
        "user_id": user_id,
        "company": args["name"],
        "careers_url": args["url"],
        "added_at": _now_iso(),
    }
    json_store.upsert(user_id, "companies", record, "company_id")
    return {"company": record}


async def _tool_remove_company(user_id: str, args: dict) -> dict:
    company_id = args["company_id"]
    companies = json_store.load_all(user_id, "companies")
    remaining = [c for c in companies if c.get("company_id") != company_id]
    if len(remaining) == len(companies):
        raise ValueError(f"No company {company_id!r} found for this user.")
    json_store.save_all(user_id, "companies", remaining)
    return {"removed_company_id": company_id}


async def _tool_mark_applied(user_id: str, args: dict) -> dict:
    job_id = args["job_id"]
    status_label = args.get("status_label") or "Applied"
    referred_by = args.get("referred_by") or ""
    comments = args.get("comments") or ""
    date_applied = datetime.now(timezone.utc).date().isoformat()
    try:
        application = tracker_service.create_application(
            user_id, job_id, status_label, date_applied,
            referred_by=referred_by, comments=comments,
        )
    except tracker_service.StatusLabelNotFoundError as exc:
        raise ValueError(str(exc)) from exc
    return {"application": application}


async def _tool_update_application_status(user_id: str, args: dict) -> dict:
    try:
        application = tracker_service.update_application_status(
            user_id, args["application_id"], args["status_label"]
        )
    except (tracker_service.ApplicationNotFoundError, tracker_service.StatusLabelNotFoundError) as exc:
        raise ValueError(str(exc)) from exc
    return {"application": application}


async def _tool_list_applications(user_id: str, args: dict) -> dict:
    filt = args.get("filter") or {}
    applications = tracker_service.list_applications(user_id)
    status_label = filt.get("status_label")
    if status_label:
        applications = [a for a in applications if a.get("status_label") == status_label]
    return {"applications": applications, "count": len(applications)}


async def _tool_get_statistics(user_id: str, args: dict) -> dict:
    granularity = args.get("granularity") or "daily"
    if granularity not in ("daily", "monthly"):
        raise ValueError(f"granularity must be 'daily' or 'monthly', got {granularity!r}")
    return {
        "summary": stats_aggregator.compute_summary(user_id),
        "status_counts": stats_aggregator.compute_status_counts(user_id, granularity),
    }


async def _tool_analyze_rejection_patterns(user_id: str, args: dict) -> dict:
    # Real call_llm under the hood -- offloaded so it never blocks the event loop.
    return await asyncio.to_thread(stats_skill_gap.analyze_rejection_patterns, user_id)


async def _tool_save_memory(user_id: str, args: dict) -> dict:
    entry = save_memory(user_id, content=args["content"], category=args.get("category", "fact"), source="chat")
    return {"memory_entry": entry}


async def _tool_list_memory(user_id: str, args: dict) -> dict:
    return {"memory": json_store.load_all(user_id, "memory")}


async def _tool_search_past_documents(user_id: str, args: dict) -> dict:
    query = args["query"]
    chunks = await asyncio.to_thread(retrieve_relevant_chunks, user_id, query, top_k=8)
    return {"chunks": chunks, "count": len(chunks)}


async def _tool_refresh_qualifications(user_id: str, args: dict) -> dict:
    record = await asyncio.to_thread(update_qualifications_prompt, user_id)
    return {"qualifications": record}


async def _tool_get_qualifications(user_id: str, args: dict) -> dict:
    return {"qualifications": get_latest_qualifications(user_id)}


def _load_preferences_or_default(user_id: str) -> dict:
    """Mirrors app/routes_companies.py:_load_preferences_or_default and
    orchestrator/discovery_graph.py:_load_preferences -- same one-record-
    via-list convention ("preferences" has no dedicated owning module)."""
    records = json_store.load_all(user_id, _PREFERENCES_ENTITY)
    if records:
        return records[0]
    return {"user_id": user_id, "updated_at": _now_iso(), **_DEFAULT_PREFERENCE_FIELDS}


async def _tool_update_commute_preferences(user_id: str, args: dict) -> dict:
    current = _load_preferences_or_default(user_id)
    updated = dict(current)

    if "home_location" in args and args["home_location"] is not None:
        new_location = args["home_location"]
        updated["home_location"] = new_location
        if new_location != current.get("home_location"):
            coords = await asyncio.to_thread(geocode, new_location)
            updated["home_lat"], updated["home_lng"] = coords if coords else (None, None)

    if "max_commute_km" in args and args["max_commute_km"] is not None:
        updated["max_commute_km"] = args["max_commute_km"]

    if "remote_preference" in args and args["remote_preference"] is not None:
        if args["remote_preference"] not in _VALID_REMOTE_PREFERENCES:
            raise ValueError(
                f"remote_preference must be one of {_VALID_REMOTE_PREFERENCES}, "
                f"got {args['remote_preference']!r}"
            )
        updated["remote_preference"] = args["remote_preference"]

    if "willing_to_relocate" in args and args["willing_to_relocate"] is not None:
        updated["willing_to_relocate"] = args["willing_to_relocate"]

    updated["user_id"] = user_id
    updated["updated_at"] = _now_iso()
    json_store.save_all(user_id, _PREFERENCES_ENTITY, [updated])
    return {"preferences": updated}


TOOL_HANDLERS: dict[str, Callable[[str, dict], Awaitable[dict]]] = {
    "run_discovery": _tool_run_discovery,
    "list_jobs": _tool_list_jobs,
    "get_job": _tool_get_job,
    "rate_job": _tool_rate_job,
    "tailor_resume_for_job": _tool_tailor_resume_for_job,
    "generate_cover_letter_for_job": _tool_generate_cover_letter_for_job,
    "get_profile": _tool_get_profile,
    "list_companies": _tool_list_companies,
    "add_company": _tool_add_company,
    "remove_company": _tool_remove_company,
    "mark_applied": _tool_mark_applied,
    "update_application_status": _tool_update_application_status,
    "list_applications": _tool_list_applications,
    "get_statistics": _tool_get_statistics,
    "analyze_rejection_patterns": _tool_analyze_rejection_patterns,
    "save_memory": _tool_save_memory,
    "list_memory": _tool_list_memory,
    "search_past_documents": _tool_search_past_documents,
    "refresh_qualifications": _tool_refresh_qualifications,
    "get_qualifications": _tool_get_qualifications,
    "update_commute_preferences": _tool_update_commute_preferences,
}


async def execute_tool(user_id: str, name: str, args: dict) -> Any:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool {name!r}")
    return await handler(user_id, args or {})


# ---------------------------------------------------------------------------
# Tool declarations -- google-genai's native structured function-calling
# format. `parameters_json_schema` (plain JSON Schema dict, confirmed present
# on google-genai==2.28.0's FunctionDeclaration) is used instead of building
# `types.Schema` objects by hand -- simpler and exactly equivalent per the
# SDK's own field docs ("Optional. Describes the parameters to the function
# in JSON Schema format").
# ---------------------------------------------------------------------------

def _decl(name: str, description: str, properties: dict, required: Optional[list[str]] = None) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=name,
        description=description,
        parameters_json_schema={
            "type": "object",
            "properties": properties,
            "required": required or [],
        },
    )


_JOB_FILTER_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["new", "seen", "closed"]},
        "company": {"type": "string"},
        "min_score": {"type": "number"},
    },
}

_APPLICATION_FILTER_SCHEMA = {
    "type": "object",
    "properties": {
        "status_label": {"type": "string", "description": "e.g. 'Applied', 'Interviewed', 'Rejected'"},
    },
}

TOOL_DECLARATIONS: list[types.FunctionDeclaration] = [
    _decl("run_discovery", "Run job discovery now across all of the user's configured companies, scoring any new postings against their profile.", {}),
    _decl("list_jobs", "List discovered jobs (joined with match scores), optionally filtered.", {
        "filter": _JOB_FILTER_SCHEMA,
    }),
    _decl("get_job", "Get full details (and match score, if any) for one job by id.", {
        "job_id": {"type": "string"},
    }, required=["job_id"]),
    _decl("rate_job", "Record the user's relevant/not_relevant feedback on a job, optionally with a free-text reason.", {
        "job_id": {"type": "string"},
        "feedback": {"type": "string", "enum": list(_VALID_FEEDBACK)},
        "reason": {"type": "string", "description": "Free-text reason, e.g. 'too much travel' or 'wrong stack'."},
    }, required=["job_id", "feedback"]),
    _decl("tailor_resume_for_job", "Generate a tailored resume (.docx) for a specific job.", {
        "job_id": {"type": "string"},
    }, required=["job_id"]),
    _decl("generate_cover_letter_for_job", "Generate a tailored cover letter (.docx) for a specific job.", {
        "job_id": {"type": "string"},
    }, required=["job_id"]),
    _decl("get_profile", "Get the user's parsed candidate profile (skills/experience/education).", {}),
    _decl("list_companies", "List the companies the user is tracking for job discovery.", {}),
    _decl("add_company", "Add a company (with its careers page URL) to the user's discovery source list.", {
        "name": {"type": "string"},
        "url": {"type": "string"},
    }, required=["name", "url"]),
    _decl("remove_company", "Remove a company from the user's discovery source list by its id.", {
        "company_id": {"type": "string"},
    }, required=["company_id"]),
    _decl("mark_applied", "Record that the user applied to a job, creating a tracker Application.", {
        "job_id": {"type": "string"},
        "status_label": {"type": "string", "description": "Defaults to 'Applied' if omitted."},
        "referred_by": {"type": "string"},
        "comments": {"type": "string"},
    }, required=["job_id"]),
    _decl("update_application_status", "Change an existing application's status (e.g. to 'Interviewed' or 'Closed').", {
        "application_id": {"type": "string"},
        "status_label": {"type": "string"},
    }, required=["application_id", "status_label"]),
    _decl("list_applications", "List the user's tracked applications, optionally filtered by status label.", {
        "filter": _APPLICATION_FILTER_SCHEMA,
    }),
    _decl("get_statistics", "Get application statistics/summary (rates, counts) and time-bucketed status counts.", {
        "granularity": {"type": "string", "enum": ["daily", "monthly"]},
    }),
    _decl("analyze_rejection_patterns", "Analyze rejected applications for a skill gap / study recommendation.", {}),
    _decl("save_memory", "Save a durable long-term fact/preference/feedback about the user for future sessions.", {
        "content": {"type": "string"},
        "category": {"type": "string", "enum": list(_VALID_MEMORY_CATEGORIES)},
    }, required=["content", "category"]),
    _decl("list_memory", "List all durable long-term memory entries saved for this user.", {}),
    _decl("search_past_documents", "Semantically search the user's past resumes/cover letters/profile for relevant phrasing.", {
        "query": {"type": "string"},
    }, required=["query"]),
    _decl("refresh_qualifications", "Re-synthesize the user's qualifications profile from their latest profile/feedback/outcomes.", {}),
    _decl("get_qualifications", "Get the latest synthesized qualifications profile, if one exists.", {}),
    _decl("update_commute_preferences", "Update the user's commute/remote/relocation preferences (geocodes home_location if given).", {
        "home_location": {"type": "string"},
        "max_commute_km": {"type": "number"},
        "remote_preference": {"type": "string", "enum": list(_VALID_REMOTE_PREFERENCES)},
        "willing_to_relocate": {"type": "boolean"},
    }),
]


# ---------------------------------------------------------------------------
# System instruction
# ---------------------------------------------------------------------------

_BASE_SYSTEM_INSTRUCTION = (
    "You are the assistant for the Smart Job Search Engine, a personal job-hunting "
    "tool. You help the user discover jobs, rate them, tailor resumes/cover letters, "
    "track applications through their status pipeline, see statistics, and manage "
    "long-term preferences -- by calling the tools made available to you. Prefer "
    "calling a tool over guessing at data you don't have; the Job Search page and "
    "the application tracker are the source of truth, not your own memory of the "
    "conversation. When a job-rating reason sounds like it's about commute, "
    "location, or remote work (e.g. 'too much travel', 'not remote enough'), "
    "proactively ask a short clarifying question and call update_commute_preferences "
    "to capture it as a computable preference rather than leaving it as vague free "
    "text. After tool results come back, compose a natural, concise reply that "
    "references the actual results (counts, titles, scores, statuses) rather than "
    "generic language."
)


def _build_system_instruction(user_id: str, session_summary: Optional[str] = None) -> str:
    parts = [_BASE_SYSTEM_INSTRUCTION]

    # Long-term memory injected on every turn (plan section 12: "chat_graph
    # injects the user's current list_memory() entries into its system
    # prompt on every turn").
    memory_entries = json_store.load_all(user_id, "memory")
    if memory_entries:
        lines = [f"- [{m.get('category', 'fact')}] {m.get('content', '')}" for m in memory_entries]
        parts.append("Long-term facts/preferences remembered about this user:\n" + "\n".join(lines))

    if session_summary:
        parts.append("Summary of earlier parts of this conversation (older turns were compressed to save context):\n" + session_summary)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# History conversion
# ---------------------------------------------------------------------------

def _history_to_contents(history: list[dict]) -> list[types.Content]:
    """Converts storage.schemas.ChatMessage dicts ({"role": "user"/
    "assistant", "content": str, "timestamp": str}) to google-genai
    `Content` turns. Gemini's roles are "user"/"model" (not "assistant")."""
    contents = []
    for msg in history:
        role = "model" if msg.get("role") == "assistant" else "user"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg.get("content") or "")]))
    return contents


# ---------------------------------------------------------------------------
# The loop itself
# ---------------------------------------------------------------------------

async def run_chat_turn(
    user_id: str,
    history: list[dict],
    user_message: str,
    *,
    session_summary: Optional[str] = None,
    client: Optional[genai.Client] = None,
    max_iterations: int = MAX_TOOL_ITERATIONS,
):
    """Runs one full user turn through Gemini's native function-calling loop,
    executing real tool calls as they come back and feeding the results back
    to the model, until it returns plain text with no further function
    calls (or `max_iterations` is hit).

    An async generator, so callers (orchestrator/chat_sessions.py, and
    chat/routes.py's SSE endpoint) can stream progress as it happens. Yields:
        {"type": "tool_call", "name": str, "args": dict}
        {"type": "tool_result", "name": str, "response": dict}
        {"type": "text", "text": str}                         -- final reply text
        {"type": "done", "reply": str, "tool_calls": [...], "max_iterations_hit": bool}

    `client` is injectable so tests never need a real GEMINI_API_KEY or to
    touch the real Gemini API -- see module docstring on the standing hold.
    """
    genai_client = client or _get_client()

    contents = _history_to_contents(history)
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_message)]))

    config = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
        system_instruction=_build_system_instruction(user_id, session_summary),
        # Explicit even though it's a no-op here: AFC only engages when raw
        # python callables are passed as `tools` (per google-genai's own
        # should_disable_afc), and we pass FunctionDeclaration/Tool objects
        # instead specifically so WE execute tools ourselves against this
        # codebase's real functions -- this just documents that choice.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    executed_tool_calls: list[dict] = []

    for _ in range(max_iterations):
        response = await asyncio.to_thread(
            genai_client.models.generate_content,
            model=MODEL_NAME,
            contents=contents,
            config=config,
        )

        function_calls = response.function_calls
        if not function_calls:
            reply_text = response.text or ""
            yield {"type": "text", "text": reply_text}
            yield {
                "type": "done",
                "reply": reply_text,
                "tool_calls": executed_tool_calls,
                "max_iterations_hit": False,
            }
            return

        # Record the model's turn (the function-call parts) before
        # executing anything, exactly as google-genai's own AFC loop does
        # (chats.py: `contents_to_model.append(func_call_content)`).
        contents.append(response.candidates[0].content)

        response_parts = []
        for call in function_calls:
            call_args = call.args or {}
            yield {"type": "tool_call", "name": call.name, "args": call_args}
            try:
                result = await execute_tool(user_id, call.name, call_args)
                func_response = {"result": result}
            except Exception as exc:  # noqa: BLE001 -- one bad tool call must not kill the turn
                func_response = {"error": str(exc)}
            executed_tool_calls.append({"name": call.name, "args": call_args, "response": func_response})
            yield {"type": "tool_result", "name": call.name, "response": func_response}
            response_parts.append(types.Part.from_function_response(name=call.name, response=func_response))

        contents.append(types.Content(role="user", parts=response_parts))

    fallback = (
        "I wasn't able to wrap this up after several tool calls in a row -- something "
        "may be looping. Here's what I found so far; try rephrasing your request or "
        "breaking it into smaller steps."
    )
    yield {"type": "text", "text": fallback}
    yield {
        "type": "done",
        "reply": fallback,
        "tool_calls": executed_tool_calls,
        "max_iterations_hit": True,
    }
