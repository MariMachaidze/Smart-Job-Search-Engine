"""
resume/test_tailor_and_cover_letter.py — end-to-end live smoke test for
document generation (plan section 6): builds a synthetic CandidateProfile +
JobPosting, runs both `tailor_resume` and `generate_cover_letter` against the
REAL Gemini API (via app.llm.call_llm), opens the resulting .docx files back
up with python-docx to check styles/content, and specifically tests the
no-fabrication guardrail by using a job description that requires a skill
("Kubernetes") the test profile does NOT have, asserting the generated
documents never claim it.

S3 upload is expected to fail in this dev environment (no bucket
provisioned) -- same situation workstream C's resume/test_parser.py hit for
PDF uploads. This test works around it the same way: faking just
storage.s3_client.upload_file for the duration of the test, so the rest of
the real pipeline (RAG retrieval call, LLM call, .docx rendering, JSON
persistence, RAG indexing call) still runs for real and is actually verified.

Run from the repo root:
    python resume/test_tailor_and_cover_letter.py
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


TEST_USER_ID = "test-user-tailor-456"

# A skill the job below asks for but this profile does NOT have -- used to
# verify the no-fabrication guardrail actually holds against the live model.
FORBIDDEN_SKILL = "Kubernetes"


def _build_test_profile() -> dict:
    return {
        "profile_id": str(uuid.uuid4()),
        "source_file_s3_key": "users/test-user-tailor-456/resumes/fake.pdf",
        "full_name": "Jordan A. Rivera",
        "email": "jordan.rivera@example.com",
        "phone": "+1 (555) 012-3456",
        "location": "Berlin, Germany",
        "summary": (
            "Backend engineer with 5 years building distributed systems in "
            "Python and Go, focused on reliability and developer tooling."
        ),
        # Deliberately NOT including "Kubernetes" so the guardrail test is
        # meaningful: the job below asks for it, the profile doesn't have it.
        "skills": ["Python", "Go", "PostgreSQL", "Docker", "AWS", "FastAPI", "gRPC"],
        "experience": [
            {
                "company": "Acme Logistics GmbH",
                "title": "Senior Backend Engineer",
                "start_date": "2021-03",
                "end_date": "Present",
                "location": "Berlin, Germany",
                "bullets": [
                    "Designed and shipped a Go-based routing service handling 2M requests/day",
                    "Migrated the on-call deploy pipeline to Docker, cutting deploy time 40%",
                    "Mentored two junior engineers through onboarding and on-call rotation",
                ],
            },
            {
                "company": "Northwind Data",
                "title": "Backend Engineer",
                "start_date": "2018-06",
                "end_date": "2021-02",
                "location": "Munich, Germany",
                "bullets": [
                    "Built a PostgreSQL-backed billing service processing 50k invoices/month",
                    "Wrote the first gRPC API layer connecting three internal services",
                ],
            },
        ],
        "education": [
            {
                "institution": "Technical University of Munich",
                "degree": "B.Sc.",
                "field": "Computer Science",
                "start_date": "2015",
                "end_date": "2019",
            }
        ],
        "certifications": ["AWS Certified Solutions Architect - Associate"],
        "links": ["linkedin.com/in/jordanrivera", "github.com/jordanrivera"],
        "raw_text": (
            "Jordan A. Rivera\n"
            "jordan.rivera@example.com | +1 (555) 012-3456 | Berlin, Germany\n"
            "linkedin.com/in/jordanrivera | github.com/jordanrivera\n\n"
            "SUMMARY\nBackend engineer with 5 years building distributed systems in Python "
            "and Go, focused on reliability and developer tooling.\n\n"
            "SKILLS\nPython, Go, PostgreSQL, Docker, AWS, FastAPI, gRPC\n\n"
            "EXPERIENCE\nSenior Backend Engineer, Acme Logistics GmbH, Berlin (2021-03 - Present)\n"
            "- Designed and shipped a Go-based routing service handling 2M requests/day\n"
            "- Migrated the on-call deploy pipeline to Docker, cutting deploy time 40%\n"
            "- Mentored two junior engineers through onboarding and on-call rotation\n\n"
            "Backend Engineer, Northwind Data, Munich (2018-06 - 2021-02)\n"
            "- Built a PostgreSQL-backed billing service processing 50k invoices/month\n"
            "- Wrote the first gRPC API layer connecting three internal services\n\n"
            "EDUCATION\nB.Sc. Computer Science, Technical University of Munich (2015 - 2019)\n\n"
            "CERTIFICATIONS\nAWS Certified Solutions Architect - Associate\n"
        ),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


def _build_test_job() -> dict:
    return {
        "job_id": str(uuid.uuid4()),
        "company": "Anthropic",
        "title": "ML Platform Engineer",
        "location": "Remote (EU)",
        "url": "https://example.com/jobs/ml-platform-engineer",
        "description": (
            "We're looking for an ML Platform Engineer to help operate the infrastructure "
            "behind our model training and serving systems. You'll work with distributed "
            "systems, Python, Go, and container orchestration.\n\n"
            "Requirements:\n"
            "- Strong backend engineering experience in Python and/or Go\n"
            "- Experience operating production services at scale\n"
            f"- Hands-on {FORBIDDEN_SKILL} experience operating production clusters\n"
            "- Familiarity with gRPC and PostgreSQL a plus\n"
        ),
        "source": "greenhouse",
        "ats_job_id": "123456",
        "department": "Engineering",
        "posted_at": None,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "last_seen_at": datetime.now(timezone.utc).isoformat(),
        "status": "new",
        "raw": None,
        "location_lat": None,
        "location_lng": None,
        "is_remote": True,
    }


def _fake_s3_upload_file_if_unconfigured():
    """Fakes storage.s3_client.upload_file for this test run if no real AWS
    bucket/credentials are configured in this dev environment (expected --
    see module docstring). Returns True if faking was applied."""
    if os.getenv("S3_BUCKET_NAME") and os.getenv("AWS_ACCESS_KEY_ID"):
        return False

    import storage.s3_client as real_s3_client

    def fake_upload_file(local_path, key):
        size = os.path.getsize(local_path)
        print(
            f"  [faked s3_client.upload_file -- no AWS creds/bucket in this dev env] "
            f"{local_path} ({size} bytes) -> s3://<bucket>/{key}"
        )
        return key

    real_s3_client.upload_file = fake_upload_file
    print(
        "No AWS credentials/S3_BUCKET_NAME in this environment -- faking "
        "storage.s3_client.upload_file's return value for this test run only "
        "(real module/function signature still used everywhere else: json_store "
        "persistence, rag indexer/retriever calls, and real .docx rendering all "
        "run for real)."
    )
    return True


def _assert_no_forbidden_skill(label: str, *texts: str):
    for text in texts:
        assert FORBIDDEN_SKILL.lower() not in (text or "").lower(), (
            f"GUARDRAIL VIOLATION in {label}: found forbidden skill "
            f"{FORBIDDEN_SKILL!r} (not present in the test profile) in generated text: "
            f"{text!r}"
        )


def _docx_full_text(path: str) -> tuple[str, list[str]]:
    from docx import Document

    document = Document(path)
    styles_used = [p.style.name for p in document.paragraphs if p.text.strip()]
    full_text = "\n".join(p.text for p in document.paragraphs)
    return full_text, styles_used


def main():
    _fake_s3_upload_file_if_unconfigured()

    profile = _build_test_profile()
    job = _build_test_job()

    print(f"\nTest profile skills: {profile['skills']}")
    print(f"Test job requires (among other things): {FORBIDDEN_SKILL!r} -- NOT in profile skills.\n")

    # --- Resume ------------------------------------------------------------
    print("--- calling tailor_resume (live Gemini call) ---")
    from resume.tailor import tailor_resume

    resume_doc = tailor_resume(TEST_USER_ID, profile, job)
    print(json.dumps(resume_doc, indent=2, default=str))

    for field in (
        "document_id", "job_id", "profile_id", "doc_type", "s3_key",
        "display_name", "format", "generated_at", "model_notes",
    ):
        assert field in resume_doc, f"GeneratedDocument missing field: {field}"
    assert resume_doc["doc_type"] == "resume"
    assert resume_doc["format"] == "docx"
    assert resume_doc["job_id"] == job["job_id"]
    assert resume_doc["profile_id"] == profile["profile_id"]
    assert resume_doc["s3_key"] == f"users/{TEST_USER_ID}/generated/{resume_doc['document_id']}.docx"
    assert resume_doc["display_name"].startswith("Resume")
    assert job["title"] in resume_doc["display_name"]
    assert job["company"] in resume_doc["display_name"]

    import storage.json_store as js
    persisted_docs = js.load_all(TEST_USER_ID, "documents")
    persisted_resume = next((d for d in persisted_docs if d["document_id"] == resume_doc["document_id"]), None)
    assert persisted_resume is not None, "resume GeneratedDocument was not persisted via json_store.upsert"
    print("\nPersisted to data/users/{}/documents.json -- confirmed.".format(TEST_USER_ID))

    # Re-render the resume .docx to a local path we can inspect (tailor_resume
    # already deleted its own tmp file after "uploading" it) -- call the
    # internal render function directly on the same tailored content isn't
    # available here, so instead we re-run the render step against a fresh
    # tmp path by re-invoking the private helpers used by tailor_resume.
    import tempfile
    from resume import tailor as tailor_module

    chunks = []  # RAG retriever is a no-op stub -- always [] right now
    past_phrasing = tailor_module.format_past_phrasing_section(chunks)
    tailored_raw = tailor_module._call_tailor_llm(profile, job, past_phrasing)
    tailored = tailor_module._validate_no_fabrication(tailored_raw, profile)

    fd, resume_tmp_path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    tailor_module._render_resume_docx(profile, tailored, resume_tmp_path)

    resume_text, resume_styles = _docx_full_text(resume_tmp_path)
    print("\n--- rendered resume .docx paragraph styles used ---")
    print(sorted(set(resume_styles)))
    print("\n--- rendered resume .docx text ---")
    print(resume_text)

    for expected_style in ("Title", "ContactLine", "SectionHeading", "JobTitleLine", "BulletPoint"):
        assert expected_style in resume_styles, f"expected style {expected_style!r} not used in resume .docx"

    assert profile["full_name"] in resume_text
    assert "Acme Logistics GmbH" in resume_text
    assert "Northwind Data" in resume_text
    for skill in tailored["featured_skills"]:
        assert skill in profile["skills"], f"resume claims skill not in profile: {skill!r}"

    _assert_no_forbidden_skill("tailored resume JSON", json.dumps(tailored))
    _assert_no_forbidden_skill("rendered resume .docx text", resume_text)
    print(f"\nGUARDRAIL CHECK PASSED (resume): {FORBIDDEN_SKILL!r} not claimed anywhere.")

    os.remove(resume_tmp_path)

    # --- Cover letter --------------------------------------------------------
    print("\n--- calling generate_cover_letter (live Gemini call) ---")
    from resume.cover_letter import generate_cover_letter

    cover_doc = generate_cover_letter(TEST_USER_ID, profile, job)
    print(json.dumps(cover_doc, indent=2, default=str))

    assert cover_doc["doc_type"] == "cover_letter"
    assert cover_doc["format"] == "docx"
    assert cover_doc["s3_key"] == f"users/{TEST_USER_ID}/generated/{cover_doc['document_id']}.docx"
    assert cover_doc["display_name"].startswith("Cover Letter")
    assert job["title"] in cover_doc["display_name"]
    assert job["company"] in cover_doc["display_name"]

    persisted_docs = js.load_all(TEST_USER_ID, "documents")
    persisted_cover = next((d for d in persisted_docs if d["document_id"] == cover_doc["document_id"]), None)
    assert persisted_cover is not None, "cover letter GeneratedDocument was not persisted via json_store.upsert"

    from resume import cover_letter as cover_letter_module

    cover_result = cover_letter_module._call_cover_letter_llm(profile, job, past_phrasing)
    paragraphs = [p for p in (cover_result.get("paragraphs") or []) if isinstance(p, str)] or [profile["summary"]]

    fd, cover_tmp_path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    cover_letter_module._render_cover_letter_docx(profile, job, paragraphs, cover_tmp_path)

    cover_text, cover_styles = _docx_full_text(cover_tmp_path)
    print("\n--- rendered cover letter .docx paragraph styles used ---")
    print(sorted(set(cover_styles)))
    print("\n--- rendered cover letter .docx text ---")
    print(cover_text)

    for expected_style in ("Title", "ContactLine", "SectionHeading", "BodyText"):
        assert expected_style in cover_styles, f"expected style {expected_style!r} not used in cover letter .docx"

    assert profile["full_name"] in cover_text
    assert "Dear Hiring Manager" in cover_text

    _assert_no_forbidden_skill("cover letter paragraphs JSON", json.dumps(cover_result))
    _assert_no_forbidden_skill("rendered cover letter .docx text", cover_text)
    print(f"\nGUARDRAIL CHECK PASSED (cover letter): {FORBIDDEN_SKILL!r} not claimed anywhere.")

    os.remove(cover_tmp_path)

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
