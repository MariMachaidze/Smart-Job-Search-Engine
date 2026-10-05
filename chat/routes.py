"""
Chat routes (workstream H, plan sections 11-13).

Self-contained FastAPI `APIRouter` -- the integration point for
`app/main.py` is `from chat.routes import router as chat_router` /
`app.include_router(chat_router)` (app/main.py already has this exact
import commented in as a placeholder; a different workstream, M, owns
actually uncommenting it). Every route is protected with
`Depends(get_current_user)` from `app.auth`, same as every other router.

Route table (plan sections 12/13):
  POST   /chat/sessions                  create a session
  GET    /chat/sessions                  list this user's sessions (sidebar)
  GET    /chat/sessions/{id}             get one session (with its messages)
  POST   /chat/sessions/{id}/message     send a message, SSE-streamed reply
  DELETE /chat/sessions/{id}             delete a session

POST .../message streams Server-Sent Events via FastAPI's StreamingResponse,
one `data: <json>\\n\\n` line per event yielded by
orchestrator.chat_sessions.send_message (tool_call / tool_result / text /
done / title -- see that module's docstring for the exact event shapes).
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth import get_current_user
from orchestrator import chat_sessions

router = APIRouter(prefix="/chat", tags=["chat"])


class CreateSessionRequest(BaseModel):
    title: Optional[str] = "New chat"


class SendMessageRequest(BaseModel):
    message: str


def _format_sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/sessions")
async def create_session(
    body: CreateSessionRequest = CreateSessionRequest(),
    current_user: dict = Depends(get_current_user),
):
    return chat_sessions.create_session(current_user["user_id"], title=body.title or "New chat")


@router.get("/sessions")
async def list_sessions(current_user: dict = Depends(get_current_user)):
    return chat_sessions.list_sessions(current_user["user_id"])


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, current_user: dict = Depends(get_current_user)):
    session = chat_sessions.get_session(current_user["user_id"], session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
    return session


@router.post("/sessions/{session_id}/message")
async def post_message(
    session_id: str,
    body: SendMessageRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    # Resolve existence up front (outside the generator) so a bad session_id
    # surfaces as a normal 404 rather than as an error buried inside an
    # already-started SSE stream.
    session = chat_sessions.get_session(user_id, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    async def event_stream():
        async for event in chat_sessions.send_message(user_id, session_id, body.message):
            yield _format_sse(event)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    if chat_sessions.get_session(user_id, session_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
    chat_sessions.delete_session(user_id, session_id)
    return {"deleted": session_id}
