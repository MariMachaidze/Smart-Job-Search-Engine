"""
resume/tailor.py — tailored resume generation (plan section 6).

Pipeline for `tailor_resume`:
  1. Retrieve past phrasing/style context via `rag.retriever.retrieve_relevant_chunks`
     (no-op stub today -- always returns [], folded into the prompt as an empty
     "past phrasing" section until workstream Q lands the real RAG implementation).
  2. Build a strict reorganize-only prompt from the candidate's existing profile
     fields (raw_text / experience / skills) + the job description, asking Gemini
     (via the existing `app.llm.call_llm`) to return structured JSON describing
     which existing bullets/skills to feature and how to phrase a summary --
     never new facts.
  3. Render that JSON into a styled .docx via resume/docx_builder.py +
     resume/templates/resume_template.docx.
  4. Upload the .docx to S3, persist a GeneratedDocument record, index it for RAG.

GUARDRAIL (critical, see plan section 6): the LLM may only reorganize, rephrase,
or emphasize content already present in the candidate's profile. It must never
invent employers, titles, dates, or skills that aren't in
profile["raw_text"]/profile["experience"]/profile["skills"]. This is enforced
in the prompt wording below, and verified by a live test in
resume/test_tailor_and_cover_letter.py that feeds a job description requiring a
skill the test profile doesn't have, and asserts the generated resume never
claims it.
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

_TAILOR_PROMPT_TEMPLATE = """You are helping a job candidate tailor their resume for a specific job posting.

You will be given the candidate's full profile (their real, verified work history, skills, and
education) and a job description. Your job is to decide which EXISTING parts of their profile to
feature, how to ORDER them, and how to REPHRASE/EMPHASIZE them for this specific job -- not to
write new facts about the candidate.

=== ABSOLUTE RULES (do not break these under any circumstances) ===
1. You may ONLY use facts that are explicitly present in the candidate profile below (summary,
   skills list, experience entries with their bullets, education, certifications).
2. You must NEVER invent, infer, guess, or add: employers, job titles, dates, degrees,
   certifications, or skills that are not verbatim present in the profile below. If the job
   description wants a skill the candidate's profile does not list, DO NOT add that skill anywhere
   in the output -- simply do not claim it. It is far better to omit something the job wants than
   to fabricate it.
3. You MAY rephrase a bullet's wording, reorder bullets/skills to put the most job-relevant ones
   first, and write a new 1-3 sentence summary -- but every claim in that rephrased text must trace
   back to something stated in the profile. Do not exaggerate scope, scale, or seniority beyond
   what the original bullet says.
4. Company names, job titles, locations, and start/end dates for each experience entry must be
   copied EXACTLY as given in the profile's experience list -- do not alter them.

=== CANDIDATE PROFILE ===
Full name: {full_name}
Existing summary: {summary}
Skills (the ONLY skills you may reference): {skills}
Experience (JSON, authoritative -- do not alter company/title/dates):
{experience_json}
Education (JSON, authoritative):
{education_json}
Certifications: {certifications}
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

Return ONLY a single JSON object (no markdown code fences, no commentary) with EXACTLY these
fields:
{{
  "summary": string,                      // 1-3 sentence tailored summary, facts from profile only
  "featured_skills": [string, ...],       // subset/reordering of the candidate's own skills list, most relevant to this job first -- must all appear verbatim in the Skills list above
  "experience": [
    {{
      "company": string,                  // copied verbatim from an experience entry above
      "title": string,                     // copied verbatim from that same entry
      "location": string or null,          // copied verbatim
      "start_date": string or null,        // copied verbatim
      "end_date": string or null,          // copied verbatim
      "bullets": [string, ...]             // rephrased/reordered/emphasized versions of that entry's own bullets ONLY -- same facts, same scope
    }}, ...
  ]
}}

Include every experience entry from the profile (do not drop entries), but you may reorder them
and reorder/rephrase/trim their bullets to emphasize what's relevant to this job. Output must be
valid JSON and nothing else.
"""


def _strip_code_fences(raw: str) -> str:
    stripped = (raw or "").strip()
    match = _CODE_FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def _parse_llm_json(raw_response: str) -> dict:
    return json.loads(_strip_code_fences(raw_response or ""))


def _call_tailor_llm(profile: dict, job: dict, past_phrasing_section: str) -> dict:
    prompt = _TAILOR_PROMPT_TEMPLATE.format(
        full_name=profile.get("full_name") or "",
        summary=profile.get("summary") or "",
        skills=", ".join(profile.get("skills") or []),
        experience_json=json.dumps(profile.get("experience") or [], indent=2),
        education_json=json.dumps(profile.get("education") or [], indent=2),
        certifications=", ".join(profile.get("certifications") or []),
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
            "Gemini did not return parseable JSON for resume tailoring, even after a "
            f"stricter retry. Last raw response (truncated): {raw_retry[:500]!r}"
        ) from exc


def _validate_no_fabrication(tailored: dict, profile: dict) -> dict:
    """Defensive guard on top of the prompt-level instructions: drops any
    featured_skills entries that aren't verbatim in the candidate's real
    skills list, and drops any experience entries whose company/title isn't
    verbatim in the candidate's real experience list. This can't catch
    fabricated *prose* inside an otherwise-real bullet, but it guarantees the
    structured facts (skills claimed, employers/titles listed) never exceed
    what the profile actually contains, even if the model ignores the prompt
    instructions."""
    real_skills = set(profile.get("skills") or [])
    real_experience_keys = {
        (entry.get("company"), entry.get("title"))
        for entry in (profile.get("experience") or [])
    }

    featured_skills = [
        s for s in (tailored.get("featured_skills") or []) if s in real_skills
    ]

    safe_experience = []
    for entry in tailored.get("experience") or []:
        key = (entry.get("company"), entry.get("title"))
        if key in real_experience_keys:
            safe_experience.append(entry)
    # Fallback: if the model dropped/garbled every entry, use the untailored
    # profile experience verbatim rather than producing an empty resume.
    if not safe_experience:
        safe_experience = profile.get("experience") or []

    return {
        "summary": tailored.get("summary") or profile.get("summary") or "",
        "featured_skills": featured_skills or list(real_skills),
        "experience": safe_experience,
    }


def _render_resume_docx(profile: dict, tailored: dict, path: str) -> str:
    document = db.new_document_from_template(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "resume_template.docx")
    )

    db.add_title(document, profile.get("full_name") or "")

    contact_parts = [
        p for p in [
            profile.get("email"),
            profile.get("phone"),
            profile.get("location"),
            ", ".join(profile.get("links") or []) or None,
        ] if p
    ]
    db.add_contact_line(document, " | ".join(contact_parts))

    if tailored.get("summary"):
        db.add_heading(document, "Summary")
        db.add_body_text(document, tailored["summary"])

    if tailored.get("experience"):
        db.add_heading(document, "Experience")
        for entry in tailored["experience"]:
            dates = " - ".join(
                [d for d in [entry.get("start_date"), entry.get("end_date")] if d]
            ) or None
            header_parts = [p for p in [entry.get("title"), entry.get("company")] if p]
            header = ", ".join(header_parts)
            trailer = " | ".join([p for p in [entry.get("location"), dates] if p])
            job_line = header + (f" — {trailer}" if trailer else "")
            db.add_job_title_line(document, job_line)
            for bullet in entry.get("bullets") or []:
                db.add_bullet(document, bullet)

    if tailored.get("featured_skills"):
        db.add_heading(document, "Skills")
        db.add_body_text(document, ", ".join(tailored["featured_skills"]))

    if profile.get("education"):
        db.add_heading(document, "Education")
        for edu in profile["education"]:
            dates = " - ".join(
                [d for d in [edu.get("start_date"), edu.get("end_date")] if d]
            ) or None
            parts = [p for p in [edu.get("degree"), edu.get("field")] if p]
            line = ", ".join(parts)
            if edu.get("institution"):
                line = f"{line}, {edu['institution']}" if line else edu["institution"]
            if dates:
                line = f"{line} ({dates})"
            db.add_body_text(document, line)

    if profile.get("certifications"):
        db.add_heading(document, "Certifications")
        db.add_body_text(document, ", ".join(profile["certifications"]))

    return db.save_document(document, path)


def _plain_text_for_rag(tailored: dict) -> str:
    """Flattens the tailored content into plain text for rag.indexer.index_generated_document."""
    parts = [tailored.get("summary") or ""]
    for entry in tailored.get("experience") or []:
        parts.append(f"{entry.get('title')} at {entry.get('company')}")
        parts.extend(entry.get("bullets") or [])
    parts.append(", ".join(tailored.get("featured_skills") or []))
    return "\n".join(p for p in parts if p)


def tailor_resume(user_id: str, profile: dict, job: dict) -> GeneratedDocument:
    """Generates a tailored resume .docx for `job` from `profile`, uploads it
    to S3, persists a GeneratedDocument record, and indexes it for RAG.
    Never fabricates facts not present in `profile` (see module docstring)."""
    chunks = rag_retriever.retrieve_relevant_chunks(
        user_id, query=job.get("description") or "", top_k=8
    )
    past_phrasing_section = format_past_phrasing_section(chunks)

    tailored_raw = _call_tailor_llm(profile, job, past_phrasing_section)
    tailored = _validate_no_fabrication(tailored_raw, profile)

    document_id = str(uuid.uuid4())
    fd, tmp_path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    try:
        _render_resume_docx(profile, tailored, tmp_path)
        s3_key = s3_client.upload_file(tmp_path, f"users/{user_id}/generated/{document_id}.docx")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    display_name = f"Resume — {job.get('title') or 'Role'} at {job.get('company') or 'Company'}.docx"

    record: GeneratedDocument = {
        "document_id": document_id,
        "job_id": job.get("job_id"),
        "profile_id": profile.get("profile_id"),
        "doc_type": "resume",
        "s3_key": s3_key,
        "display_name": display_name,
        "format": "docx",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_notes": f"retrieved_chunks={len(chunks)}",
    }

    json_store.upsert(user_id, "documents", record, "document_id")
    rag_indexer.index_generated_document(user_id, record, _plain_text_for_rag(tailored))

    return record
