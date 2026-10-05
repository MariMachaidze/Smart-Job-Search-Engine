"""
Profile routes (workstream M, plan section 13).

  POST /profile/upload   (multipart PDF) -> resume.parser.extract_profile_from_pdf
  GET  /profile                           -> the user's current CandidateProfile

Every route requires a valid JWT, resolved via `app.auth.get_current_user`,
enforcing the same per-user data isolation every other router in this system
uses.

`extract_profile_from_pdf` (workstream C) does real work synchronously
(pdfplumber extraction + a Gemini call + an S3 upload + json_store
persistence + RAG indexing) -- it's called directly rather than via
`asyncio.to_thread` since FastAPI's `async def` route just runs it on the
event loop; that's an acceptable tradeoff here (one upload at a time, not a
hot path) and keeps this route as a thin pass-through to the real pipeline,
consistent with how other workstreams' routers (e.g. tracker/routes.py)
delegate straight to their service module.
"""
import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.auth import get_current_user
from resume.parser import extract_profile_from_pdf
from storage import json_store

router = APIRouter(prefix="/profile", tags=["profile"])


@router.post("/upload")
async def upload_profile(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Accepts a multipart PDF upload, parses it into a CandidateProfile via
    the real resume-parsing pipeline, and returns the resulting profile.

    Raises 422 if the PDF has no usable text layer (resume/parser.py's
    OCR-out-of-scope ValueError) or if Gemini's extraction output couldn't
    be parsed as JSON even after a retry -- both are "this specific upload
    didn't work" cases, not server errors.
    """
    filename = (file.filename or "").lower()
    if not filename.endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted for resume upload.",
        )

    user_id = current_user["user_id"]
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(await file.read())

        try:
            profile = extract_profile_from_pdf(user_id, tmp_path)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return profile


@router.get("")
async def get_profile(current_user: dict = Depends(get_current_user)):
    """Returns the current user's CandidateProfile, or 404 if they haven't
    uploaded a resume yet."""
    profile = json_store.load_profile(current_user["user_id"])
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No profile uploaded yet. POST a resume PDF to /profile/upload first.",
        )
    return profile
