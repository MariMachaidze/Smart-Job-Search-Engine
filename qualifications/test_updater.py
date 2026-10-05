"""
qualifications/test_updater.py -- end-to-end smoke test for the
qualifications prompt updater (plan section 8a, workstream R).

Seeds a throwaway test user under a temp DATA_DIR (so it never touches the
real data/ tree) with:
  - a CandidateProfile lacking a couple of in-demand skills
  - two MatchScore records with user_feedback == "not_relevant" and real
    feedback_reason text ("too much travel", "wrong tech stack")
  - a few rejected Applications (joined against seeded JobPosting +
    TrackerStatus records) whose job descriptions require skills the seeded
    profile doesn't have

stats.skill_gap.analyze_rejection_patterns and tracker.service.list_applications
are owned by other workstreams (J, I) that may not have landed yet. This test
checks which is real vs stubs it locally to match the documented contract,
printing which path was taken either way.

Runs update_qualifications_prompt against the REAL Gemini API (via
app.llm.call_llm, no mocking) twice, and checks:
  - prompt_text actually reflects the seeded signal (mentions travel /
    missing skills), not just a restatement of the raw profile
  - the second call increments `version` and both records are retained in
    qualifications.json (history, not overwrite)
  - get_latest_qualifications returns the newer record

Run from the repo root:
    python qualifications/test_updater.py
"""
import importlib
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

USER_ID = "qual-test-user-001"


def _check_dependency_status():
    """Reports whether stats.skill_gap / tracker.service are real modules on
    disk yet, since the task wants this noted explicitly either way."""
    try:
        importlib.import_module("stats.skill_gap")
        print("stats.skill_gap found on disk -- real analyze_rejection_patterns will be used.")
    except ModuleNotFoundError:
        print(
            "stats.skill_gap NOT found on disk (workstream J not landed yet) -- "
            "qualifications/updater.py's own ImportError fallback (a local stand-in "
            "returning {missing_skills: [], recommendation: ''}) will be used."
        )

    try:
        importlib.import_module("tracker.service")
        print("tracker.service found on disk -- real list_applications will be used.")
    except ModuleNotFoundError:
        print(
            "tracker.service NOT found on disk (workstream I not landed yet) -- "
            "qualifications/updater.py's local join of applications/jobs/tracker_statuses "
            "will be used instead."
        )


def _seed_data(data_dir: str):
    """Writes profile.json, scores.json, jobs.json, tracker_statuses.json,
    and applications.json directly via storage.json_store for USER_ID."""
    from storage import json_store

    profile = {
        "profile_id": "profile_qual_test_1",
        "source_file_s3_key": "users/qual-test-user-001/resumes/profile_qual_test_1.pdf",
        "full_name": "Alex Tester",
        "email": "alex@example.com",
        "phone": None,
        "location": "Berlin, Germany",
        "summary": "Backend engineer with 4 years of Python experience building REST APIs.",
        "skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
        "experience": [
            {
                "company": "Acme GmbH",
                "title": "Backend Engineer",
                "start_date": "2021-01",
                "end_date": "present",
                "location": "Berlin",
                "bullets": ["Built REST APIs in Python/FastAPI", "Managed PostgreSQL schemas"],
            }
        ],
        "education": [
            {"institution": "TU Berlin", "degree": "B.Sc.", "field": "Computer Science",
             "start_date": "2016", "end_date": "2020"}
        ],
        "certifications": [],
        "links": [],
        "raw_text": "Alex Tester resume raw text...",
        "extracted_at": "2026-09-01T00:00:00+00:00",
    }
    json_store.save_profile(USER_ID, profile)

    jobs = [
        {
            "job_id": "job_travel_1",
            "company": "Globetrotter Consulting",
            "title": "Field Solutions Engineer",
            "location": "Berlin (60% travel)",
            "url": "https://example.com/jobs/job_travel_1",
            "description": "Requires 60% travel across EU client sites to deliver on-prem installs.",
            "source": "scraper",
            "ats_job_id": None,
            "department": None,
            "posted_at": "2026-08-01",
            "discovered_at": "2026-08-01T00:00:00+00:00",
            "last_seen_at": "2026-08-01T00:00:00+00:00",
            "status": "seen",
            "raw": None,
            "location_lat": None,
            "location_lng": None,
            "is_remote": False,
        },
        {
            "job_id": "job_stack_1",
            "company": "KubeScale AI",
            "title": "ML Platform Engineer",
            "location": "Remote",
            "url": "https://example.com/jobs/job_stack_1",
            "description": "Must have deep Kubernetes, Go, and Kafka experience to run our ML platform.",
            "source": "scraper",
            "ats_job_id": None,
            "department": None,
            "posted_at": "2026-08-05",
            "discovered_at": "2026-08-05T00:00:00+00:00",
            "last_seen_at": "2026-08-05T00:00:00+00:00",
            "status": "seen",
            "raw": None,
            "location_lat": None,
            "location_lng": None,
            "is_remote": True,
        },
        {
            "job_id": "job_stack_2",
            "company": "DataGrid Systems",
            "title": "Data Infrastructure Engineer",
            "location": "Remote",
            "url": "https://example.com/jobs/job_stack_2",
            "description": "Looking for strong Rust and distributed systems (Kafka, gRPC) experience.",
            "source": "scraper",
            "ats_job_id": None,
            "department": None,
            "posted_at": "2026-08-10",
            "discovered_at": "2026-08-10T00:00:00+00:00",
            "last_seen_at": "2026-08-10T00:00:00+00:00",
            "status": "seen",
            "raw": None,
            "location_lat": None,
            "location_lng": None,
            "is_remote": True,
        },
    ]
    json_store.save_all(USER_ID, "jobs", jobs)

    scores = [
        {
            "match_id": "match_1",
            "job_id": "job_travel_1",
            "profile_id": profile["profile_id"],
            "score": 55.0,
            "rationale": "Backend skills partially match but role is field-based.",
            "matched_skills": ["Python"],
            "missing_skills": [],
            "scored_at": "2026-08-02T00:00:00+00:00",
            "user_feedback": "not_relevant",
            "feedback_reason": "too much travel",
        },
        {
            "match_id": "match_2",
            "job_id": "job_stack_1",
            "profile_id": profile["profile_id"],
            "score": 40.0,
            "rationale": "Candidate lacks Kubernetes/Go depth required.",
            "matched_skills": [],
            "missing_skills": ["Kubernetes", "Go", "Kafka"],
            "scored_at": "2026-08-06T00:00:00+00:00",
            "user_feedback": "not_relevant",
            "feedback_reason": "wrong tech stack",
        },
    ]
    json_store.save_all(USER_ID, "scores", scores)

    tracker_statuses = [
        {"status_id": "status_rejected", "user_id": USER_ID, "label": "Rejected", "color": "#B71C1C", "order": 1},
        {"status_id": "status_applied", "user_id": USER_ID, "label": "Applied", "color": "#C8E6C9", "order": 0},
    ]
    json_store.save_all(USER_ID, "tracker_statuses", tracker_statuses)

    applications = [
        {
            "application_id": "app_1",
            "user_id": USER_ID,
            "job_id": "job_stack_1",
            "status_id": "status_rejected",
            "date_applied": "2026-08-06",
            "referred_by": "",
            "comments": "Rejected after screen -- cited lack of Kubernetes/Go experience.",
            "created_at": "2026-08-06T00:00:00+00:00",
            "updated_at": "2026-08-12T00:00:00+00:00",
        },
        {
            "application_id": "app_2",
            "user_id": USER_ID,
            "job_id": "job_stack_2",
            "status_id": "status_rejected",
            "date_applied": "2026-08-11",
            "referred_by": "",
            "comments": "Rejected -- team wanted Rust/distributed-systems background.",
            "created_at": "2026-08-11T00:00:00+00:00",
            "updated_at": "2026-08-15T00:00:00+00:00",
        },
    ]
    json_store.save_all(USER_ID, "applications", applications)


def main():
    tmp_data_dir = tempfile.mkdtemp(prefix="qual_updater_test_")
    os.environ["DATA_DIR"] = tmp_data_dir
    print(f"Using throwaway DATA_DIR: {tmp_data_dir}\n")

    _check_dependency_status()
    print()

    try:
        _seed_data(tmp_data_dir)
        print("Seeded profile/scores/jobs/tracker_statuses/applications for test user.\n")

        from qualifications.updater import update_qualifications_prompt, get_latest_qualifications

        print("--- Calling update_qualifications_prompt (run #1, real Gemini call) ---")
        record1 = update_qualifications_prompt(USER_ID)
        print("\nResulting QualificationsProfile (version 1):")
        print(f"  qualifications_id: {record1['qualifications_id']}")
        print(f"  version: {record1['version']}")
        print(f"  based_on: {record1['based_on']}")
        print(f"  prompt_text:\n{record1['prompt_text']}\n")

        for field in ("qualifications_id", "user_id", "version", "prompt_text", "based_on", "generated_at"):
            assert field in record1, f"missing field: {field}"
        assert record1["version"] == 1
        assert record1["user_id"] == USER_ID
        assert record1["based_on"]["rejections_considered"] == 2
        assert record1["based_on"]["applications_considered"] == 2
        assert record1["prompt_text"], "prompt_text should not be empty (check GEMINI_API_KEY)"

        lowered = record1["prompt_text"].lower()
        signal_hits = []
        if "travel" in lowered:
            signal_hits.append("travel")
        if any(s in lowered for s in ("kubernetes", "go", "kafka", "rust", "tech stack", "stack")):
            signal_hits.append("missing-skills/stack")
        print(f"Seeded-signal mentions found in prompt_text: {signal_hits}")
        assert signal_hits, (
            "prompt_text did not mention travel preference or stack/skill-gap signal -- "
            "looks like it may just be restating the raw profile rather than synthesizing feedback"
        )

        latest_after_1 = get_latest_qualifications(USER_ID)
        assert latest_after_1["qualifications_id"] == record1["qualifications_id"]
        print("\nget_latest_qualifications correctly returns the version-1 record after run #1.")

        print("\n--- Calling update_qualifications_prompt (run #2, real Gemini call) ---")
        record2 = update_qualifications_prompt(USER_ID)
        print(f"\nResulting QualificationsProfile (version {record2['version']}):")
        print(f"  qualifications_id: {record2['qualifications_id']}")
        print(f"  prompt_text:\n{record2['prompt_text']}\n")

        assert record2["version"] == 2, f"expected version 2, got {record2['version']}"
        assert record2["qualifications_id"] != record1["qualifications_id"]

        from storage import json_store as js
        history = js.load_all(USER_ID, "qualifications")
        assert len(history) == 2, f"expected 2 records retained in history, found {len(history)}"
        versions = sorted(r["version"] for r in history)
        assert versions == [1, 2], f"expected versions [1, 2] retained, found {versions}"
        print(f"qualifications.json history now has {len(history)} records (versions {versions}) -- append, not overwrite, confirmed.")

        latest_after_2 = get_latest_qualifications(USER_ID)
        assert latest_after_2["qualifications_id"] == record2["qualifications_id"]
        assert latest_after_2["version"] == 2
        print("get_latest_qualifications correctly returns the version-2 (newer) record after run #2.")

        print("\nAll checks passed.")
    finally:
        shutil.rmtree(tmp_data_dir, ignore_errors=True)
        os.environ.pop("DATA_DIR", None)
        print(f"\nCleaned up throwaway DATA_DIR: {tmp_data_dir}")


if __name__ == "__main__":
    main()
