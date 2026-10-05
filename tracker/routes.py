"""
Application tracker routes (workstream I, plan section 13).

Self-contained FastAPI `APIRouter` -- the integration point for
`app/main.py` is a single `app.include_router(tracker.routes.router)`
(a different workstream owns that wiring). Every route is protected with
`Depends(get_current_user)` from `app.auth`, resolving `user_id` from the
JWT and enforcing per-user data isolation the same way every other router
in the system does.

Route table (plan section 13):
  GET/POST/PATCH/DELETE /tracker/statuses
  GET/POST/PATCH        /tracker/applications

There is deliberately no DELETE /tracker/applications/* route: applications
are never deleted, only moved to another status (see tracker/service.py).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from pydantic import BaseModel

from app.auth import get_current_user
from tracker import service

router = APIRouter(prefix="/tracker", tags=["tracker"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class CreateStatusRequest(BaseModel):
    label: str
    color: str


class UpdateStatusRequest(BaseModel):
    label: Optional[str] = None
    color: Optional[str] = None
    order: Optional[int] = None


class CreateApplicationRequest(BaseModel):
    job_id: str
    status_label: str
    date_applied: Optional[str] = None
    referred_by: Optional[str] = ""
    comments: str = ""


class UpdateApplicationStatusRequest(BaseModel):
    status_label: str


# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------

@router.get("/statuses")
async def get_statuses(current_user: dict = Depends(get_current_user)):
    return service.list_statuses(current_user["user_id"])


@router.post("/statuses")
async def post_status(body: CreateStatusRequest, current_user: dict = Depends(get_current_user)):
    return service.create_status(current_user["user_id"], body.label, body.color)


@router.patch("/statuses/{status_id}")
async def patch_status(
    status_id: str,
    body: UpdateStatusRequest,
    current_user: dict = Depends(get_current_user),
):
    fields = body.model_dump(exclude_unset=True)
    try:
        return service.update_status(current_user["user_id"], status_id, **fields)
    except service.StatusNotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/statuses/{status_id}")
async def delete_status(status_id: str, current_user: dict = Depends(get_current_user)):
    try:
        service.delete_status(current_user["user_id"], status_id)
    except service.StatusNotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc))
    except service.StatusInUseError as exc:
        raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail=str(exc))
    return {"deleted": status_id}


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@router.get("/applications")
async def get_applications(current_user: dict = Depends(get_current_user)):
    return service.list_applications(current_user["user_id"])


@router.post("/applications")
async def post_application(body: CreateApplicationRequest, current_user: dict = Depends(get_current_user)):
    try:
        return service.create_application(
            current_user["user_id"],
            job_id=body.job_id,
            status_label=body.status_label,
            date_applied=body.date_applied,
            referred_by=body.referred_by,
            comments=body.comments,
        )
    except service.StatusLabelNotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.patch("/applications/{application_id}")
async def patch_application(
    application_id: str,
    body: UpdateApplicationStatusRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        return service.update_application_status(
            current_user["user_id"], application_id, body.status_label
        )
    except service.ApplicationNotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc))
    except service.StatusLabelNotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))
