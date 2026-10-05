"""
orchestrator/test_chat_graph.py -- smoke test for Graph 3 (workstream H).

Follows this repo's established convention (orchestrator/test_graphs.py,
qualifications/test_updater.py): a throwaway test user under a temporary
DATA_DIR (never touches the real data/ tree), cleaned up at the end.

Two halves, per this workstream's explicit testing instructions:

1. TOOL FUNCTIONS (every one of the 21 tools in chat_graph.TOOL_HANDLERS) --
   tested LIVE against the REAL storage/tracker/stats/qualifications
   modules. The ONLY exception: wherever a tool's real implementation
   itself makes a `call_llm` call (tailor_resume_for_job,
   generate_cover_letter_for_job via tailoring_graph -> resume.tailor /
   resume.cover_letter; refresh_qualifications via
   qualifications.updater; analyze_rejection_patterns's threshold-met
   branch via stats.skill_gap), that ONE call_llm reference is monkeypatched
   with a deterministic fake for the duration of this test -- per the user's
   standing "no live Gemini API calls right now" instruction, which applies
   regardless of free-tier quota status. Real network geocoding (OSM
   Nominatim, via update_commute_preferences) is NOT mocked -- it isn't an
   LLM call, and this repo's own tests (orchestrator/test_graphs.py) already
   call it live.

2. THE GEMINI TOOL-CALLING LOOP (run_chat_turn) -- the actual
   `client.models.generate_content` call is ALWAYS mocked (never real,
   regardless of quota), via a FakeClient whose `.models.generate_content`
   returns real `google.genai.types.GenerateContentResponse` objects built
   the same way the SDK itself builds them (Candidate/Content/Part,
   constructed via `Part.from_text`/`Part.from_function_call` -- see this
   file's `_text_response`/`_function_call_response` helpers and
   orchestrator/chat_graph.py's module docstring for why this is considered
   structurally accurate rather than a hand-rolled dict). This exercises
   four scenarios: plain text reply (no tool calls), a single tool call
   then a text reply, a multi-tool-call turn, and the max-iteration guard
   actually triggering.

**Live verification against the real Gemini API has NOT been done** -- see
orchestrator/chat_graph.py's module docstring. Re-run against the real API
once the user's hold is lifted.

Run from the repo root:
    python orchestrator/test_chat_graph.py
"""
import asyncio
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

USER_ID = "chat-graph-test-user-001"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Deterministic call_llm fakes, patched in only at the exact seams other
# workstreams' modules hold their own `call_llm` reference (same pattern
# orchestrator/test_graphs.py uses for resume.tailor/resume.cover_letter).
# ---------------------------------------------------------------------------

def _patch_call_llm_seams():
    import resume.cover_letter as cover_letter_module
    import resume.tailor as tailor_module
    import qualifications.updater as qualifications_module
    import stats.skill_gap as skill_gap_module

    originals = {
        "tailor": tailor_module.call_llm,
        "cover_letter": cover_letter_module.call_llm,
        "qualifications": qualifications_module.call_llm,
        "skill_gap": skill_gap_module.call_llm,
    }

    tailor_module.call_llm = lambda prompt: (
        '{"summary": "Backend engineer.", "featured_skills": ["Python", "FastAPI"], '
        '"experience": [{"company": "Chat Test GmbH", "title": "Backend Engineer", '
        '"location": "Berlin, Germany", "start_date": "2022-01", "end_date": "Present", '
        '"bullets": ["Built REST APIs."]}]}'
    )
    cover_letter_module.call_llm = lambda prompt: (
        '{"paragraphs": ["I am excited to apply.", "I have relevant backend experience.", '
        '"I would welcome the opportunity."]}'
    )
    qualifications_module.call_llm = lambda prompt: (
        "Deterministic fake qualifications synthesis for test purposes."
    )
    skill_gap_module.call_llm = lambda prompt: (
        '{"missing_skills": ["Kubernetes"], "recommendation": "Study Kubernetes."}'
    )

    def _restore():
        tailor_module.call_llm = originals["tailor"]
        cover_letter_module.call_llm = originals["cover_letter"]
        qualifications_module.call_llm = originals["qualifications"]
        skill_gap_module.call_llm = originals["skill_gap"]

    return _restore


def _fake_s3_upload_file_if_unconfigured():
    if os.getenv("S3_BUCKET_NAME") and os.getenv("AWS_ACCESS_KEY_ID"):
        return
    import storage.s3_client as real_s3_client

    def fake_upload_file(local_path, key):
        return key

    real_s3_client.upload_file = fake_upload_file


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def _seed_profile():
    from storage import json_store

    profile = {
        "profile_id": "profile_chat_test_1",
        "source_file_s3_key": f"users/{USER_ID}/resumes/profile_chat_test_1.pdf",
        "full_name": "Chat Tester",
        "email": "chat.tester@example.com",
        "phone": None,
        "location": "Berlin, Germany",
        "summary": "Backend engineer.",
        "skills": ["Python", "FastAPI"],
        "experience": [],
        "education": [],
        "certifications": [],
        "links": [],
        "raw_text": "raw",
        "extracted_at": _now_iso(),
    }
    json_store.save_profile(USER_ID, profile)
    return profile


def _seed_jobs():
    from storage import json_store

    jobs = [
        {
            "job_id": "job_1", "company": "Acme", "title": "Backend Engineer",
            "location": "Berlin", "url": "https://example.com/1",
            "description": "Build APIs.", "source": "scraper", "ats_job_id": None,
            "department": None, "posted_at": None, "discovered_at": _now_iso(),
            "last_seen_at": _now_iso(), "status": "new", "raw": None,
            "location_lat": None, "location_lng": None, "is_remote": False,
        },
        {
            "job_id": "job_2", "company": "Beta Inc", "title": "ML Engineer",
            "location": "Remote", "url": "https://example.com/2",
            "description": "Train models.", "source": "scraper", "ats_job_id": None,
            "department": None, "posted_at": None, "discovered_at": _now_iso(),
            "last_seen_at": _now_iso(), "status": "new", "raw": None,
            "location_lat": None, "location_lng": None, "is_remote": True,
        },
    ]
    json_store.save_all(USER_ID, "jobs", jobs)

    scores = [{
        "match_id": "match_1", "job_id": "job_1", "profile_id": "profile_chat_test_1",
        "score": 72.0, "rationale": "Good fit.", "matched_skills": ["Python"],
        "missing_skills": [], "scored_at": _now_iso(),
        "user_feedback": None, "feedback_reason": None,
    }]
    json_store.save_all(USER_ID, "scores", scores)
    return jobs


def _seed_tracker_statuses():
    from storage import json_store
    from storage.default_statuses import DEFAULT_STATUSES

    statuses = [
        {"status_id": f"status_{i}", "user_id": USER_ID, "label": s["label"], "color": s["color"], "order": i}
        for i, s in enumerate(DEFAULT_STATUSES)
    ]
    json_store.save_all(USER_ID, "tracker_statuses", statuses)
    return statuses


# ---------------------------------------------------------------------------
# Tool function tests (live)
# ---------------------------------------------------------------------------

def test_tools_live():
    import orchestrator.chat_graph as cg
    from storage import json_store

    print("--- run_discovery (zero companies seeded -> cheap, no network) ---")
    json_store.save_all(USER_ID, "companies", [])
    result = asyncio.run(cg.execute_tool(USER_ID, "run_discovery", {}))
    assert result["new_jobs_count"] == 0
    assert result["errors"] == []
    print("OK\n")

    print("--- list_jobs / get_job ---")
    _seed_jobs()
    result = asyncio.run(cg.execute_tool(USER_ID, "list_jobs", {}))
    assert result["count"] == 2
    result = asyncio.run(cg.execute_tool(USER_ID, "list_jobs", {"filter": {"company": "Beta Inc"}}))
    assert result["count"] == 1 and result["jobs"][0]["job_id"] == "job_2"
    result = asyncio.run(cg.execute_tool(USER_ID, "get_job", {"job_id": "job_1"}))
    assert result["job"]["title"] == "Backend Engineer"
    assert result["score"]["score"] == 72.0
    try:
        asyncio.run(cg.execute_tool(USER_ID, "get_job", {"job_id": "nope"}))
        assert False, "expected ValueError for missing job"
    except ValueError:
        pass
    print("OK\n")

    print("--- rate_job (existing score + reason -> memory entry) ---")
    result = asyncio.run(cg.execute_tool(USER_ID, "rate_job", {
        "job_id": "job_1", "feedback": "not_relevant", "reason": "too much travel",
    }))
    assert result["match_score"]["user_feedback"] == "not_relevant"
    assert result["match_score"]["feedback_reason"] == "too much travel"
    assert result["memory_entry"] is not None
    memory = json_store.load_all(USER_ID, "memory")
    assert any(m["category"] == "feedback" and "too much travel" in m["content"] for m in memory)
    print("OK\n")

    print("--- rate_job (no existing score -> creates placeholder MatchScore) ---")
    result = asyncio.run(cg.execute_tool(USER_ID, "rate_job", {
        "job_id": "job_2", "feedback": "relevant",
    }))
    assert result["match_score"]["job_id"] == "job_2"
    assert result["match_score"]["score"] == 0.0
    assert result["memory_entry"] is None  # no reason given -> no memory write
    scores_on_disk = json_store.load_all(USER_ID, "scores")
    assert any(s["job_id"] == "job_2" for s in scores_on_disk)
    print("OK\n")

    print("--- get_profile ---")
    _seed_profile()
    result = asyncio.run(cg.execute_tool(USER_ID, "get_profile", {}))
    assert result["profile"]["full_name"] == "Chat Tester"
    print("OK\n")

    print("--- companies CRUD (list/add/remove) ---")
    result = asyncio.run(cg.execute_tool(USER_ID, "add_company", {"name": "Gamma Co", "url": "https://gamma.example.com/careers"}))
    company_id = result["company"]["company_id"]
    result = asyncio.run(cg.execute_tool(USER_ID, "list_companies", {}))
    assert any(c["company_id"] == company_id for c in result["companies"])
    result = asyncio.run(cg.execute_tool(USER_ID, "remove_company", {"company_id": company_id}))
    assert result["removed_company_id"] == company_id
    result = asyncio.run(cg.execute_tool(USER_ID, "list_companies", {}))
    assert not any(c["company_id"] == company_id for c in result["companies"])
    try:
        asyncio.run(cg.execute_tool(USER_ID, "remove_company", {"company_id": "nonexistent"}))
        assert False, "expected ValueError"
    except ValueError:
        pass
    print("OK\n")

    print("--- tracker: mark_applied / update_application_status / list_applications ---")
    _seed_tracker_statuses()
    result = asyncio.run(cg.execute_tool(USER_ID, "mark_applied", {
        "job_id": "job_1", "status_label": "Applied", "referred_by": "", "comments": "via chat",
    }))
    application_id = result["application"]["application_id"]
    assert result["application"]["status_history"][0]["changed_at"]
    result = asyncio.run(cg.execute_tool(USER_ID, "update_application_status", {
        "application_id": application_id, "status_label": "Interviewed",
    }))
    assert len(result["application"]["status_history"]) == 2
    result = asyncio.run(cg.execute_tool(USER_ID, "list_applications", {}))
    assert result["count"] == 1
    result = asyncio.run(cg.execute_tool(USER_ID, "list_applications", {"filter": {"status_label": "Interviewed"}}))
    assert result["count"] == 1
    result = asyncio.run(cg.execute_tool(USER_ID, "list_applications", {"filter": {"status_label": "Rejected"}}))
    assert result["count"] == 0
    try:
        asyncio.run(cg.execute_tool(USER_ID, "mark_applied", {"job_id": "job_1", "status_label": "Not A Real Status"}))
        assert False, "expected ValueError"
    except ValueError:
        pass
    print("OK\n")

    print("--- get_statistics ---")
    result = asyncio.run(cg.execute_tool(USER_ID, "get_statistics", {"granularity": "daily"}))
    assert result["summary"]["total_applications"] == 1
    assert isinstance(result["status_counts"], list)
    print("OK\n")

    print("--- analyze_rejection_patterns (not-enough-data branch, no LLM call) ---")
    result = asyncio.run(cg.execute_tool(USER_ID, "analyze_rejection_patterns", {}))
    assert result["threshold_met"] is False
    print("OK\n")

    print("--- save_memory / list_memory ---")
    result = asyncio.run(cg.execute_tool(USER_ID, "save_memory", {"content": "Prefers remote roles.", "category": "preference"}))
    assert result["memory_entry"]["category"] == "preference"
    result = asyncio.run(cg.execute_tool(USER_ID, "list_memory", {}))
    assert any(m["content"] == "Prefers remote roles." for m in result["memory"])
    try:
        asyncio.run(cg.execute_tool(USER_ID, "save_memory", {"content": "x", "category": "bogus"}))
        assert False, "expected ValueError"
    except ValueError:
        pass
    print("OK\n")

    print("--- search_past_documents (rag stub, expect empty) ---")
    result = asyncio.run(cg.execute_tool(USER_ID, "search_past_documents", {"query": "backend experience"}))
    assert result == {"chunks": [], "count": 0}
    print("OK\n")

    print("--- update_commute_preferences (REAL live Nominatim geocode -- not an LLM call) ---")
    result = asyncio.run(cg.execute_tool(USER_ID, "update_commute_preferences", {
        "home_location": "Berlin, Germany", "max_commute_km": 30.0,
        "remote_preference": "hybrid_ok", "willing_to_relocate": False,
    }))
    prefs = result["preferences"]
    assert prefs["home_location"] == "Berlin, Germany"
    assert prefs["home_lat"] is not None and prefs["home_lng"] is not None, "live geocode of Berlin should resolve"
    assert prefs["max_commute_km"] == 30.0
    assert prefs["remote_preference"] == "hybrid_ok"
    stored = json_store.load_all(USER_ID, "preferences")
    assert len(stored) == 1, "preferences should stay a single-record list"
    print("OK\n")

    print("--- unknown tool name ---")
    try:
        asyncio.run(cg.execute_tool(USER_ID, "not_a_real_tool", {}))
        assert False, "expected ValueError"
    except ValueError:
        pass
    print("OK\n")

    restore = _patch_call_llm_seams()
    try:
        print("--- tailor_resume_for_job / generate_cover_letter_for_job (real tailoring_graph, call_llm faked) ---")
        result = asyncio.run(cg.execute_tool(USER_ID, "tailor_resume_for_job", {"job_id": "job_1"}))
        doc = result["resume_document"]
        assert doc is not None, f"tailor_resume_for_job failed: {result['errors']}"
        assert doc["doc_type"] == "resume" and doc["job_id"] == "job_1"
        persisted = json_store.load_all(USER_ID, "documents")
        assert any(d["document_id"] == doc["document_id"] for d in persisted)

        result = asyncio.run(cg.execute_tool(USER_ID, "generate_cover_letter_for_job", {"job_id": "job_1"}))
        doc2 = result["cover_letter_document"]
        assert doc2 is not None, f"generate_cover_letter_for_job failed: {result['errors']}"
        assert doc2["doc_type"] == "cover_letter" and doc2["job_id"] == "job_1"
        print("OK\n")

        print("--- refresh_qualifications / get_qualifications (call_llm faked) ---")
        result = asyncio.run(cg.execute_tool(USER_ID, "refresh_qualifications", {}))
        assert result["qualifications"]["version"] == 1
        result = asyncio.run(cg.execute_tool(USER_ID, "get_qualifications", {}))
        assert result["qualifications"]["version"] == 1
        print("OK\n")

        print("--- analyze_rejection_patterns (threshold-met branch, call_llm faked) ---")
        # Push rejected_count past REJECTED_COUNT_THRESHOLD (5).
        statuses = json_store.load_all(USER_ID, "tracker_statuses")
        rejected_status_id = next(s["status_id"] for s in statuses if s["label"] == "Rejected")
        jobs = json_store.load_all(USER_ID, "jobs")
        extra_jobs = [{**jobs[0], "job_id": f"job_rej_{i}", "description": f"Needs Kubernetes skill #{i}."} for i in range(5)]
        json_store.save_all(USER_ID, "jobs", jobs + extra_jobs)
        applications = json_store.load_all(USER_ID, "applications")
        for i in range(5):
            applications.append({
                "application_id": f"app_rej_{i}", "user_id": USER_ID, "job_id": f"job_rej_{i}",
                "status_id": rejected_status_id,
                "status_history": [{"status_id": rejected_status_id, "changed_at": _now_iso()}],
                "date_applied": _now_iso(), "referred_by": "", "comments": "",
                "created_at": _now_iso(), "updated_at": _now_iso(),
            })
        json_store.save_all(USER_ID, "applications", applications)
        result = asyncio.run(cg.execute_tool(USER_ID, "analyze_rejection_patterns", {}))
        assert result["threshold_met"] is True
        assert "Kubernetes" in result["missing_skills"]
        print("OK\n")
    finally:
        restore()

    print("ALL LIVE TOOL TESTS PASSED.\n")


# ---------------------------------------------------------------------------
# Mocked Gemini loop tests
# ---------------------------------------------------------------------------

def _text_response(text):
    from google.genai import types
    content = types.Content(role="model", parts=[types.Part.from_text(text=text)])
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


def _function_call_response(calls):
    """`calls` is a list of (name, args) tuples -- one response can carry
    multiple function_call parts, matching how Gemini represents a
    multi-tool-call turn."""
    from google.genai import types
    parts = [types.Part.from_function_call(name=name, args=args) for name, args in calls]
    content = types.Content(role="model", parts=parts)
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


class _FakeModels:
    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0

    def generate_content(self, model, contents, config):
        self.call_count += 1
        if not self._responses:
            raise AssertionError("FakeModels.generate_content called more times than scripted")
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.models = _FakeModels(responses)


def _collect_events(agen):
    async def _run():
        return [event async for event in agen]
    return asyncio.run(_run())


def test_loop_no_tool_call():
    import orchestrator.chat_graph as cg
    print("--- run_chat_turn: plain text reply, no tool calls ---")
    client = _FakeClient([_text_response("Hello! How can I help with your job search?")])
    events = _collect_events(cg.run_chat_turn(USER_ID, [], "hi", client=client))
    assert events[-1]["type"] == "done"
    assert events[-1]["reply"] == "Hello! How can I help with your job search?"
    assert events[-1]["tool_calls"] == []
    assert events[-1]["max_iterations_hit"] is False
    assert client.models.call_count == 1
    print("OK\n")


def test_loop_single_tool_call():
    import orchestrator.chat_graph as cg
    print("--- run_chat_turn: one tool call, then a text reply ---")
    client = _FakeClient([
        _function_call_response([("get_profile", {})]),
        _text_response("Your profile shows you're a backend engineer skilled in Python/FastAPI."),
    ])
    events = _collect_events(cg.run_chat_turn(USER_ID, [], "what's in my profile?", client=client))
    types_seen = [e["type"] for e in events]
    assert types_seen == ["tool_call", "tool_result", "text", "done"], types_seen
    assert events[0]["name"] == "get_profile"
    assert "result" in events[1]["response"]
    assert events[1]["response"]["result"]["profile"]["full_name"] == "Chat Tester"
    assert events[-1]["reply"].startswith("Your profile shows")
    assert len(events[-1]["tool_calls"]) == 1
    assert client.models.call_count == 2
    print("OK\n")


def test_loop_multi_tool_call():
    import orchestrator.chat_graph as cg
    print("--- run_chat_turn: multiple tool calls in one turn ---")
    client = _FakeClient([
        _function_call_response([("get_profile", {}), ("list_companies", {})]),
        _text_response("Here's your profile and your tracked companies."),
    ])
    events = _collect_events(cg.run_chat_turn(USER_ID, [], "show me my profile and companies", client=client))
    tool_call_events = [e for e in events if e["type"] == "tool_call"]
    tool_result_events = [e for e in events if e["type"] == "tool_result"]
    assert len(tool_call_events) == 2
    assert len(tool_result_events) == 2
    assert {e["name"] for e in tool_call_events} == {"get_profile", "list_companies"}
    done = events[-1]
    assert done["type"] == "done"
    assert len(done["tool_calls"]) == 2
    assert client.models.call_count == 2
    print("OK\n")


def test_loop_tool_error_does_not_kill_turn():
    import orchestrator.chat_graph as cg
    print("--- run_chat_turn: a failing tool call surfaces as an error FunctionResponse, not a crash ---")
    client = _FakeClient([
        _function_call_response([("get_job", {"job_id": "does-not-exist"})]),
        _text_response("I couldn't find that job."),
    ])
    events = _collect_events(cg.run_chat_turn(USER_ID, [], "tell me about job does-not-exist", client=client))
    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert "error" in tool_result["response"]
    assert events[-1]["reply"] == "I couldn't find that job."
    print("OK\n")


def test_loop_max_iterations_guard():
    import orchestrator.chat_graph as cg
    print("--- run_chat_turn: max-iteration guard actually triggers ---")
    # Script MORE function-call responses than max_iterations, so if the
    # guard didn't work the loop would keep going past the cap.
    responses = [_function_call_response([("list_memory", {})]) for _ in range(5)]
    client = _FakeClient(responses)
    events = _collect_events(
        cg.run_chat_turn(USER_ID, [], "keep looping", client=client, max_iterations=3)
    )
    done = events[-1]
    assert done["type"] == "done"
    assert done["max_iterations_hit"] is True
    assert "loop" in done["reply"].lower() or "wrap this up" in done["reply"].lower()
    assert client.models.call_count == 3, f"expected exactly max_iterations=3 calls, got {client.models.call_count}"
    tool_call_events = [e for e in events if e["type"] == "tool_call"]
    assert len(tool_call_events) == 3
    print("OK\n")


def main():
    tmp_data_dir = tempfile.mkdtemp(prefix="chat_graph_test_")
    os.environ["DATA_DIR"] = tmp_data_dir
    print(f"Using throwaway DATA_DIR: {tmp_data_dir}\n")
    try:
        _fake_s3_upload_file_if_unconfigured()

        test_tools_live()
        test_loop_no_tool_call()
        test_loop_single_tool_call()
        test_loop_multi_tool_call()
        test_loop_tool_error_does_not_kill_turn()
        test_loop_max_iterations_guard()

        print("ALL CHECKS PASSED.")
    finally:
        shutil.rmtree(tmp_data_dir, ignore_errors=True)
        os.environ.pop("DATA_DIR", None)
        print(f"\nCleaned up throwaway DATA_DIR: {tmp_data_dir}")


if __name__ == "__main__":
    main()
