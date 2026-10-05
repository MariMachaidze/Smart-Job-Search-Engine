"""
app/test_main.py -- end-to-end live smoke test for the API backend
(workstream M, plan section 13), following this repo's established
convention (see resume/test_parser.py, orchestrator/test_graphs.py,
qualifications/test_updater.py): a throwaway test user under a temporary
DATA_DIR (never touches the real data/ tree, cleaned up at the end),
driven through FastAPI's real `TestClient` against the real `app.main.app`
-- every route actually runs its real underlying module (storage,
resume.parser, scraper/orchestrator graphs, tracker.service,
stats.aggregator/skill_gap, storage.s3_client), not a mocked app.

What's REAL vs mocked, and exactly why:
  - REAL: signup/login/me, companies CRUD, preferences (including a LIVE
    OSM Nominatim geocode call -- no Gemini involved), GET /jobs,
    POST /jobs/{id}/feedback (+ the MemoryEntry side effect), GET /tracker/*,
    GET /documents + its presigned-URL download route, GET /statistics/*.
  - MOCKED (standing instruction: no live Gemini calls in this environment,
    full stop, independent of quota): app.llm.call_llm, at the exact import
    site each caller bound it to (`from app.llm import call_llm` is a name
    binding, not a live module reference -- patching app.llm.call_llm
    itself would NOT intercept matching.scorer's/resume.tailor's/
    resume.cover_letter's/resume.parser's already-bound local name, so each
    is patched at its own module, same convention orchestrator/test_graphs.py
    already established for exactly this reason):
      * matching.scorer.call_llm      -- used by POST /discovery/run (via
        discovery_graph -> score_job)
      * resume.tailor.call_llm,
        resume.cover_letter.call_llm  -- used by POST /jobs/{id}/tailor
        (via tailoring_graph)
      * resume.parser.call_llm        -- used by POST /profile/upload (via
        resume.parser.extract_profile_from_pdf). NOTE: the task brief named
        only the two routes above as LLM-triggering; /profile/upload also
        calls Gemini (to extract structured fields from the resume text)
        and was not called out. Since the standing instruction is "no live
        Gemini calls, period" -- not "only mock the two named routes" --
        this one is mocked too, for the same reason, even though it isn't
        in the brief's list. Flagged explicitly in the final report as a
        judgment call.
  - MOCKED (unrelated to the Gemini constraint -- same workaround every
    other workstream's tests in this repo use, since no AWS bucket is
    configured in this dev environment): storage.s3_client.upload_file and
    storage.s3_client.get_presigned_url.
  - discover_company_jobs is also replaced with a small fixed/synthetic
    job list (2 remote postings) rather than a real ATS fetch -- NOT for
    the Gemini constraint, but because a real Greenhouse board can return
    hundreds of jobs (638 observed by workstream B/F), each of which would
    need geocoding at OSM Nominatim's ~1 req/sec usage-policy cap, which
    would make this test take many minutes for no benefit to what THIS
    workstream needs to verify (that POST /discovery/run correctly wires
    into discovery_graph.ainvoke and returns a sane summary). Marking the
    jobs "remote" also means persist_jobs_node's geocoding step is a no-op
    by design (enrich_job_location short-circuits remote jobs), so this
    stays fast without disabling anything real about the graph itself.
    Workstream B/F's own tests already cover real ATS fetch + real
    geocoding end-to-end.

Run from the repo root:
    python app/test_main.py
"""
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _fake_s3_if_unconfigured():
    """Same workaround as resume/test_parser.py and orchestrator/test_graphs.py:
    fake storage.s3_client's two functions this workstream's routes touch
    (upload_file via resume.parser/resume.tailor/resume.cover_letter;
    get_presigned_url via app.routes_documents) if no AWS bucket is
    configured in this dev environment."""
    if os.getenv("S3_BUCKET_NAME") and os.getenv("AWS_ACCESS_KEY_ID"):
        print("Real AWS credentials/S3_BUCKET_NAME found -- using the real S3 client.")
        return

    import storage.s3_client as real_s3_client

    def fake_upload_file(local_path, key):
        size = os.path.getsize(local_path)
        print(f"  [faked s3_client.upload_file] {local_path} ({size} bytes) -> s3://<bucket>/{key}")
        return key

    def fake_get_presigned_url(key, expires_in=3600):
        url = f"https://fake-bucket.s3.amazonaws.com/{key}?X-Fake-Presigned=1&expires_in={expires_in}"
        print(f"  [faked s3_client.get_presigned_url] {key} -> {url}")
        return url

    real_s3_client.upload_file = fake_upload_file
    real_s3_client.get_presigned_url = fake_get_presigned_url
    print(
        "No AWS credentials/S3_BUCKET_NAME in this environment -- faking "
        "storage.s3_client.upload_file/get_presigned_url's return values only "
        "(every other part of each pipeline -- .docx rendering, PDF parsing, "
        "json_store persistence, RAG calls -- still runs for real)."
    )


def _mock_llm_everywhere():
    """Patches app.llm.call_llm at every site that imported it directly
    (`from app.llm import call_llm`), per this module's docstring: the
    standing no-live-Gemini-calls instruction applies regardless of quota,
    so nothing here is a live probe/fallback like orchestrator/test_graphs.py's
    quota-exhaustion check -- it's an unconditional mock."""
    import matching.scorer as scorer_module
    import resume.cover_letter as cover_letter_module
    import resume.parser as parser_module
    import resume.tailor as tailor_module

    def fake_scorer_call_llm(prompt: str) -> str:
        return (
            '{"score": 85, "rationale": "Mocked score: strong Python/FastAPI match.", '
            '"matched_skills": ["Python", "FastAPI"], "missing_skills": []}'
        )

    def fake_tailor_call_llm(prompt: str) -> str:
        return (
            '{"summary": "Backend engineer with experience building distributed '
            'systems in Python.", "featured_skills": ["Python", "FastAPI", '
            '"PostgreSQL", "Docker"], "experience": [{"company": "API Test GmbH", '
            '"title": "Backend Engineer", "location": "Berlin, Germany", '
            '"start_date": "2020-01", "end_date": "Present", "bullets": '
            '["Built REST APIs serving millions of requests/day"]}]}'
        )

    def fake_cover_letter_call_llm(prompt: str) -> str:
        return (
            '{"paragraphs": ["I am excited to apply for this role.", '
            '"At API Test GmbH I built REST APIs serving millions of requests per '
            'day.", "I would welcome the chance to contribute these skills here."]}'
        )

    def fake_parser_call_llm(prompt: str) -> str:
        return (
            '{"full_name": "API Test Candidate", "email": "api.test@example.com", '
            '"phone": "+49 30 0000000", "location": "Berlin, Germany", '
            '"summary": "Backend engineer with experience in Python and FastAPI.", '
            '"skills": ["Python", "FastAPI", "PostgreSQL", "Docker"], '
            '"experience": [{"company": "API Test GmbH", "title": "Backend Engineer", '
            '"start_date": "2020-01", "end_date": "Present", "location": "Berlin, Germany", '
            '"bullets": ["Built REST APIs serving millions of requests/day"]}], '
            '"education": [{"institution": "TU Berlin", "degree": "B.Sc.", '
            '"field": "Computer Science", "start_date": "2016", "end_date": "2020"}], '
            '"certifications": [], "links": []}'
        )

    scorer_module.call_llm = fake_scorer_call_llm
    tailor_module.call_llm = fake_tailor_call_llm
    cover_letter_module.call_llm = fake_cover_letter_call_llm
    parser_module.call_llm = fake_parser_call_llm
    print(
        "Mocked app.llm.call_llm at every import site (matching.scorer, "
        "resume.tailor, resume.cover_letter, resume.parser) -- NO live Gemini "
        "call will happen anywhere in this test run, per the standing "
        "no-live-Gemini-calls instruction."
    )


def _generate_sample_resume_pdf(path: str) -> None:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(path, pagesize=LETTER)
    _, height = LETTER
    y = height - 72

    def line(text, size=11, gap=16):
        nonlocal y
        c.setFont("Helvetica", size)
        c.drawString(72, y, text)
        y -= gap

    line("API Test Candidate", size=16, gap=22)
    line("api.test@example.com | +49 30 0000000 | Berlin, Germany", size=10, gap=24)
    line("SUMMARY", size=13, gap=16)
    line("Backend engineer with experience in Python and FastAPI.", size=10, gap=22)
    line("SKILLS", size=13, gap=16)
    line("Python, FastAPI, PostgreSQL, Docker", size=10, gap=22)
    line("EXPERIENCE", size=13, gap=16)
    line("Backend Engineer, API Test GmbH, Berlin (2020-01 - Present)", size=10, gap=14)
    line("- Built REST APIs serving millions of requests/day", size=10, gap=22)
    line("EDUCATION", size=13, gap=16)
    line("B.Sc. Computer Science, TU Berlin (2016 - 2020)", size=10, gap=16)
    c.save()


def _fake_discover_company_jobs():
    """Patches the name discovery_graph's discover_jobs_node actually
    calls (bound via `from scraper.discovery import ... discover_company_jobs`
    into orchestrator.discovery_graph's own module globals) with a small
    fixed, synthetic, all-remote job list. See module docstring for why."""
    from datetime import datetime, timezone

    import orchestrator.discovery_graph as dg

    async def fake_discover_company_jobs(playwright, company, careers_url):
        now = datetime.now(timezone.utc).isoformat()
        return [
            {
                "job_id": f"apitest-job-{i}",
                "company": company,
                "title": f"Backend Engineer {i}",
                "location": "Remote",
                "url": f"https://example.com/jobs/apitest-{i}",
                "description": "We need a backend engineer skilled in Python, FastAPI, and PostgreSQL.",
                "source": "scraper",
                "ats_job_id": None,
                "department": None,
                "posted_at": None,
                "discovered_at": now,
                "last_seen_at": now,
                "status": "new",
                "raw": None,
                "location_lat": None,
                "location_lng": None,
                "is_remote": True,
            }
            for i in range(2)
        ]

    dg.discover_company_jobs = fake_discover_company_jobs


def main():
    tmp_data_dir = tempfile.mkdtemp(prefix="api_backend_test_")
    os.environ["DATA_DIR"] = tmp_data_dir
    print(f"Using throwaway DATA_DIR: {tmp_data_dir}\n")

    pdf_path = os.path.join(tmp_data_dir, "_sample_resume.pdf")

    try:
        _fake_s3_if_unconfigured()
        _mock_llm_everywhere()
        _fake_discover_company_jobs()

        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)

        # -------------------------------------------------------------
        # Health + unauthenticated access
        # -------------------------------------------------------------
        r = client.get("/health")
        assert r.status_code == 200 and r.json()["status"] == "ok"

        r = client.get("/profile")
        assert r.status_code in (401, 403), f"expected 401/403 with no auth header, got {r.status_code}"
        print("Health check OK; unauthenticated /profile correctly rejected.\n")

        # -------------------------------------------------------------
        # Signup / login / me (real -- no LLM involved)
        # -------------------------------------------------------------
        email = "api-backend-test@example.com"
        password = "correct-horse-battery-staple"

        r = client.post("/auth/signup", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        signup_body = r.json()
        token = signup_body["access_token"]
        user_id = signup_body["user"]["user_id"]
        headers = {"Authorization": f"Bearer {token}"}
        print(f"Signed up throwaway user {user_id}.\n")

        r = client.get("/auth/me", headers=headers)
        assert r.status_code == 200 and r.json()["user_id"] == user_id

        r = client.get("/tracker/statuses", headers=headers)
        assert r.status_code == 200
        statuses = r.json()
        assert len(statuses) == 14, f"expected 14 seeded default statuses, got {len(statuses)}"
        print("GET /tracker/statuses confirms main.py's tracker router is correctly mounted "
              f"and signup seeded {len(statuses)} default statuses.\n")

        # -------------------------------------------------------------
        # Profile upload (REAL pdfplumber extraction + S3-upload call;
        # MOCKED Gemini call -- see module docstring)
        # -------------------------------------------------------------
        _generate_sample_resume_pdf(pdf_path)
        with open(pdf_path, "rb") as f:
            r = client.post(
                "/profile/upload",
                files={"file": ("resume.pdf", f, "application/pdf")},
                headers=headers,
            )
        assert r.status_code == 200, r.text
        profile = r.json()
        assert profile["full_name"] == "API Test Candidate"
        assert "Python" in profile["skills"]
        profile_id = profile["profile_id"]
        print(f"POST /profile/upload succeeded, profile_id={profile_id}.\n")

        r = client.get("/profile", headers=headers)
        assert r.status_code == 200 and r.json()["profile_id"] == profile_id
        print("GET /profile round-trips the uploaded profile.\n")

        # -------------------------------------------------------------
        # Companies CRUD (real)
        # -------------------------------------------------------------
        r = client.post("/companies", json={"company": "Test Co", "careers_url": "https://testco.example.com/careers"}, headers=headers)
        assert r.status_code == 200, r.text
        company_id = r.json()["company_id"]

        r = client.get("/companies", headers=headers)
        assert r.status_code == 200 and len(r.json()) == 1

        r = client.delete(f"/companies/{company_id}", headers=headers)
        assert r.status_code == 200

        r = client.get("/companies", headers=headers)
        assert r.status_code == 200 and r.json() == []
        print("Companies CRUD (create/list/delete) confirmed.\n")

        # Re-add one company -- discover_company_jobs is faked regardless of
        # what this points to, but load_companies_node needs >=1 entry to
        # even attempt a discovery pass.
        r = client.post("/companies", json={"company": "Rigged Co", "careers_url": "https://rigged.example.com/careers"}, headers=headers)
        assert r.status_code == 200, r.text

        # -------------------------------------------------------------
        # Preferences (real -- including a LIVE OSM Nominatim geocode call,
        # which is NOT Gemini and is fine to call live per the task brief)
        # -------------------------------------------------------------
        r = client.get("/preferences", headers=headers)
        assert r.status_code == 200
        assert r.json()["remote_preference"] == "no_preference"

        r = client.patch(
            "/preferences",
            json={
                "home_location": "Berlin, Germany",
                "max_commute_km": 50.0,
                "remote_preference": "onsite_ok",
                "willing_to_relocate": False,
            },
            headers=headers,
        )
        assert r.status_code == 200, r.text
        prefs = r.json()
        assert prefs["home_lat"] is not None and prefs["home_lng"] is not None, (
            "expected a real geocoded home_lat/home_lng from a live Nominatim call"
        )
        print(f"PATCH /preferences live-geocoded 'Berlin, Germany' -> "
              f"({prefs['home_lat']}, {prefs['home_lng']}).\n")

        # -------------------------------------------------------------
        # Discovery run (MOCKED Gemini via matching.scorer.call_llm;
        # real graph wiring, real persistence, fixed synthetic job list)
        # -------------------------------------------------------------
        r = client.post("/discovery/run", headers=headers)
        assert r.status_code == 200, r.text
        discovery_result = r.json()
        assert discovery_result["persisted_jobs_count"] == 2, discovery_result
        assert discovery_result["scored_jobs_count"] == 2, discovery_result
        assert discovery_result["errors"] == [], discovery_result
        print(f"POST /discovery/run: {discovery_result}\n")

        # -------------------------------------------------------------
        # GET /jobs (real join of jobs.json + scores.json)
        # -------------------------------------------------------------
        r = client.get("/jobs", headers=headers)
        assert r.status_code == 200
        jobs = r.json()
        assert len(jobs) == 2
        assert all(j["score"] == 85 for j in jobs), jobs
        job_a, job_b = jobs[0]["job_id"], jobs[1]["job_id"]
        print(f"GET /jobs returned 2 scored jobs: {job_a}, {job_b}.\n")

        # -------------------------------------------------------------
        # POST /jobs/{id}/feedback (real; also writes a MemoryEntry since a
        # reason is given -- verified directly via json_store, since this
        # workstream owns no GET /memory route)
        # -------------------------------------------------------------
        r = client.post(
            f"/jobs/{job_a}/feedback",
            json={"feedback": "not_relevant", "reason": "too much travel"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        feedback_result = r.json()
        assert feedback_result["user_feedback"] == "not_relevant"
        assert feedback_result["feedback_reason"] == "too much travel"

        from storage import json_store as _js
        memory_entries = _js.load_all(user_id, "memory")
        assert len(memory_entries) == 1, memory_entries
        assert "too much travel" in memory_entries[0]["content"]
        assert memory_entries[0]["category"] == "feedback"
        print("POST /jobs/{id}/feedback confirmed, including the derived MemoryEntry "
              f"(plan section 5/12): {memory_entries[0]['content']!r}\n")

        # -------------------------------------------------------------
        # POST /jobs/{id}/tailor (MOCKED Gemini via resume.tailor.call_llm /
        # resume.cover_letter.call_llm; real tailoring_graph fan-out/fan-in,
        # real .docx rendering, real (faked-S3) persistence)
        # -------------------------------------------------------------
        r = client.post(f"/jobs/{job_b}/tailor", headers=headers)
        assert r.status_code == 200, r.text
        tailor_result = r.json()
        assert tailor_result["errors"] == [], tailor_result
        resume_doc = tailor_result["resume_doc"]
        cover_letter_doc = tailor_result["cover_letter_doc"]
        assert resume_doc is not None and resume_doc["doc_type"] == "resume"
        assert cover_letter_doc is not None and cover_letter_doc["doc_type"] == "cover_letter"
        assert resume_doc["job_id"] == job_b and cover_letter_doc["job_id"] == job_b
        print(f"POST /jobs/{{id}}/tailor produced: {resume_doc['display_name']!r}, "
              f"{cover_letter_doc['display_name']!r}.\n")

        # -------------------------------------------------------------
        # Documents (real)
        # -------------------------------------------------------------
        r = client.get("/documents", headers=headers)
        assert r.status_code == 200
        documents = r.json()
        assert len(documents) == 2, documents
        doc_ids = {d["document_id"] for d in documents}
        assert resume_doc["document_id"] in doc_ids and cover_letter_doc["document_id"] in doc_ids

        r = client.get(f"/documents/{resume_doc['document_id']}/download", headers=headers)
        assert r.status_code == 200, r.text
        download = r.json()
        assert download["url"].startswith("https://fake-bucket.s3.amazonaws.com/") or "s3" in download["url"]
        assert download["display_name"] == resume_doc["display_name"]
        print(f"GET /documents and /documents/{{id}}/download confirmed: {download['url']}\n")

        # -------------------------------------------------------------
        # Statistics (real; no applications created in this run, so these
        # exercise the "empty but well-formed" paths)
        # -------------------------------------------------------------
        r = client.get("/statistics/summary", headers=headers)
        assert r.status_code == 200
        summary = r.json()
        assert summary["total_applications"] == 0
        assert summary["rejection_rate"] == 0.0

        r = client.get("/statistics/timeseries?granularity=daily", headers=headers)
        assert r.status_code == 200 and r.json() == []

        r = client.get("/statistics/skill-gap", headers=headers)
        assert r.status_code == 200
        skill_gap = r.json()
        assert skill_gap["threshold_met"] is False
        print(f"GET /statistics/summary, /timeseries, /skill-gap all confirmed well-formed: "
              f"{summary}\n")

        # -------------------------------------------------------------
        # Cross-user isolation sanity check: a second user must not see the
        # first user's data.
        # -------------------------------------------------------------
        r = client.post("/auth/signup", json={"email": "api-backend-test-2@example.com", "password": password})
        assert r.status_code == 200
        other_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

        r = client.get("/jobs", headers=other_headers)
        assert r.status_code == 200 and r.json() == [], "second user must not see the first user's jobs"
        r = client.get("/profile", headers=other_headers)
        assert r.status_code == 404, "second user must not see the first user's profile"
        print("Cross-user isolation confirmed: a brand-new user sees none of the first user's data.\n")

        print("ALL CHECKS PASSED.")
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        shutil.rmtree(tmp_data_dir, ignore_errors=True)
        os.environ.pop("DATA_DIR", None)
        print(f"\nCleaned up throwaway DATA_DIR: {tmp_data_dir}")


if __name__ == "__main__":
    main()
