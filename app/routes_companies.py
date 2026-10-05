"""
Companies + preferences routes (workstream M, plan section 13).

  GET/POST/DELETE /companies    -> CRUD over storage.schemas.CompanySource,
                                     the source list discovery_graph's
                                     load_companies_node reads (workstream B/F)
  GET/PATCH       /preferences  -> storage.schemas.UserPreferences (plan
                                     section 3a's commute/remote hard filter)

`preferences` has no dedicated owning module (it wasn't assigned to any
single workstream in the plan's table -- workstream F's discovery_graph
reads it directly via json_store, per that module's own
`_load_preferences` docstring). This router follows the exact same
convention: `UserPreferences` is a single logical record per user, but
json_store only exposes list-based entity storage, so it's persisted as a
one-entry list via `json_store.load_all(user_id, "preferences")` /
`json_store.save_all(user_id, "preferences", [record])` -- the same pattern
`orchestrator/discovery_graph.py:_load_preferences` already uses to read it.

`home_lat`/`home_lng` are never accepted directly from the client -- they're
always derived server-side by geocoding `home_location` via
`geocoding.client.geocode` (OSM Nominatim) whenever it's set or changed on
PATCH /preferences, per plan section 3a ("UserPreferences is geocoded once
... when the user sets home_location").
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import get_current_user
from geocoding.client import geocode
from storage import json_store

router = APIRouter(tags=["companies"])

_COMPANIES_ENTITY = "companies"
_PREFERENCES_ENTITY = "preferences"

_VALID_REMOTE_PREFERENCES = {"remote_only", "hybrid_ok", "onsite_ok", "no_preference"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

class CreateCompanyRequest(BaseModel):
    company: str
    careers_url: str


@router.get("/companies")
async def list_companies(current_user: dict = Depends(get_current_user)):
    return json_store.load_all(current_user["user_id"], _COMPANIES_ENTITY)


@router.post("/companies")
async def create_company(
    body: CreateCompanyRequest,
    current_user: dict = Depends(get_current_user),
):
    record = {
        "company_id": str(uuid.uuid4()),
        "user_id": current_user["user_id"],
        "company": body.company,
        "careers_url": body.careers_url,
        "added_at": _now_iso(),
    }
    json_store.upsert(current_user["user_id"], _COMPANIES_ENTITY, record, "company_id")
    return record


@router.delete("/companies/{company_id}")
async def delete_company(company_id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    existing = json_store.get_by_id(user_id, _COMPANIES_ENTITY, "company_id", company_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    remaining = [
        c for c in json_store.load_all(user_id, _COMPANIES_ENTITY)
        if c.get("company_id") != company_id
    ]
    json_store.save_all(user_id, _COMPANIES_ENTITY, remaining)
    return {"deleted": company_id}


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

_DEFAULT_PREFERENCE_FIELDS = {
    "home_location": None,
    "home_lat": None,
    "home_lng": None,
    "max_commute_km": None,
    "remote_preference": "no_preference",
    "willing_to_relocate": False,
}


class UpdatePreferencesRequest(BaseModel):
    home_location: Optional[str] = None
    max_commute_km: Optional[float] = None
    remote_preference: Optional[str] = None
    willing_to_relocate: Optional[bool] = None


def _load_preferences_or_default(user_id: str) -> dict:
    """Mirrors orchestrator.discovery_graph._load_preferences's fallback:
    a conservative default (no commute limit, no remote requirement, not
    willing to relocate) when the user hasn't set anything yet -- so
    nothing gets excluded by the hard filter until they actually opt in."""
    records = json_store.load_all(user_id, _PREFERENCES_ENTITY)
    if records:
        return records[0]
    return {"user_id": user_id, "updated_at": _now_iso(), **_DEFAULT_PREFERENCE_FIELDS}


@router.get("/preferences")
async def get_preferences(current_user: dict = Depends(get_current_user)):
    return _load_preferences_or_default(current_user["user_id"])


@router.patch("/preferences")
async def patch_preferences(
    body: UpdatePreferencesRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    current = _load_preferences_or_default(user_id)
    fields = body.model_dump(exclude_unset=True)

    if "remote_preference" in fields and fields["remote_preference"] not in _VALID_REMOTE_PREFERENCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"remote_preference must be one of: {sorted(_VALID_REMOTE_PREFERENCES)}",
        )

    updated = {**current, **fields}

    # Re-geocode whenever home_location is part of this request and actually
    # changed value -- including clearing it, which also clears the derived
    # coordinates rather than leaving them stale.
    if "home_location" in fields and fields["home_location"] != current.get("home_location"):
        new_location = fields["home_location"]
        if new_location:
            coords = geocode(new_location)
            updated["home_lat"], updated["home_lng"] = coords if coords else (None, None)
        else:
            updated["home_lat"], updated["home_lng"] = None, None

    updated["user_id"] = user_id
    updated["updated_at"] = _now_iso()

    json_store.save_all(user_id, _PREFERENCES_ENTITY, [updated])
    return updated
