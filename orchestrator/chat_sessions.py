"""
orchestrator/chat_sessions.py -- chat session persistence, auto-titling, and
short-term history compression (plan section 12, workstream H).

Owns the `chat_sessions` entity (storage.schemas.ChatSession/ChatMessage) via
storage.json_store. The one real piece of logic beyond plain CRUD:

  - `send_message` drives one turn through orchestrator.chat_graph.run_chat_turn,
    persists the user/assistant messages, and -- on a session's FIRST
    exchange -- fires one extra `app.llm.call_llm` call to auto-title the
    session (plan: 'fire one extra call_llm("Generate a concise 4-6 word
    title...") call'). This is a plain text call, not native tool-calling,
    so it reuses the existing `call_llm` wrapper rather than chat_graph's
    Gemini client.
  - `_maybe_compress_history` implements the "short-term memory" rolling
    summary (plan section 12): once a session's message list exceeds
    `_SUMMARY_TRIGGER_MESSAGE_COUNT`, older turns are summarized into
    `ChatSession.summary` via one more call_llm call and dropped from the
    active `messages` list, so only the summary + the most recent messages
    are ever sent to Gemini on later turns.

Both of these LLM calls are `call_llm`, same standing-hold caveat as
chat_graph.py: implemented for real, exercised only against a mocked
`call_llm_fn` in orchestrator/test_chat_sessions.py.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator, Callable, Optional

from app.llm import call_llm as _default_call_llm
from storage import json_store

from orchestrator import chat_graph

_SESSIONS_ENTITY = "chat_sessions"

# Plan section 12: "once a session's message list grows past a token budget
# (e.g. ~30 messages)". We trigger on message COUNT (not a real token count)
# as a simple, deterministic proxy -- same spirit, cheaper to check.
_SUMMARY_TRIGGER_MESSAGE_COUNT = 30
_KEEP_RECENT_MESSAGES = 10


class SessionNotFoundError(Exception):
    """Raised when a session_id doesn't exist for this user."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Plain CRUD
# ---------------------------------------------------------------------------

def create_session(user_id: str, title: str = "New chat") -> dict:
    session = {
        "session_id": str(uuid.uuid4()),
        "user_id": user_id,
        "title": title,
        "messages": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "summary": None,
    }
    json_store.upsert(user_id, _SESSIONS_ENTITY, session, "session_id")
    return session


def list_sessions(user_id: str) -> list[dict]:
    """Most-recently-updated first, for a saved-sessions sidebar."""
    sessions = json_store.load_all(user_id, _SESSIONS_ENTITY)
    return sorted(sessions, key=lambda s: s.get("updated_at") or "", reverse=True)


def get_session(user_id: str, session_id: str) -> Optional[dict]:
    return json_store.get_by_id(user_id, _SESSIONS_ENTITY, "session_id", session_id)


def delete_session(user_id: str, session_id: str) -> None:
    sessions = json_store.load_all(user_id, _SESSIONS_ENTITY)
    remaining = [s for s in sessions if s.get("session_id") != session_id]
    json_store.save_all(user_id, _SESSIONS_ENTITY, remaining)


# ---------------------------------------------------------------------------
# Auto-titling (plan section 12)
# ---------------------------------------------------------------------------

def generate_session_title(
    user_message: str,
    assistant_reply: str,
    call_llm_fn: Optional[Callable[[str], str]] = None,
) -> str:
    """Fires the one extra call_llm call the plan describes, and cleans up
    common LLM formatting noise (surrounding quotes, a trailing period,
    markdown emphasis) since titles are rendered as plain sidebar labels."""
    call_llm_fn = call_llm_fn or _default_call_llm
    prompt = (
        "Generate a concise 4-6 word title for this conversation. Reply with "
        "ONLY the title -- no quotes, no markdown, no punctuation at the end.\n\n"
        f"User: {user_message}\nAssistant: {assistant_reply}"
    )
    raw = (call_llm_fn(prompt) or "").strip()
    cleaned = raw.strip("\"'* \n").rstrip(".")
    return cleaned or "New conversation"


# ---------------------------------------------------------------------------
# Short-term memory compression (plan section 12)
# ---------------------------------------------------------------------------

async def _maybe_compress_history(
    user_id: str,
    session: dict,
    call_llm_fn: Optional[Callable[[str], str]] = None,
) -> None:
    """Mutates `session` in place: if `messages` has grown past the
    trigger, summarizes everything except the most recent
    `_KEEP_RECENT_MESSAGES` into `session["summary"]` (folding in any prior
    summary, so compression is cumulative rather than lossy-per-step) and
    trims `messages` down to just those recent ones."""
    messages = session.get("messages") or []
    if len(messages) <= _SUMMARY_TRIGGER_MESSAGE_COUNT:
        return

    call_llm_fn = call_llm_fn or _default_call_llm
    to_summarize = messages[:-_KEEP_RECENT_MESSAGES]
    existing_summary = session.get("summary")

    transcript = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in to_summarize)
    prompt = (
        (f"Existing summary of the conversation so far:\n{existing_summary}\n\n" if existing_summary else "")
        + "Summarize the following older conversation turns concisely, preserving any "
          "concrete facts, preferences, job titles/companies, or decisions mentioned, so "
          "nothing load-bearing is lost once these turns are dropped from active context:\n\n"
        + transcript
    )
    summary = (await asyncio.to_thread(call_llm_fn, prompt) or "").strip()

    session["summary"] = summary or existing_summary
    session["messages"] = messages[-_KEEP_RECENT_MESSAGES:]


# ---------------------------------------------------------------------------
# send_message -- the main entry point chat/routes.py streams from
# ---------------------------------------------------------------------------

async def send_message(
    user_id: str,
    session_id: str,
    user_message: str,
    *,
    client=None,
    call_llm_fn: Optional[Callable[[str], str]] = None,
) -> AsyncIterator[dict]:
    """Appends the user's message, runs chat_graph.run_chat_turn (yielding
    its tool_call/tool_result/text/done events as-is for SSE streaming),
    appends the assistant's reply, persists the session, and -- on the
    session's first exchange only -- fires the auto-titling call and yields
    one extra `{"type": "title", "title": str}` event.

    Raises SessionNotFoundError if session_id doesn't belong to user_id.
    """
    session = get_session(user_id, session_id)
    if session is None:
        raise SessionNotFoundError(f"No chat session {session_id!r} for this user.")

    is_first_exchange = len(session.get("messages") or []) == 0

    session.setdefault("messages", [])
    session["messages"].append({"role": "user", "content": user_message, "timestamp": _now_iso()})

    await _maybe_compress_history(user_id, session, call_llm_fn=call_llm_fn)

    history = session["messages"][:-1]
    session_summary = session.get("summary")

    final_reply = ""
    async for event in chat_graph.run_chat_turn(
        user_id, history, user_message, session_summary=session_summary, client=client
    ):
        yield event
        if event.get("type") == "done":
            final_reply = event.get("reply", "")

    session["messages"].append({"role": "assistant", "content": final_reply, "timestamp": _now_iso()})
    session["updated_at"] = _now_iso()
    json_store.upsert(user_id, _SESSIONS_ENTITY, session, "session_id")

    if is_first_exchange and final_reply:
        title = await asyncio.to_thread(generate_session_title, user_message, final_reply, call_llm_fn)
        if title:
            session["title"] = title
            session["updated_at"] = _now_iso()
            json_store.upsert(user_id, _SESSIONS_ENTITY, session, "session_id")
            yield {"type": "title", "title": title}
