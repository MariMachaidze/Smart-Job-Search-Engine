"""
resume/cover_letter.py — tailored cover-letter generation (plan section 6).

Mirrors resume/tailor.py's pipeline (RAG retrieval -> strict LLM prompt ->
.docx render -> S3 upload -> GeneratedDocument persistence -> RAG indexing),
but the LLM output is prose paragraphs rather than structured resume
sections, since a cover letter is just a few paragraphs of connected text.

GUARDRAIL (critical, see plan section 6 and resume/tailor.py's module
docstring): the LLM may only reorganize/rephrase/emphasize facts already
present in the candidate's profile (raw_text/experience/skills). It must
never invent employers, titles, dates, or skills. Enforced in the prompt
wording below and verified live in
resume/test_tailor_and_cover_letter.py.
"""
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone

from app.llm import call_llm
from rag import indexer as rag_indexer
from rag import retriever as rag_retriever
from storage import json_store, s3_client
from storage.schemas import GeneratedDocument

from resume import docx_builder as db
from resume.prompts import format_past_phrasing_section

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

_COVER_LETTER_PROMPT_TEMPLATE = """You are helping a job candidate write a cover letter for a specific job posting.

You will be given the candidate's full profile (their real, verified work history, skills, and
education) and a job description. Write a cover letter that connects the candidate's EXISTING,
REAL experience to this job -- you are not inventing a new story about them, just telling their
real story in a way that's relevant to this job.

=== ABSOLUTE RULES (do not break these under any circumstances) ===
1. Every fact in the letter (employer names, job titles, projects, skills, achievements,
   durations) must be explicitly present in the candidate profile below. Do not invent, infer, or
   guess any employer, title, date, skill, or achievement that isn't there.
2. If the job description asks for a skill or experience the profile does not contain, DO NOT
   claim the candidate has it, even implicitly. Either omit it, or -- at most -- note genuine
   transferable experience that IS in the profile, described honestly as such (never as direct
   experience with the missing skill/tool itself).
3. You may rephrase, reorder, and choose which real experiences to emphasize for this job, and you
   may write connecting/framing sentences (enthusiasm, motivation, fit) that aren't literal resume
   bullets, as long as they don't assert any new factual claim about the candidate's background.
4. Company names and job titles, if mentioned, must match the profile's experience entries
   exactly.

=== CANDIDATE PROFILE ===
Full name: {full_name}
Existing summary: {summary}
Skills (the ONLY skills you may reference): {skills}
Experience (JSON, authoritative -- do not alter company/title/dates):
{experience_json}
Education (JSON, authoritative):
{education_json}
Raw resume text (for additional context/phrasing only, same facts as above):
---
{raw_text}
---

=== PAST PHRASING / STYLE CONTEXT (optional; reused phrasing only, never reused facts) ===
{past_phrasing_section}

=== TARGET JOB ===
Title: {job_title}
Company: {job_company}
Description:
---
{job_description}
---

Return ONLY a single JSON object (no markdown code fences, no commentary) with EXACTLY this
field:
{{
  "paragraphs": [string, ...]   // 3-5 paragraphs: opening/intro, 1-2 body paragraphs connecting
                                  // real experience to the role, closing. Do NOT include the
                                  // salutation ("Dear Hiring Manager,") or signoff ("Sincerely,
                                  // Full Name") -- those are added separately.
}}

Output must be valid JSON and nothing else.
"""


def _strip_code_fences(raw: str) -> str:
    stripped = (raw or "").strip()
    match = _CODE_FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def _parse_llm_json(raw_response: str) -> dict:
    return json.loads(_strip_code_fences(raw_response or ""))


def _call_cover_letter_llm(profile: dict, job: dict, past_phrasing_section: str) -> dict:
    prompt = _COVER_LETTER_PROMPT_TEMPLATE.format(
        full_name=profile.get("full_name") or "",
        summary=profile.get("summary") or "",
        skills=", ".join(profile.get("skills") or []),
        experience_json=json.dumps(profile.get("experience") or [], indent=2),
        education_json=json.dumps(profile.get("education") or [], indent=2),
        raw_text=(profile.get("raw_text") or "")[:8000],
        past_phrasing_section=past_phrasing_section,
        job_title=job.get("title") or "",
        job_company=job.get("company") or "",
        job_description=(job.get("description") or "")[:6000],
    )
    raw_response = call_llm(prompt)
    try:
        return _parse_llm_json(raw_response)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    retry_suffix = (
        "\n\nYour previous response could not be parsed as JSON. Return ONLY a valid JSON "
        "object as specified above -- no markdown fences, no commentary, nothing but JSON."
    )
    raw_retry = call_llm(prompt + retry_suffix)
    try:
        return _parse_llm_json(raw_retry)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(
            "Gemini did not return parseable JSON for cover-letter generation, even after a "
            f"stricter retry. Last raw response (truncated): {raw_retry[:500]!r}"
        ) from exc


def _render_cover_letter_docx(profile: dict, job: dict, paragraphs: list[str], path: str) -> str:
    document = db.new_document_from_template(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "templates", "cover_letter_template.docx"
        )
    )

    db.add_title(document, profile.get("full_name") or "")

    contact_parts = [
        p for p in [
            profile.get("email"),
            profile.get("phone"),
            profile.get("location"),
        ] if p
    ]
    db.add_contact_line(document, " | ".join(contact_parts))

    db.add_heading(document, "Dear Hiring Manager,")

    for paragraph in paragraphs:
        if paragraph and paragraph.strip():
            db.add_body_text(document, paragraph.strip())

    db.add_body_text(document, "Sincerely,")
    db.add_body_text(document, profile.get("full_name") or "")

    return db.save_document(document, path)


def generate_cover_letter(user_id: str, profile: dict, job: dict) -> GeneratedDocument:
    """Generates a tailored cover-letter .docx for `job` from `profile`,
    uploads it to S3, persists a GeneratedDocument record, and indexes it
    for RAG. Never fabricates facts not present in `profile` (see module
    docstring)."""
    chunks = rag_retriever.retrieve_relevant_chunks(
        user_id, query=job.get("description") or "", top_k=8
    )
    past_phrasing_section = format_past_phrasing_section(chunks)

    result = _call_cover_letter_llm(profile, job, past_phrasing_section)
    paragraphs = [p for p in (result.get("paragraphs") or []) if isinstance(p, str)]
    if not paragraphs:
        # Defensive fallback so a malformed/empty LLM response never produces
        # a blank cover letter -- fall back to the profile's own summary.
        paragraphs = [profile.get("summary") or ""]

    document_id = str(uuid.uuid4())
    fd, tmp_path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    try:
        _render_cover_letter_docx(profile, job, paragraphs, tmp_path)
        s3_key = s3_client.upload_file(tmp_path, f"users/{user_id}/generated/{document_id}.docx")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    display_name = f"Cover Letter — {job.get('title') or 'Role'} at {job.get('company') or 'Company'}.docx"

    record: GeneratedDocument = {
        "document_id": document_id,
        "job_id": job.get("job_id"),
        "profile_id": profile.get("profile_id"),
        "doc_type": "cover_letter",
        "s3_key": s3_key,
        "display_name": display_name,
        "format": "docx",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_notes": f"retrieved_chunks={len(chunks)}",
    }

    json_store.upsert(user_id, "documents", record, "document_id")
    rag_indexer.index_generated_document(user_id, record, "\n\n".join(paragraphs))

    return record
