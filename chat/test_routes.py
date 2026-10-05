"""
chat/test_routes.py -- end-to-end route-wiring test for chat/routes.py
(workstream H, plan section 13).

Builds a throwaway FastAPI app (mirrors app/main.py's own
`app.include_router(...)` pattern, without touching app/main.py itself --
a different workstream, M, owns deciding when to mount chat.routes.router
for real) and drives it with FastAPI's TestClient, under a throwaway
DATA_DIR, with a real signed-up user (real app.auth.router: real password
hashing + real JWT).

The only things faked: the Gemini client chat_graph.run_chat_turn would
otherwise construct (monkeypatched at orchestrator.chat_graph._get_client)
and app.llm.call_llm (auto-titling) -- per the standing "no live Gemini
calls right now" instruction. Everything else (auth, routing, session
persistence, SSE formatting) is real.

Run from the repo root:
    python chat/test_routes.py
"""
import json
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _text_response(text):
    from google.genai import types
    content = types.Content(role="model", parts=[types.Part.from_text(text=text)])
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


class _FakeModels:
    def __init__(self, responses):
        self._responses = list(responses)

    def generate_content(self, model, contents, config):
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.models = _FakeModels(responses)


def _parse_sse(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def main():
    tmp_data_dir = tempfile.mkdtemp(prefix="chat_routes_test_")
    os.environ["DATA_DIR"] = tmp_data_dir
    os.environ.setdefault("JWT_SECRET", "test-secret-for-chat-routes")
    print(f"Using throwaway DATA_DIR: {tmp_data_dir}\n")

    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.auth import router as auth_router
        from chat.routes import router as chat_router
        import orchestrator.chat_graph as chat_graph_module

        app = FastAPI()
        app.include_router(auth_router)
        app.include_router(chat_router)
        client = TestClient(app)

        # Always fake the Gemini client this route path will construct --
        # never a real API call, per the standing hold.
        chat_graph_module._get_client = lambda: _FakeClient([_text_response("Hello from the fake model!")])
        import orchestrator.chat_sessions as chat_sessions_module
        chat_sessions_module._default_call_llm = lambda prompt: "Fake Auto Generated Title"

        print("--- signup (real auth) ---")
        signup_resp = client.post("/auth/signup", json={"email": "chat-routes-test@example.com", "password": "supersecret123"})
        assert signup_resp.status_code == 200, signup_resp.text
        token = signup_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("OK\n")

        print("--- unauthenticated request is rejected ---")
        unauth_resp = client.get("/chat/sessions")
        assert unauth_resp.status_code in (401, 403), unauth_resp.status_code
        print("OK\n")

        print("--- POST /chat/sessions ---")
        create_resp = client.post("/chat/sessions", json={"title": "My first chat"}, headers=headers)
        assert create_resp.status_code == 200, create_resp.text
        session = create_resp.json()
        session_id = session["session_id"]
        assert session["title"] == "My first chat"
        assert session["messages"] == []
        print("OK\n")

        print("--- GET /chat/sessions (list) ---")
        list_resp = client.get("/chat/sessions", headers=headers)
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1
        print("OK\n")

        print("--- GET /chat/sessions/{id} ---")
        get_resp = client.get(f"/chat/sessions/{session_id}", headers=headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["session_id"] == session_id
        print("OK\n")

        print("--- GET /chat/sessions/{id} (not found) ---")
        missing_resp = client.get("/chat/sessions/does-not-exist", headers=headers)
        assert missing_resp.status_code == 404
        print("OK\n")

        print("--- POST /chat/sessions/{id}/message (SSE stream) ---")
        msg_resp = client.post(
            f"/chat/sessions/{session_id}/message",
            json={"message": "hi there, find me some jobs"},
            headers=headers,
        )
        assert msg_resp.status_code == 200
        assert msg_resp.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(msg_resp.text)
        event_types = [e["type"] for e in events]
        assert event_types == ["text", "done", "title"], event_types
        assert events[-1]["title"] == "Fake Auto Generated Title"
        print(f"  SSE events: {event_types}")
        print("OK\n")

        print("--- session now has persisted messages + generated title ---")
        get_resp2 = client.get(f"/chat/sessions/{session_id}", headers=headers)
        updated_session = get_resp2.json()
        assert len(updated_session["messages"]) == 2
        assert updated_session["title"] == "Fake Auto Generated Title"
        print("OK\n")

        print("--- DELETE /chat/sessions/{id} ---")
        delete_resp = client.delete(f"/chat/sessions/{session_id}", headers=headers)
        assert delete_resp.status_code == 200
        assert client.get(f"/chat/sessions/{session_id}", headers=headers).status_code == 404
        print("OK\n")

        print("--- POST /chat/sessions/{id}/message against deleted session -> 404 ---")
        gone_resp = client.post(
            f"/chat/sessions/{session_id}/message",
            json={"message": "hello?"},
            headers=headers,
        )
        assert gone_resp.status_code == 404
        print("OK\n")

        print("ALL CHECKS PASSED.")
    finally:
        shutil.rmtree(tmp_data_dir, ignore_errors=True)
        os.environ.pop("DATA_DIR", None)
        print(f"\nCleaned up throwaway DATA_DIR: {tmp_data_dir}")


if __name__ == "__main__":
    main()
