"""
orchestrator/test_chat_sessions.py -- smoke test for chat session
persistence, auto-titling, and short-term history compression (plan
section 12, workstream H).

Same convention as orchestrator/test_chat_graph.py: throwaway DATA_DIR,
real storage.json_store CRUD throughout. The two LLM seams this module
owns -- `call_llm` (auto-titling, history-compression summarization) and
the Gemini tool-calling client (via chat_graph.run_chat_turn) -- are ALWAYS
faked here, never real, per the standing "no live Gemini calls right now"
instruction. See orchestrator/chat_graph.py's module docstring for the
mock-construction notes (reused here via the same helpers).

Run from the repo root:
    python orchestrator/test_chat_sessions.py
"""
import asyncio
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

USER_ID = "chat-sessions-test-user-001"


def _text_response(text):
    from google.genai import types
    content = types.Content(role="model", parts=[types.Part.from_text(text=text)])
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


class _FakeModels:
    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0

    def generate_content(self, model, contents, config):
        self.call_count += 1
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.models = _FakeModels(responses)


def _collect(agen):
    async def _run():
        return [event async for event in agen]
    return asyncio.run(_run())


def test_session_crud():
    from orchestrator import chat_sessions

    print("--- session CRUD ---")
    session = chat_sessions.create_session(USER_ID, title="Untitled")
    session_id = session["session_id"]
    assert session["messages"] == []
    assert session["summary"] is None

    fetched = chat_sessions.get_session(USER_ID, session_id)
    assert fetched["session_id"] == session_id

    chat_sessions.create_session(USER_ID, title="Second session")
    sessions = chat_sessions.list_sessions(USER_ID)
    assert len(sessions) == 2

    chat_sessions.delete_session(USER_ID, session_id)
    assert chat_sessions.get_session(USER_ID, session_id) is None
    assert len(chat_sessions.list_sessions(USER_ID)) == 1
    print("OK\n")


def test_generate_session_title():
    from orchestrator import chat_sessions

    print("--- generate_session_title (call_llm faked) ---")
    fake_call_llm = lambda prompt: '"Resume Tailoring For Anthropic Role"'
    title = chat_sessions.generate_session_title("tailor my resume", "Done!", call_llm_fn=fake_call_llm)
    assert title == "Resume Tailoring For Anthropic Role", title

    empty_call_llm = lambda prompt: ""
    title = chat_sessions.generate_session_title("hi", "hello", call_llm_fn=empty_call_llm)
    assert title == "New conversation"
    print("OK\n")


def test_send_message_first_exchange_triggers_titling():
    from orchestrator import chat_sessions

    print("--- send_message: first exchange persists messages + auto-titles ---")
    session = chat_sessions.create_session(USER_ID, title="New chat")
    session_id = session["session_id"]

    client = _FakeClient([_text_response("I can help you search for jobs!")])
    title_calls = []

    def fake_call_llm(prompt):
        title_calls.append(prompt)
        return "Getting Started With Job Search"

    events = _collect(chat_sessions.send_message(USER_ID, session_id, "hi there", client=client, call_llm_fn=fake_call_llm))

    event_types = [e["type"] for e in events]
    assert event_types == ["text", "done", "title"], event_types
    assert events[-1]["title"] == "Getting Started With Job Search"
    assert len(title_calls) == 1, "auto-titling should fire exactly once, on the first exchange"

    persisted = chat_sessions.get_session(USER_ID, session_id)
    assert persisted["title"] == "Getting Started With Job Search"
    assert len(persisted["messages"]) == 2
    assert persisted["messages"][0] == {"role": "user", "content": "hi there", "timestamp": persisted["messages"][0]["timestamp"]}
    assert persisted["messages"][1]["role"] == "assistant"
    assert persisted["messages"][1]["content"] == "I can help you search for jobs!"
    print("OK\n")

    print("--- send_message: SECOND exchange does NOT re-fire auto-titling ---")
    client2 = _FakeClient([_text_response("Sure, here's more info.")])
    title_calls2 = []

    def fake_call_llm2(prompt):
        title_calls2.append(prompt)
        return "Should Not Be Used"

    events2 = _collect(chat_sessions.send_message(USER_ID, session_id, "tell me more", client=client2, call_llm_fn=fake_call_llm2))
    event_types2 = [e["type"] for e in events2]
    assert "title" not in event_types2, event_types2
    assert len(title_calls2) == 0

    persisted2 = chat_sessions.get_session(USER_ID, session_id)
    assert persisted2["title"] == "Getting Started With Job Search"  # unchanged
    assert len(persisted2["messages"]) == 4
    print("OK\n")


def test_session_not_found():
    from orchestrator import chat_sessions

    print("--- send_message against a nonexistent session_id raises ---")
    try:
        _collect(chat_sessions.send_message(USER_ID, "nonexistent-session", "hi"))
        assert False, "expected SessionNotFoundError"
    except chat_sessions.SessionNotFoundError:
        pass
    print("OK\n")


def test_history_compression():
    from orchestrator import chat_sessions
    from storage import json_store

    print("--- history compression (>_SUMMARY_TRIGGER_MESSAGE_COUNT messages -> summarized) ---")
    session = chat_sessions.create_session(USER_ID, title="Long chat")
    session_id = session["session_id"]

    # Seed 29 prior messages directly (below the trigger), then send one
    # more real message through send_message so the post-append count (30)
    # crosses chat_sessions._SUMMARY_TRIGGER_MESSAGE_COUNT (30 triggers
    # compression since the check is `> 30`... use 31 seeded so count=32 > 30).
    seeded_messages = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"message number {i}", "timestamp": "2026-01-01T00:00:00+00:00"}
        for i in range(31)
    ]
    session["messages"] = seeded_messages
    json_store.upsert(USER_ID, "chat_sessions", session, "session_id")

    summarize_calls = []

    def fake_call_llm(prompt):
        summarize_calls.append(prompt)
        return "Summary: user has been discussing their job search at length."

    client = _FakeClient([_text_response("Got it, continuing on.")])
    events = _collect(chat_sessions.send_message(USER_ID, session_id, "one more message", client=client, call_llm_fn=fake_call_llm))
    assert events[-1]["type"] in ("done", "title")

    persisted = chat_sessions.get_session(USER_ID, session_id)
    assert persisted["summary"] == "Summary: user has been discussing their job search at length."
    # 31 seeded + 1 new user message = 32 before compression; compression
    # keeps the last _KEEP_RECENT_MESSAGES of those 32 (which already
    # includes the just-appended user message), then the assistant reply
    # is appended after compression runs -> _KEEP_RECENT_MESSAGES + 1.
    assert len(persisted["messages"]) == chat_sessions._KEEP_RECENT_MESSAGES + 1, len(persisted["messages"])
    assert len(summarize_calls) == 1
    print("OK\n")


def main():
    tmp_data_dir = tempfile.mkdtemp(prefix="chat_sessions_test_")
    os.environ["DATA_DIR"] = tmp_data_dir
    print(f"Using throwaway DATA_DIR: {tmp_data_dir}\n")
    try:
        test_session_crud()
        test_generate_session_title()
        test_send_message_first_exchange_triggers_titling()
        test_session_not_found()
        test_history_compression()
        print("ALL CHECKS PASSED.")
    finally:
        shutil.rmtree(tmp_data_dir, ignore_errors=True)
        os.environ.pop("DATA_DIR", None)
        print(f"\nCleaned up throwaway DATA_DIR: {tmp_data_dir}")


if __name__ == "__main__":
    main()
