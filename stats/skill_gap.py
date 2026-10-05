"""
Skill-gap recommendations, derived from rejection patterns in the tracker.

Per the design doc (section 8): triggered once rejected-application count
crosses a threshold, at which point it gathers the JobPosting descriptions
for every rejected-outcome application, diffs the skills those postings seem
to require against the user's CandidateProfile.skills via the existing
Gemini wrapper (`app/llm.py:call_llm`), and returns a skill-gap
recommendation.

Thresholds implemented (either one triggers analysis -- both are checked,
matching the "e.g. >= 5, or rejection rate > 50%" wording in the design doc
literally as two independent checks rather than picking just one):
  1. rejected_count >= REJECTED_COUNT_THRESHOLD (5)
  2. rejected_count / terminal_count > REJECTION_RATE_THRESHOLD (0.5),
     where terminal_count = applications currently in a terminal status
     (Accepted, Rejected, Applied but closed, Closed -- see
     stats/aggregator.py's _TERMINAL set) -- i.e. "more than half of the
     applications that have reached some final outcome were rejections."
     Guarded against terminal_count == 0 (no division by zero).

"Rejected-outcome" applications (the ones whose job descriptions get fed to
the LLM) are those categorized "rejected" by aggregator._category_for_label,
i.e. current status label "Rejected" or "Applied but closed" -- exactly the
pairing named in the design doc.
"""
import json
import re

from app.llm import call_llm
from storage import json_store
from stats.aggregator import _category_for_label, _joined_applications

REJECTED_COUNT_THRESHOLD = 5
REJECTION_RATE_THRESHOLD = 0.5


def _not_enough_data(reason: str, based_on_count: int = 0) -> dict:
    return {
        "missing_skills": [],
        "recommendation": reason,
        "based_on_count": based_on_count,
        "threshold_met": False,
    }


def _extract_json_object(text: str) -> dict:
    """call_llm returns raw Gemini text, which may wrap JSON in a markdown
    code fence (```json ... ```) or include stray prose around it. Strips
    fences and grabs the first {...} block."""
    if not text:
        raise ValueError("empty LLM response")
    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object found in LLM response: {text!r}")
    return json.loads(match.group(0))


def analyze_rejection_patterns(user_id: str) -> dict:
    """
    Returns:
        {
            "missing_skills": list[str],
            "recommendation": str,
            "based_on_count": int,     # number of rejected-outcome applications analyzed
            "threshold_met": bool,     # False means the dict is a "not enough
                                        # data yet" placeholder, not a real analysis
        }
    Never raises for the "not enough data" / "no profile" cases -- those are
    reported in the return value instead of an exception, per the design
    doc's "should still return a reasonable result ... rather than erroring."
    """
    apps = _joined_applications(user_id)

    rejected_apps = [a for a in apps if _category_for_label(a.get("status_label")) == "rejected"]
    terminal_apps = [a for a in apps if _category_for_label(a.get("status_label")) in ("offer", "rejected", "closed_other")]

    rejected_count = len(rejected_apps)
    terminal_count = len(terminal_apps)
    rejection_rate = (rejected_count / terminal_count) if terminal_count else 0.0

    threshold_met = (
        rejected_count >= REJECTED_COUNT_THRESHOLD
        or (terminal_count > 0 and rejection_rate > REJECTION_RATE_THRESHOLD)
    )

    if not threshold_met:
        return _not_enough_data(
            f"Not enough data yet to spot a skill gap: {rejected_count} rejected "
            f"application(s) so far (need at least {REJECTED_COUNT_THRESHOLD}, or a "
            f"rejection rate above {int(REJECTION_RATE_THRESHOLD * 100)}% of applications "
            f"with a final outcome -- currently {rejection_rate:.0%} of {terminal_count}).",
            based_on_count=rejected_count,
        )

    profile = json_store.load_profile(user_id)
    if not profile or not profile.get("skills"):
        return _not_enough_data(
            "Rejection count/rate crossed the threshold, but no CandidateProfile "
            "(or no skills on it) is on file yet to diff against -- upload a resume first.",
            based_on_count=rejected_count,
        )

    descriptions = [a["description"] for a in rejected_apps if a.get("description")]
    if not descriptions:
        return _not_enough_data(
            "Rejection threshold crossed, but none of the rejected applications' "
            "linked job postings have a description on file to analyze.",
            based_on_count=rejected_count,
        )

    candidate_skills = profile["skills"]
    postings_block = "\n\n".join(
        f"--- Job {i + 1}: {a.get('title') or 'Unknown title'} at {a.get('company') or 'Unknown company'} ---\n{a['description']}"
        for i, a in enumerate(rejected_apps) if a.get("description")
    )

    prompt = (
        "You are analyzing a job seeker's rejected job applications to find a skill gap.\n\n"
        f"The candidate's current skills are:\n{', '.join(candidate_skills)}\n\n"
        "Below are the job descriptions for applications that were REJECTED or closed after "
        "applying. Identify skills/technologies/qualifications that these job descriptions "
        "commonly require which are NOT present in the candidate's current skill list above.\n\n"
        f"{postings_block}\n\n"
        "Respond with ONLY a JSON object (no markdown fence, no commentary) matching exactly "
        "this shape:\n"
        '{"missing_skills": ["skill1", "skill2", ...], "recommendation": "one or two sentences '
        'of concrete, actionable advice naming which skills to study and why, referencing how '
        'often they appeared in the rejected postings"}\n'
        "List at most 8 missing_skills, ordered by how frequently/important they appeared. "
        "Only include skills that are genuinely absent from the candidate's skill list -- do "
        "not repeat skills the candidate already has."
    )

    raw_response = call_llm(prompt)
    try:
        parsed = _extract_json_object(raw_response)
        missing_skills = parsed.get("missing_skills", [])
        recommendation = parsed.get("recommendation", "")
    except (ValueError, json.JSONDecodeError):
        # LLM didn't return parseable JSON -- degrade gracefully rather than
        # erroring, per the design doc. Surface the raw text as the
        # recommendation so the information isn't silently lost.
        missing_skills = []
        recommendation = (
            "Analysis ran but the LLM response couldn't be parsed as structured data. "
            f"Raw response: {raw_response.strip()[:500]}"
        )

    return {
        "missing_skills": missing_skills,
        "recommendation": recommendation,
        "based_on_count": rejected_count,
        "threshold_met": True,
    }
