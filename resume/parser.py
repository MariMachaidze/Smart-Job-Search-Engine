"""
resume/parser.py — PDF resume -> structured CandidateProfile (plan section 4).

Pipeline:
  1. `extract_text_from_pdf`: layout-aware text extraction via `pdfplumber`
     (chosen over `pypdf` specifically because it handles multi-column resume
     layouts much better).
  2. `extract_profile_from_pdf`: sends that text to Gemini via the existing
     `app.llm.call_llm` wrapper with a strict JSON-only extraction prompt,
     defensively parses the response, fills in the non-LLM-derived fields
     (profile_id, source_file_s3_key, raw_text, extracted_at), uploads the
     original PDF to S3, persists the profile via the storage layer, and
     wires it into the RAG indexer.

OCR is explicitly out of scope (see plan section 4): a near-empty text
extraction (typically a scanned/image-only PDF) raises `ValueError` rather
than silently producing a near-empty profile.
"""
import json
import re
import uuid
from datetime import datetime, timezone

import pdfplumber

from app.llm import call_llm
from storage.schemas import CandidateProfile
from storage import json_store
from storage import s3_client
from rag import indexer as rag_indexer


# Below this many characters of extracted text, the PDF is almost certainly a
# scanned image (no embedded text layer) or empty/corrupt -- not something
# this parser can handle (OCR is out of scope for MVP).
MIN_EXTRACTED_TEXT_CHARS = 50

# Fields the LLM is responsible for; everything else on CandidateProfile
# (profile_id, source_file_s3_key, raw_text, extracted_at) is filled in code.
_LLM_PROFILE_FIELDS = (
    "full_name", "email", "phone", "location", "summary",
    "skills", "experience", "education", "certifications", "links",
)

_EXTRACTION_PROMPT_TEMPLATE = """You are extracting structured data from a candidate's resume. Below is the raw text extracted from their resume PDF.

Return ONLY a single JSON object (no markdown code fences, no commentary before or after it) with EXACTLY these fields:

{{
  "full_name": string,
  "email": string or null,
  "phone": string or null,
  "location": string or null,
  "summary": string,
  "skills": [string, ...],
  "experience": [
    {{
      "company": string,
      "title": string,
      "start_date": string or null,
      "end_date": string or null,
      "location": string or null,
      "bullets": [string, ...]
    }}, ...
  ],
  "education": [
    {{
      "institution": string,
      "degree": string or null,
      "field": string or null,
      "start_date": string or null,
      "end_date": string or null
    }}, ...
  ],
  "certifications": [string, ...],
  "links": [string, ...]
}}

Rules:
- Use ONLY information that is actually present in the resume text below. Do NOT invent, guess, or hallucinate any employer, title, date, skill, school, or certification that isn't there.
- If a field cannot be determined from the text, use `null` for single-value fields or `[]` for list fields. Do not omit any of the fields above.
- "summary" should be a short (1-3 sentence) synthesis of the candidate's background, written using only facts present in the text. If there's no explicit summary/objective section, write a brief one derived strictly from the experience/skills present. If even that isn't possible, use an empty string.
- Dates should be copied as they appear in the text (e.g. "2021-03", "March 2021", "2019"); do not normalize or invent a format.
- "links" should include things like LinkedIn/GitHub/portfolio URLs if present.
- Output must be valid JSON and nothing else.

Resume text:
---
{resume_text}
---
"""

_STRICT_JSON_RETRY_SUFFIX = (
    "\n\nYour previous response could not be parsed as JSON. Return ONLY a "
    "valid JSON object as specified above. No markdown code fences, no "
    "backticks, no explanation, no leading or trailing text of any kind -- "
    "the entire response must be valid JSON."
)

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extracts plain text from a PDF using pdfplumber's layout-aware
    extraction (handles multi-column resumes far better than naive
    pypdf-style extraction). Returns the concatenated text of all pages,
    stripped of leading/trailing whitespace. Returns "" if the PDF has no
    extractable text layer (e.g. a scanned image)."""
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                text_parts.append(page_text.strip())
    return "\n\n".join(text_parts).strip()


def _strip_code_fences(raw: str) -> str:
    """Strips a leading/trailing ```json ... ``` or ``` ... ``` fence if
    present, since Gemini frequently wraps JSON responses in one despite
    being told not to."""
    stripped = raw.strip()
    match = _CODE_FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def _parse_llm_json(raw_response: str) -> dict:
    cleaned = _strip_code_fences(raw_response or "")
    return json.loads(cleaned)


def _extract_fields_via_llm(resume_text: str) -> dict:
    """Calls Gemini (via app.llm.call_llm) to extract CandidateProfile fields
    as JSON, defensively parsing the response. Retries once with a stricter
    "JSON only" follow-up prompt if the first response doesn't parse."""
    prompt = _EXTRACTION_PROMPT_TEMPLATE.format(resume_text=resume_text)
    raw_response = call_llm(prompt)
    try:
        return _parse_llm_json(raw_response)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    raw_retry = call_llm(prompt + _STRICT_JSON_RETRY_SUFFIX)
    try:
        return _parse_llm_json(raw_retry)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(
            "Gemini did not return parseable JSON for resume field "
            f"extraction, even after a stricter retry. Last raw response "
            f"(truncated): {raw_retry[:500]!r}"
        ) from exc


def _normalize_profile_fields(data: dict) -> dict:
    """Defensively normalizes the LLM's parsed JSON onto the expected
    CandidateProfile field shapes, in case the model omits a field or
    returns a slightly-off type despite the prompt's instructions."""
    if not isinstance(data, dict):
        data = {}

    def _str_or_none(value):
        return value if isinstance(value, str) and value.strip() else None

    def _list_of(value):
        return value if isinstance(value, list) else []

    return {
        "full_name": data.get("full_name") or "",
        "email": _str_or_none(data.get("email")),
        "phone": _str_or_none(data.get("phone")),
        "location": _str_or_none(data.get("location")),
        "summary": data.get("summary") or "",
        "skills": _list_of(data.get("skills")),
        "experience": _list_of(data.get("experience")),
        "education": _list_of(data.get("education")),
        "certifications": _list_of(data.get("certifications")),
        "links": _list_of(data.get("links")),
    }


def extract_profile_from_pdf(user_id: str, pdf_path: str) -> CandidateProfile:
    """Parses a resume PDF into a CandidateProfile: extracts text, sends it
    to Gemini for structured extraction, uploads the original PDF to S3,
    persists the resulting profile, and indexes it for RAG retrieval.

    Raises ValueError if the PDF has no usable text layer (likely a scanned
    image -- OCR is out of scope) or if Gemini's output can't be parsed as
    JSON even after a retry.
    """
    raw_text = extract_text_from_pdf(pdf_path)
    if len(raw_text) < MIN_EXTRACTED_TEXT_CHARS:
        raise ValueError(
            f"Only {len(raw_text)} character(s) of text could be extracted "
            f"from {pdf_path!r}. This usually means the PDF is a scanned "
            "image with no embedded text layer (pdfplumber can only read "
            "real text, not pixels), or the file is empty/corrupt. OCR is "
            "out of scope for this parser -- please upload a resume "
            "exported as a text-based PDF instead."
        )

    extracted = _extract_fields_via_llm(raw_text)
    fields = _normalize_profile_fields(extracted)

    profile_id = str(uuid.uuid4())
    extracted_at = datetime.now(timezone.utc).isoformat()

    s3_key = s3_client.upload_file(
        pdf_path, f"users/{user_id}/resumes/{profile_id}.pdf"
    )

    profile: CandidateProfile = {
        "profile_id": profile_id,
        "source_file_s3_key": s3_key,
        "full_name": fields["full_name"],
        "email": fields["email"],
        "phone": fields["phone"],
        "location": fields["location"],
        "summary": fields["summary"],
        "skills": fields["skills"],
        "experience": fields["experience"],
        "education": fields["education"],
        "certifications": fields["certifications"],
        "links": fields["links"],
        "raw_text": raw_text,
        "extracted_at": extracted_at,
    }

    json_store.save_profile(user_id, profile)
    rag_indexer.index_profile(user_id, profile)

    return profile
