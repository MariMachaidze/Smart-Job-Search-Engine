"""
Matching / scoring (workstream D).

score_job() is the only public entrypoint: given a candidate profile and a
job posting, it makes one `call_llm` invocation asking Gemini to rate how
well the candidate matches the job, and returns a fully-populated
MatchScore record.

`user_feedback` / `feedback_reason` are intentionally left None here — they
get set later, by a separate code path, when the user actually rates the
job (see plan section 5 / section 11's `rate_job` chat tool).
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Optional

from app.llm import call_llm

try:
    # Real schemas, once workstream A has landed them.
    from storage.schemas import CandidateProfile, JobPosting, MatchScore
except ImportError:  # pragma: no cover - only hit if storage/schemas.py isn't present yet
    CandidateProfile = dict
    JobPosting = dict
    MatchScore = dict


# Judgment call: Gemini 2.5 Flash can handle far more than this in context,
# but very long JDs (some ATS postings embed entire benefits handbooks) add
# cost/latency for no scoring benefit, so we cap and note the truncation.
MAX_DESCRIPTION_CHARS = 8000

# Candidate-side text is normally much shorter than a job description, but
# cap it too in case a profile has an unusually long raw summary/experience list.
MAX_CANDIDATE_CHARS = 6000

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _truncate(text: str, max_chars: int) -> str:
    if text and len(text) > max_chars:
        return text[:max_chars] + "\n...[truncated]"
    return text or ""


def _build_candidate_summary(profile: dict) -> str:
    """
    Raw-profile fallback used when no qualifications_prompt has been
    synthesized yet (plan section 8a: qualifications_prompt is preferred
    once it exists, since it reflects feedback/memory/rejection patterns
    that the raw profile fields never will).
    """
    parts = []

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

    certifications = profile.get("certifications") or []
    if certifications:
        parts.append("Certifications: " + ", ".join(certifications))

    return _truncate("\n\n".join(parts), MAX_CANDIDATE_CHARS)


def _build_prompt(candidate_text: str, job: dict, strict: bool = False) -> str:
    title = job.get("title", "")
    company = job.get("company", "")
    description = _truncate(job.get("description", ""), MAX_DESCRIPTION_CHARS)

    schema_block = (
        '{"score": <integer 0-100>, "rationale": "<1-3 sentence explanation>", '
        '"matched_skills": ["<skill>", ...], "missing_skills": ["<skill>", ...]}'
    )

    instructions = (
        "You are an expert technical recruiter. Compare the candidate below against "
        "the job posting and assess how strong a match they are.\n\n"
        f"CANDIDATE:\n{candidate_text}\n\n"
        f"JOB TITLE: {title}\n"
        f"COMPANY: {company}\n"
        f"JOB DESCRIPTION:\n{description}\n\n"
        "Respond with ONLY a single JSON object, no markdown code fences, no "
        "commentary before or after it, matching exactly this shape:\n"
        f"{schema_block}\n\n"
        "- score is an integer from 0 (no fit) to 100 (ideal fit).\n"
        "- matched_skills lists skills/experience the candidate has that this job wants.\n"
        "- missing_skills lists skills/requirements the job wants that the candidate's "
        "profile does not show.\n"
    )

    if strict:
        instructions += (
            "\nIMPORTANT: Your previous response could not be parsed as JSON. "
            "Output raw JSON ONLY — do not wrap it in ```json fences, do not add any "
            "explanation text, do not prefix or suffix it with anything. The entire "
            "response body must be valid JSON and nothing else.\n"
        )

    return instructions


def _parse_response(raw: str) -> Optional[dict]:
    if not raw:
        return None

    text = raw.strip()
    text = _JSON_FENCE_RE.sub("", text).strip()

    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: pull out the largest {...} blob in case the model added
    # stray commentary around the JSON despite instructions.
    match = _JSON_OBJECT_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError):
            return None

    return None


def _coerce_match_fields(parsed: dict) -> dict:
    score = parsed.get("score", 0)
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(100.0, score))

    rationale = parsed.get("rationale")
    if not isinstance(rationale, str):
        rationale = str(rationale) if rationale is not None else ""

    def _as_str_list(value) -> list:
        if not isinstance(value, list):
            return []
        return [str(v) for v in value]

    return {
        "score": score,
        "rationale": rationale,
        "matched_skills": _as_str_list(parsed.get("matched_skills")),
        "missing_skills": _as_str_list(parsed.get("missing_skills")),
    }


def _deterministic_match_id(job_id: str, profile_id: str) -> str:
    digest = hashlib.sha256(f"{job_id}:{profile_id}".encode("utf-8")).hexdigest()
    return f"match_{digest[:24]}"


def score_job(
    profile: "CandidateProfile",
    job: "JobPosting",
    qualifications_prompt: Optional[str] = None,
) -> "MatchScore":
    """
    Score one job against one candidate via a single call_llm invocation.

    When `qualifications_prompt` is given, it is used in place of the raw
    profile fields (plan section 8a: it's a periodically-refreshed, more
    nuanced synthesis — incorporating feedback/memory/rejection patterns —
    so it's strictly preferred over the static profile once it exists).
    """
    candidate_text = qualifications_prompt if qualifications_prompt else _build_candidate_summary(profile)
    if qualifications_prompt:
        candidate_text = _truncate(qualifications_prompt, MAX_CANDIDATE_CHARS)

    prompt = _build_prompt(candidate_text, job)
    raw = call_llm(prompt)
    parsed = _parse_response(raw)

    if parsed is None:
        # Retry once with a stricter, more explicit prompt before giving up.
        strict_prompt = _build_prompt(candidate_text, job, strict=True)
        raw_retry = call_llm(strict_prompt)
        parsed = _parse_response(raw_retry)

    if parsed is None:
        # Don't crash a whole discovery run over one unparseable response
        # (consistent with the plan's "per-item errors logged, not fatal"
        # pattern used elsewhere, e.g. discovery_graph's per-company errors).
        print(f"[matching.scorer] Could not parse LLM response for job_id={job.get('job_id')!r}; raw={raw!r}")
        fields = {
            "score": 0.0,
            "rationale": "Scoring failed: LLM response could not be parsed as JSON after one retry.",
            "matched_skills": [],
            "missing_skills": [],
        }
    else:
        fields = _coerce_match_fields(parsed)

    job_id = job.get("job_id")
    profile_id = profile.get("profile_id")

    match_score: dict = {
        "match_id": _deterministic_match_id(job_id, profile_id),
        "job_id": job_id,
        "profile_id": profile_id,
        "score": fields["score"],
        "rationale": fields["rationale"],
        "matched_skills": fields["matched_skills"],
        "missing_skills": fields["missing_skills"],
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "user_feedback": None,
        "feedback_reason": None,
    }
    return match_score  # type: ignore[return-value]
