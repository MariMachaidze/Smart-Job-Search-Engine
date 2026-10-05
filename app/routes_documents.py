"""
Documents routes (workstream M, plan section 13).

  GET /documents                 -> GeneratedDocument records for this user
  GET /documents/{id}/download   -> presigned S3 download URL

Backs the Profile page's "Resumes & Cover Letters" history tab (plan
section 14): `display_name` is already a meaningful, job-relative filename
(set at generation time by resume.tailor/resume.cover_letter), so the
frontend can render a readable list straight off GET /documents without
any extra joining.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user
from storage import json_store, s3_client

router = APIRouter(prefix="/documents", tags=["documents"])

_DOCUMENTS_ENTITY = "documents"


@router.get("")
async def list_documents(current_user: dict = Depends(get_current_user)):
    return json_store.load_all(current_user["user_id"], _DOCUMENTS_ENTITY)


@router.get("/{document_id}/download")
async def download_document(document_id: str, current_user: dict = Depends(get_current_user)):
    """Returns a time-limited presigned S3 GET URL for the document, rather
    than streaming the file through this API -- the frontend's download
    button follows the URL directly (storage.s3_client.get_presigned_url,
    workstream A)."""
    user_id = current_user["user_id"]
    document = json_store.get_by_id(user_id, _DOCUMENTS_ENTITY, "document_id", document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    url = s3_client.get_presigned_url(document["s3_key"])
    return {"url": url, "display_name": document.get("display_name"), "document_id": document_id}
