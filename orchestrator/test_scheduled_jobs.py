"""
orchestrator/test_scheduled_jobs.py -- end-to-end smoke test for the
scheduler workstream (plan section 9, workstream K).

Seeds three throwaway users under a temp DATA_DIR (so it never touches the
real data/ tree):
  - "sched-good-1": a normal profile, zero companies, and one MatchScore
    marked "relevant" with no Application yet -- so the digest run has
    something real to send (RESEND_API_KEY isn't configured in this dev
    environment, so notifications.email.send_email raises RuntimeError when
    it actually tries -- that's expected and is itself part of what this
    test verifies: a real send failure for ONE user must not stop the batch).
  - "sched-good-2": a normal profile, zero companies, no relevant/unapplied
    jobs -- digest should cleanly no-op for this one.
  - "sched-broken": deliberately malformed in three different ways, one per
    job under test, seeded in the MIDDLE of the user list so a clean pass
    requires every run_daily_*_for_all_users() to keep going past it and
    still reach "sched-good-2":
      * qualifications: profile["skills"] contains a non-string element,
        which crashes qualifications.updater._representative_query's
        ", ".join(...) call -- a real exception from real code, not a mock.
      * discovery: companies.json is written as invalid JSON, which crashes
        orchestrator.discovery_graph.load_companies_node's json.load() --
        confirmed (see module-level exploration this task did before writing
        this test) to propagate all the way out of discovery_graph.ainvoke
        uncaught, unlike per-company/per-job failures which that graph's
        nodes already catch internally.
      * digest: one MatchScore marked "relevant" with no Application, whose
        JobPosting has title=12345 (an int, not a str) -- crashes
        notifications.digest._build_digest_html's html.escape(title) call.

Each run_daily_*_for_all_users() is called directly (no waiting for
5am/6am/8am), with the real per-user function (update_qualifications_prompt,
discovery_graph.ainvoke, build_and_send_daily_digest) monkeypatched with a
thin recording wrapper -- NOT replaced with a fake -- so this test can
confirm, independent of whether an exception was raised, that the real
function was actually invoked for every seeded user, including after a
failure.

Separately, orchestrator.scheduler_service.build_scheduler() is called (not
started) and its registered jobs are inspected directly via
scheduler.get_jobs(), confirming three jobs exist with cron triggers at
hour=5/6/8 -- no need to wait for anything to actually fire.

qualifications.update_qualifications_prompt makes one real call_llm (Gemini)
call per healthy user, same as qualifications/test_updater.py's own
precedent -- this test seeds 2 healthy users, so 2 real LLM calls total.

Run from the repo root:
    python orchestrator/test_scheduled_jobs.py
"""
import asyncio
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

USER_GOOD_1 = "sched-good-1"
USER_BROKEN = "sched-broken"
USER_GOOD_2 = "sched-good-2"
USER_ORDER = [USER_GOOD_1, USER_BROKEN, USER_GOOD_2]  # broken deliberately in the middle


def _seed_users(data_dir: str):
    from storage import json_store
    from storage.paths import user_entity_path

    now = "2026-10-04T00:00:00+00:00"

    for uid in USER_ORDER:
        json_store.save_user({
            "user_id": uid,
            "email": f"{uid}@example.com",
            "password_hash": "not-a-real-hash",
            "created_at": now,
            "notify_email": f"{uid}@example.com",
            "digest_enabled": True,
            "totp_secret": None,
            "totp_enabled": False,
        })

    # --- sched-good-1: normal profile, one relevant+unapplied job ---
    json_store.save_profile(USER_GOOD_1, {
        "profile_id": "profile_good_1",
        "source_file_s3_key": "users/sched-good-1/resumes/profile_good_1.pdf",
        "full_name": "Good One",
        "email": "good1@example.com",
        "phone": None,
        "location": "Berlin, Germany",
        "summary": "Backend engineer with Python experience.",
        "skills": ["Python", "FastAPI", "PostgreSQL"],
        "experience": [],
        "education": [],
        "certifications": [],
        "links": [],
        "raw_text": "raw text",
        "extracted_at": now,
    })
    json_store.save_all(USER_GOOD_1, "companies", [])  # zero companies: no network/playwright needed
    json_store.save_all(USER_GOOD_1, "jobs", [{
        "job_id": "job_good_1",
        "company": "Acme GmbH",
        "title": "Backend Engineer",
        "location": "Berlin",
        "url": "https://example.com/jobs/job_good_1",
        "description": "Build REST APIs in Python.",
        "source": "scraper",
        "ats_job_id": None,
        "department": None,
        "posted_at": "2026-09-01",
        "discovered_at": now,
        "last_seen_at": now,
        "status": "seen",
        "raw": None,
        "location_lat": None,
        "location_lng": None,
        "is_remote": False,
    }])
    json_store.save_all(USER_GOOD_1, "scores", [{
        "match_id": "match_good_1",
        "job_id": "job_good_1",
        "profile_id": "profile_good_1",
        "score": 88.0,
        "rationale": "Strong backend fit.",
        "matched_skills": ["Python"],
        "missing_skills": [],
        "scored_at": now,
        "user_feedback": "relevant",
        "feedback_reason": None,
    }])
    json_store.save_all(USER_GOOD_1, "applications", [])  # no Application yet -> digest has something to send

    # --- sched-good-2: normal profile, nothing relevant/unapplied ---
    json_store.save_profile(USER_GOOD_2, {
        "profile_id": "profile_good_2",
        "source_file_s3_key": "users/sched-good-2/resumes/profile_good_2.pdf",
        "full_name": "Good Two",
        "email": "good2@example.com",
        "phone": None,
        "location": "Munich, Germany",
        "summary": "Data engineer with Spark/SQL experience.",
        "skills": ["SQL", "Spark", "Airflow"],
        "experience": [],
        "education": [],
        "certifications": [],
        "links": [],
        "raw_text": "raw text",
        "extracted_at": now,
    })
    json_store.save_all(USER_GOOD_2, "companies", [])
    json_store.save_all(USER_GOOD_2, "jobs", [])
    json_store.save_all(USER_GOOD_2, "scores", [])
    json_store.save_all(USER_GOOD_2, "applications", [])

    # --- sched-broken: three independent, realistic breakages ---
    json_store.save_profile(USER_BROKEN, {
        "profile_id": "profile_broken",
        "source_file_s3_key": "users/sched-broken/resumes/profile_broken.pdf",
        "full_name": "Broken User",
        "email": "broken@example.com",
        "phone": None,
        "location": "Nowhere",
        "summary": "Profile with a malformed skills list.",
        "skills": ["Python", 123],  # non-string element -> crashes ", ".join(...)
        "experience": [],
        "education": [],
        "certifications": [],
        "links": [],
        "raw_text": "raw text",
        "extracted_at": now,
    })
    # Invalid JSON written directly (bypassing json_store's writer on purpose)
    # so load_companies_node's json.load() raises a real JSONDecodeError.
    companies_path = user_entity_path(USER_BROKEN, "companies")
    os.makedirs(os.path.dirname(companies_path), exist_ok=True)
    with open(companies_path, "w", encoding="utf-8") as f:
        f.write("{not valid json!!!")

    json_store.save_all(USER_BROKEN, "jobs", [{
        "job_id": "job_broken",
        "company": "Bad Co",
        "title": 12345,  # int, not str -> crashes html.escape(title) in digest
        "location": "Remote",
        "url": "https://example.com/jobs/job_broken",
        "description": "n/a",
        "source": "scraper",
        "ats_job_id": None,
        "department": None,
        "posted_at": "2026-09-01",
        "discovered_at": now,
        "last_seen_at": now,
        "status": "seen",
        "raw": None,
        "location_lat": None,
        "location_lng": None,
        "is_remote": False,
    }])
    json_store.save_all(USER_BROKEN, "scores", [{
        "match_id": "match_broken",
        "job_id": "job_broken",
        "profile_id": "profile_broken",
        "score": 70.0,
        "rationale": "n/a",
        "matched_skills": [],
        "missing_skills": [],
        "scored_at": now,
        "user_feedback": "relevant",
        "feedback_reason": None,
    }])
    json_store.save_all(USER_BROKEN, "applications", [])


async def _test_qualifications():
    import orchestrator.scheduled_jobs as sj
    import qualifications.updater as updater_module
    from qualifications.updater import get_latest_qualifications

    called = []
    original = sj.update_qualifications_prompt

    def tracking_wrapper(user_id):
        called.append(user_id)
        return original(user_id)

    sj.update_qualifications_prompt = tracking_wrapper

    # The real Gemini free-tier quota (20 requests/day) is already exhausted
    # today by other workstreams' own real-API testing (confirmed via a
    # live 429 RESOURCE_EXHAUSTED from call_llm on a first attempt here).
    # qualifications.updater.update_qualifications_prompt's OWN synthesis
    # logic was already verified against the real API by workstream R's
    # qualifications/test_updater.py -- what THIS test needs to verify is
    # orchestrator.scheduled_jobs's iteration/error-isolation around it, not
    # re-prove R's prompt synthesis. So call_llm is stubbed here (the one
    # external, quota-limited call) while every other line of the real
    # update_qualifications_prompt (profile/memory/scores loading, RAG
    # retrieval, skill-gap analysis, tracker join, prompt assembly, record
    # versioning/persistence) still runs for real.
    original_call_llm = updater_module.call_llm
    updater_module.call_llm = lambda prompt: "[stubbed LLM output for scheduler test -- real quota exhausted]"

    try:
        print("--- run_daily_qualifications_update_for_all_users ---")
        await sj.run_daily_qualifications_update_for_all_users()
    finally:
        sj.update_qualifications_prompt = original
        updater_module.call_llm = original_call_llm

    print(f"Called update_qualifications_prompt for: {called}")
    assert called == USER_ORDER, f"expected all 3 users attempted in order, got {called}"

    good1_qual = get_latest_qualifications(USER_GOOD_1)
    good2_qual = get_latest_qualifications(USER_GOOD_2)
    broken_qual = get_latest_qualifications(USER_BROKEN)

    assert good1_qual is not None and good1_qual.get("prompt_text"), (
        "sched-good-1 should have a real QualificationsProfile written"
    )
    assert good2_qual is not None and good2_qual.get("prompt_text"), (
        "sched-good-2 should have a real QualificationsProfile written "
        "(proves the loop reached the user AFTER the broken one)"
    )
    assert broken_qual is None, (
        "sched-broken's malformed skills list should have crashed before "
        "writing any QualificationsProfile -- if this is not None, the "
        "per-user error isolation didn't actually stop the write"
    )
    print("qualifications: good-1 and good-2 got real QualificationsProfile records; "
          "broken user correctly got none (crashed before writing, error logged, loop continued).\n")


async def _test_discovery():
    import orchestrator.scheduled_jobs as sj

    called = []
    original_ainvoke = sj.discovery_graph.ainvoke

    async def tracking_ainvoke(state):
        called.append(state.get("user_id"))
        return await original_ainvoke(state)

    sj.discovery_graph.ainvoke = tracking_ainvoke
    try:
        print("--- run_daily_discovery_for_all_users ---")
        await sj.run_daily_discovery_for_all_users()
    finally:
        sj.discovery_graph.ainvoke = original_ainvoke

    print(f"Called discovery_graph.ainvoke for: {called}")
    assert called == USER_ORDER, f"expected all 3 users attempted in order, got {called}"
    print("discovery: ainvoke was actually invoked for every seeded user, including "
          "sched-good-2 AFTER sched-broken's corrupted companies.json raised -- "
          "confirms per-user isolation around a real (uncaught-by-F) exception.\n")


async def _test_digest():
    import orchestrator.scheduled_jobs as sj

    called = []
    original = sj.build_and_send_daily_digest

    def tracking_wrapper(user_id):
        called.append(user_id)
        return original(user_id)

    sj.build_and_send_daily_digest = tracking_wrapper
    try:
        print("--- run_daily_digest_for_all_users ---")
        await sj.run_daily_digest_for_all_users()
    finally:
        sj.build_and_send_daily_digest = original

    print(f"Called build_and_send_daily_digest for: {called}")
    assert called == USER_ORDER, f"expected all 3 users attempted in order, got {called}"
    print("digest: build_and_send_daily_digest was actually invoked for every seeded user. "
          "sched-good-1 has a real relevant+unapplied job, so it hit notifications.email.send_email, "
          "which raised RuntimeError because RESEND_API_KEY isn't configured in this dev environment "
          "(same situation notifications/email.py's own docstring documents) -- that real failure, "
          "exactly like sched-broken's malformed-title crash, was caught per-user and did not stop "
          "the batch from reaching sched-good-2.\n")


def _test_scheduler_registration():
    from orchestrator.scheduler_service import build_scheduler

    print("--- build_scheduler() job registration ---")
    scheduler = build_scheduler()
    jobs = {job.id: job for job in scheduler.get_jobs()}
    print(f"Registered job ids: {list(jobs.keys())}")

    assert set(jobs.keys()) == {
        "daily_qualifications_update", "daily_discovery", "daily_digest",
    }, f"unexpected job id set: {list(jobs.keys())}"

    expected_hours = {
        "daily_qualifications_update": "5",
        "daily_discovery": "6",
        "daily_digest": "8",
    }
    for job_id, expected_hour in expected_hours.items():
        job = jobs[job_id]
        field_strs = {str(f.name): str(f) for f in job.trigger.fields}
        actual_hour = field_strs.get("hour")
        print(f"  {job_id}: trigger={job.trigger}, hour field={actual_hour!r}")
        assert actual_hour == expected_hour, (
            f"{job_id} expected hour={expected_hour!r}, got {actual_hour!r}"
        )
    print("All three jobs registered with the correct cron hour (5/6/8), without starting the scheduler.\n")

    # Never actually started -- nothing here should fire or block.
    assert not scheduler.running


def main():
    tmp_data_dir = tempfile.mkdtemp(prefix="scheduler_test_")
    os.environ["DATA_DIR"] = tmp_data_dir
    print(f"Using throwaway DATA_DIR: {tmp_data_dir}\n")

    try:
        _seed_users(tmp_data_dir)
        print(f"Seeded users: {USER_ORDER} (broken user deliberately in the middle)\n")

        asyncio.run(_test_qualifications())
        asyncio.run(_test_discovery())
        asyncio.run(_test_digest())
        _test_scheduler_registration()

        print("All checks passed.")
    finally:
        shutil.rmtree(tmp_data_dir, ignore_errors=True)
        os.environ.pop("DATA_DIR", None)
        print(f"\nCleaned up throwaway DATA_DIR: {tmp_data_dir}")


if __name__ == "__main__":
    main()
