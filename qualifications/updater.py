"""
Qualifications prompt updater (workstream R, plan section 8a).

update_qualifications_prompt() is the only thing that writes
data/users/{id}/qualifications.json, and it does so by *appending* a new
versioned QualificationsProfile record rather than overwriting -- the plan
explicitly wants to be able to see the model's understanding of the
candidate drift over time, so qualifications.json is a growing history list,
not a single mutable record.

It makes exactly ONE call_llm synthesis call per invocation, combining:
  - storage.json_store.load_profile(user_id)                      -- base profile
  - storage.json_store.load_all(user_id, "memory")                 -- MemoryEntry list
  - storage.json_store.load_all(user_id, "scores") filtered to
    user_feedback == "not_relevant", read directly for feedback_reason
  - rag.retriever.retrieve_relevant_chunks(...)                    -- may be []
  - stats.skill_gap.analyze_rejection_patterns(user_id)             -- may not exist yet
  - recent Application outcomes, joined against jobs/tracker_statuses
    (via tracker.service.list_applications if that workstream has landed,
    otherwise joined locally here)

Dependencies owned by other, possibly-not-yet-landed workstreams
(stats.skill_gap, tracker.service) are imported defensively: if the real
module isn't on disk yet, a local stand-in matching its documented contract
is used instead, so this module degrades gracefully rather than failing to
import. rag.retriever is always real (it's a deliberate no-op stub per the
plan, not a missing module) and is called unconditionally -- it currently
returns [], which this module treats as "no retrieved context to add."
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.llm import call_llm
from storage import json_store
from rag.retriever import retrieve_relevant_chunks

try:
    # Real implementation, once workstream J (Statistics & Skill-Gap) has landed.
    from stats.skill_gap import analyze_rejection_patterns
except ImportError:  # pragma: no cover - only hit if stats/skill_gap.py isn't present yet
    def analyze_rejection_patterns(user_id: str) -> dict:
        """Stand-in matching stats.skill_gap.analyze_rejection_patterns's
        documented return shape (plan section 8):
        {missing_skills: [...], recommendation: "..."}. Used only until
        workstream J lands the real implementation."""
        return {"missing_skills": [], "recommendation": ""}

try:
    # Real implementation, once workstream I (Application Tracker) has landed.
    from tracker.service import list_applications as _list_applications
except ImportError:  # pragma: no cover - only hit if tracker/service.py isn't present yet
    _list_applications = None


# ---------------------------------------------------------------------------
# get_latest_qualifications
# ---------------------------------------------------------------------------

def get_latest_qualifications(user_id: str) -> Optional[dict]:
    """Returns the highest-`version` QualificationsProfile record for this
    user, or None if update_qualifications_prompt has never run for them."""
    records = json_store.load_all(user_id, "qualifications")
    if not records:
        return None
    return max(records, key=lambda r: r.get("version", 0))


# ---------------------------------------------------------------------------
# Application outcomes (joined view)
# ---------------------------------------------------------------------------

def _joined_applications(user_id: str) -> list[dict]:
    """Recent Application records joined with their JobPosting and
    TrackerStatus, for use as "which job types led to interviews vs silence
    vs rejection" signal. Prefers tracker.service.list_applications (workstream
    I's real joined view) when available; otherwise joins the three entity
    collections locally. Field names (`title`, `description`, `company`,
    `location`, `status_label`) match tracker/service.py:list_applications's
    actual joined-dict shape so both paths can be consumed identically by the
    rest of this module."""
    if _list_applications is not None:
        try:
            return _list_applications(user_id)
        except Exception as exc:  # pragma: no cover - defensive, don't let this block synthesis
            print(f"[qualifications.updater] tracker.service.list_applications failed, falling back to local join: {exc}")

    applications = json_store.load_all(user_id, "applications")
    if not applications:
        return []

    jobs_by_id = {j.get("job_id"): j for j in json_store.load_all(user_id, "jobs")}
    statuses_by_id = {s.get("status_id"): s for s in json_store.load_all(user_id, "tracker_statuses")}

    joined = []
    for app in applications:
        job = jobs_by_id.get(app.get("job_id"), {})
        status = statuses_by_id.get(app.get("status_id"), {})
        joined.append({
            **app,
            "company": job.get("company"),
            "title": job.get("title"),
            "description": job.get("description"),
            "location": job.get("location"),
            "status_label": status.get("label"),
        })
    return joined


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _build_profile_text(profile: Optional[dict]) -> str:
    if not profile:
        return "No candidate profile has been uploaded yet."

    parts = []
    full_name = profile.get("full_name")
    if full_name:
        parts.append(f"Name: {full_name}")

    summary = profile.get("summary")
    if summary:
        parts.append(f"Summary: {summary}")

    skills = profile.get("skills") or []
    if skills:
        parts.append("Skills: " + ", ".join(skills))

    experience = profile.get("experience") or []
    if experience:
        exp_lines = []
        for entry in experience:
            title = entry.get("title", "")
            company = entry.get("company", "")
            start = entry.get("start_date") or "?"
            end = entry.get("end_date") or "present"
            line = f"- {title} at {company} ({start} - {end})"
            bullets = entry.get("bullets") or []
            if bullets:
                line += "\n  " + "\n  ".join(bullets)
            exp_lines.append(line)
        parts.append("Experience:\n" + "\n".join(exp_lines))

    education = profile.get("education") or []
    if education:
        edu_lines = [
            f"- {e.get('degree', '')} {e.get('field', '')} at {e.get('institution', '')}".strip()
            for e in education
        ]
        parts.append("Education:\n" + "\n".join(edu_lines))

    return "\n\n".join(parts) if parts else "Candidate profile on file is empty."


def _representative_query(profile: Optional[dict], applications: list[dict]) -> str:
    """Builds the `query` passed to retrieve_relevant_chunks: the plan
    suggests "the profile summary or recent job titles" as a representative
    stand-in for "what is this candidate's search about" -- we use both."""
    pieces = []
    if profile:
        if profile.get("summary"):
            pieces.append(profile["summary"])
        if profile.get("skills"):
            pieces.append(", ".join(profile["skills"][:10]))
    recent_titles = [a.get("title") for a in applications[:10] if a.get("title")]
    if recent_titles:
        pieces.append("Recent roles applied to: " + ", ".join(recent_titles))
    return " | ".join(pieces) if pieces else "software engineering job search"


def _build_synthesis_prompt(
    profile_text: str,
    memory_entries: list[dict],
    rejection_reasons: list[str],
    chunks: list[dict],
    skill_gap: dict,
    applications: list[dict],
) -> str:
    sections = [
        "You maintain an evolving, natural-language 'qualifications profile' for a "
        "candidate using a job-search assistant. Read everything below and write ONE "
        "synthesized qualifications summary describing: (1) what this candidate is "
        "genuinely qualified for, (2) what kind of roles/companies they are actually "
        "looking for, and (3) constraints, preferences, or skill gaps that should steer "
        "future job matching. This summary -- not the raw profile -- is what gets used "
        "to score future job postings against this candidate, so it should actively "
        "incorporate what has been learned from feedback and outcomes below, not just "
        "restate the base profile. Ground every claim in the evidence given; do not "
        "invent facts, employers, or skills that aren't supported by the data.\n",
        "BASE CANDIDATE PROFILE:\n" + profile_text,
    ]

    if memory_entries:
        mem_lines = [f"- [{m.get('category', 'fact')}] {m.get('content', '')}" for m in memory_entries]
        sections.append("LONG-TERM MEMORY (explicit or derived preferences/feedback/facts):\n" + "\n".join(mem_lines))

    if rejection_reasons:
        reason_lines = [f"- {r}" for r in rejection_reasons]
        sections.append(
            "JOBS THE CANDIDATE EXPLICITLY MARKED 'NOT RELEVANT', WITH THE REASON GIVEN "
            "(this is the most direct 'why didn't you like these' signal available -- "
            "weigh it heavily):\n" + "\n".join(reason_lines)
        )

    if chunks:
        chunk_lines = [c.get("text", "") for c in chunks if c.get("text")]
        if chunk_lines:
            sections.append(
                "RETRIEVED CONTEXT FROM PAST RESUMES/COVER LETTERS (phrasing/emphasis "
                "actually used before):\n" + "\n".join(f"- {t}" for t in chunk_lines)
            )

    missing_skills = skill_gap.get("missing_skills") or []
    recommendation = skill_gap.get("recommendation") or ""
    if missing_skills or recommendation:
        gap_text = ""
        if missing_skills:
            gap_text += "Skills that keep coming up missing across rejected applications: " + ", ".join(missing_skills) + "\n"
        if recommendation:
            gap_text += "Analysis recommendation: " + recommendation
        sections.append("SKILL-GAP ANALYSIS FROM REJECTION PATTERNS:\n" + gap_text.strip())

    if applications:
        app_lines = []
        for a in applications[:25]:
            app_lines.append(
                f"- {a.get('title') or 'Unknown title'} at {a.get('company') or 'Unknown company'}: "
                f"status = {a.get('status_label') or a.get('status_id') or 'unknown'}"
            )
        sections.append("RECENT APPLICATION OUTCOMES:\n" + "\n".join(app_lines))

    sections.append(
        "Now write the qualifications summary as plain prose (no JSON, no markdown "
        "headers/bullets), roughly 150-300 words."
    )

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# update_qualifications_prompt
# ---------------------------------------------------------------------------

def update_qualifications_prompt(user_id: str) -> dict:
    """
    Runs one call_llm synthesis combining the candidate's base profile,
    long-term memory, explicit 'not relevant' feedback reasons, RAG-retrieved
    past document context, rejection-driven skill-gap analysis, and recent
    application outcomes -- then appends a new versioned QualificationsProfile
    record to data/users/{user_id}/qualifications.json (history is kept, not
    overwritten) and returns that new record.
    """
    profile = json_store.load_profile(user_id)
    memory_entries = json_store.load_all(user_id, "memory")
    scores = json_store.load_all(user_id, "scores")
    not_relevant_scores = [s for s in scores if s.get("user_feedback") == "not_relevant"]
    rejection_reasons = [s["feedback_reason"] for s in not_relevant_scores if s.get("feedback_reason")]

    applications = _joined_applications(user_id)

    query = _representative_query(profile, applications)
    chunks = retrieve_relevant_chunks(user_id, query=query, top_k=8)

    skill_gap = analyze_rejection_patterns(user_id) or {}

    profile_text = _build_profile_text(profile)
    prompt = _build_synthesis_prompt(
        profile_text=profile_text,
        memory_entries=memory_entries,
        rejection_reasons=rejection_reasons,
        chunks=chunks,
        skill_gap=skill_gap,
        applications=applications,
    )

    prompt_text = (call_llm(prompt) or "").strip()

    previous = get_latest_qualifications(user_id)
    next_version = (previous.get("version", 0) + 1) if previous else 1

    record = {
        "qualifications_id": f"qual_{uuid.uuid4().hex[:16]}",
        "user_id": user_id,
        "version": next_version,
        "prompt_text": prompt_text,
        "based_on": {
            "profile_id": (profile or {}).get("profile_id"),
            "applications_considered": len(applications),
            "rejections_considered": len(not_relevant_scores),
            "memory_entries_considered": len(memory_entries),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Each record gets a fresh qualifications_id, so upsert's "replace if
    # key_field matches an existing record" branch never fires here -- every
    # call appends a new history entry rather than overwriting the last one.
    json_store.upsert(user_id, "qualifications", record, "qualifications_id")

    return record
