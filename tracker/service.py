"""
Application tracker service (workstream I, plan section 7).

Owns two user-scoped entities, persisted through `storage.json_store`:
  - `tracker_statuses` -- the user's customizable status pipeline
    (`storage.schemas.TrackerStatus`), seeded at signup by the Auth
    workstream from `storage.default_statuses.DEFAULT_STATUSES`.
  - `applications` -- one record per job application
    (`storage.schemas.Application`), referencing a `JobPosting` (`job_id`)
    and a `TrackerStatus` (`status_id`).

Callers (routes, the future chat agent) talk about statuses by their
human-readable `label` ("Interviewed"), never by `status_id` -- so every
function that takes a `status_label` resolves it against the user's current
`list_statuses()` and raises `StatusLabelNotFoundError` if no status with
that label exists for that user.

"Close but don't delete": `update_application_status(..., "Closed")` is just
a normal status change. There is deliberately no delete-application
function anywhere in this module -- application history is never removed.
`delete_status` only removes a now-unused entry from the status *picker*,
and refuses (raises `StatusInUseError`) if any `Application` still
references it.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from storage import json_store

_STATUSES_ENTITY = "tracker_statuses"
_APPLICATIONS_ENTITY = "applications"
_JOBS_ENTITY = "jobs"

_ALLOWED_STATUS_UPDATE_FIELDS = {"label", "color", "order"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class TrackerError(Exception):
    """Base class for tracker-domain errors."""


class StatusNotFoundError(TrackerError):
    """Raised when a `status_id` doesn't exist for this user."""


class StatusLabelNotFoundError(TrackerError):
    """Raised when a human-readable status label doesn't match any of the
    user's current statuses. Callers (including the chat agent) pass labels,
    not ids, so this is the error surface they need to handle -- e.g. by
    listing valid labels back to the user."""


class StatusInUseError(TrackerError):
    """Raised by `delete_status` when at least one `Application` still
    references the status -- deletion is refused, not cascaded."""


class ApplicationNotFoundError(TrackerError):
    """Raised when an `application_id` doesn't exist for this user."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------

def list_statuses(user_id: str) -> list[dict]:
    """Returns the user's `TrackerStatus` list, ordered by `order`."""
    statuses = json_store.load_all(user_id, _STATUSES_ENTITY)
    return sorted(statuses, key=lambda s: s.get("order", 0))


def _get_status_by_id(user_id: str, status_id: str) -> Optional[dict]:
    return json_store.get_by_id(user_id, _STATUSES_ENTITY, "status_id", status_id)


def _resolve_status_id(user_id: str, status_label: str) -> str:
    """Resolves a human-readable label to this user's current `status_id`.

    Raises `StatusLabelNotFoundError` (with the available labels in the
    message) if no status with that label exists for the user -- callers
    are expected to pass labels they got from `list_statuses()`, so a
    mismatch almost always means a stale/typo'd label from the caller.
    """
    statuses = list_statuses(user_id)
    for status in statuses:
        if status.get("label") == status_label:
            return status["status_id"]
    available = ", ".join(repr(s.get("label")) for s in statuses)
    raise StatusLabelNotFoundError(
        f"No tracker status labeled {status_label!r} for this user. "
        f"Available labels: {available}"
    )


def create_status(user_id: str, label: str, color: str) -> dict:
    """Creates a new `TrackerStatus`, appended to the end of the order."""
    statuses = list_statuses(user_id)
    new_status = {
        "status_id": str(uuid.uuid4()),
        "user_id": user_id,
        "label": label,
        "color": color,
        "order": len(statuses),
    }
    json_store.upsert(user_id, _STATUSES_ENTITY, new_status, "status_id")
    return new_status


def update_status(user_id: str, status_id: str, **fields) -> dict:
    """Updates one or more of `label`/`color`/`order` on an existing status.

    Raises `StatusNotFoundError` if `status_id` doesn't belong to this user,
    or `ValueError` if an unsupported field name is passed (guards against
    silently ignoring a caller typo like `colour=`).
    """
    unknown = set(fields) - _ALLOWED_STATUS_UPDATE_FIELDS
    if unknown:
        raise ValueError(
            f"update_status got unsupported field(s) {sorted(unknown)}; "
            f"allowed: {sorted(_ALLOWED_STATUS_UPDATE_FIELDS)}"
        )

    status = _get_status_by_id(user_id, status_id)
    if status is None:
        raise StatusNotFoundError(f"No tracker status {status_id!r} for this user.")

    status = {**status, **fields}
    json_store.upsert(user_id, _STATUSES_ENTITY, status, "status_id")
    return status


def delete_status(user_id: str, status_id: str) -> None:
    """Deletes a status from the picker -- only if no `Application`
    currently references it.

    Raises `StatusNotFoundError` if `status_id` doesn't belong to this user,
    or `StatusInUseError` if at least one `Application` still has this
    `status_id` (the fix is to move those applications to another status
    first; this function never cascades that change itself).
    """
    status = _get_status_by_id(user_id, status_id)
    if status is None:
        raise StatusNotFoundError(f"No tracker status {status_id!r} for this user.")

    applications = json_store.load_all(user_id, _APPLICATIONS_ENTITY)
    in_use = any(app.get("status_id") == status_id for app in applications)
    if in_use:
        raise StatusInUseError(
            f"Tracker status {status_id!r} ({status.get('label')!r}) is still "
            f"referenced by at least one application and cannot be deleted."
        )

    remaining = [s for s in json_store.load_all(user_id, _STATUSES_ENTITY) if s.get("status_id") != status_id]
    json_store.save_all(user_id, _STATUSES_ENTITY, remaining)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

def create_application(
    user_id: str,
    job_id: str,
    status_label: str,
    date_applied: Optional[str],
    referred_by: Optional[str] = "",
    comments: str = "",
) -> dict:
    """Creates a new `Application` linking `job_id` to a status (resolved
    from `status_label`). Raises `StatusLabelNotFoundError` if the label
    doesn't match any of the user's current statuses."""
    status_id = _resolve_status_id(user_id, status_label)
    now = _now_iso()
    application = {
        "application_id": str(uuid.uuid4()),
        "user_id": user_id,
        "job_id": job_id,
        "status_id": status_id,
        "status_history": [{"status_id": status_id, "changed_at": now}],
        "date_applied": date_applied,
        "referred_by": referred_by or "",
        "comments": comments or "",
        "created_at": now,
        "updated_at": now,
    }
    json_store.upsert(user_id, _APPLICATIONS_ENTITY, application, "application_id")
    return application


def update_application_status(user_id: str, application_id: str, status_label: str) -> dict:
    """Changes an application's status. This is the ONLY way an
    `Application` is ever modified after creation, including closing one:
    `update_application_status(..., "Closed")` is just a normal status
    change -- the record and its full history stay in `applications.json`.

    Appends a new `StatusHistoryEntry` to `status_history` rather than
    replacing it, so the full journey (e.g. Applied -> Interviewed ->
    Rejected) is preserved even once `status_id` only reflects the latest
    state -- this is what lets statistics answer "was this ever
    Interviewed?" for an application that was later rejected/closed.

    Raises `ApplicationNotFoundError` if `application_id` doesn't belong to
    this user, or `StatusLabelNotFoundError` if the label doesn't match any
    of the user's current statuses.
    """
    application = json_store.get_by_id(user_id, _APPLICATIONS_ENTITY, "application_id", application_id)
    if application is None:
        raise ApplicationNotFoundError(f"No application {application_id!r} for this user.")

    status_id = _resolve_status_id(user_id, status_label)
    now = _now_iso()
    # status_history is append-only: every status change -- including moving
    # to "Closed" -- adds a new entry rather than overwriting the last one,
    # so stats can answer "was this ever Interviewed?" even after it's later
    # Rejected/Closed. Default to [] for any pre-existing record that
    # predates this field, rather than raising a KeyError on old data.
    history = list(application.get("status_history") or [])
    history.append({"status_id": status_id, "changed_at": now})
    application = {
        **application,
        "status_id": status_id,
        "status_history": history,
        "updated_at": now,
    }
    json_store.upsert(user_id, _APPLICATIONS_ENTITY, application, "application_id")
    return application


def list_applications(user_id: str) -> list[dict]:
    """Joined view backing the tracker table: for every `Application`,
    merges in the linked `JobPosting`'s company/title/url/description/
    location and the linked `TrackerStatus`'s label/color.

    If a linked job or status can no longer be found (e.g. data corruption
    -- `delete_status` itself prevents this in the normal path), the
    corresponding joined fields are returned as `None` rather than raising,
    since this is a read view and one bad row shouldn't break the whole
    table.
    """
    applications = json_store.load_all(user_id, _APPLICATIONS_ENTITY)
    statuses_by_id = {s["status_id"]: s for s in json_store.load_all(user_id, _STATUSES_ENTITY)}

    joined = []
    for application in applications:
        job = json_store.get_by_id(user_id, _JOBS_ENTITY, "job_id", application.get("job_id"))
        status = statuses_by_id.get(application.get("status_id"))

        joined.append({
            "application_id": application.get("application_id"),
            "job_id": application.get("job_id"),
            "status_id": application.get("status_id"),
            "status_label": status.get("label") if status else None,
            "status_color": status.get("color") if status else None,
            "status_history": application.get("status_history") or [],
            "company": job.get("company") if job else None,
            "title": job.get("title") if job else None,
            "url": job.get("url") if job else None,
            "description": job.get("description") if job else None,
            "location": job.get("location") if job else None,
            "date_applied": application.get("date_applied"),
            "referred_by": application.get("referred_by"),
            "comments": application.get("comments"),
            "created_at": application.get("created_at"),
            "updated_at": application.get("updated_at"),
        })

    return joined
