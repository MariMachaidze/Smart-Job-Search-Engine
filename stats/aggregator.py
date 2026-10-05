"""
Statistics derived purely from a user's tracker data (`applications.json` +
`tracker_statuses.json`, joined against `jobs.json`) -- no separate stats
storage, everything here is computed on read.

`tracker/service.py` (workstream I) now exists, so `_joined_applications`
below calls its `list_applications(user_id)` joined view rather than
re-deriving the join -- it falls back to a manual join directly against
`storage.json_store`/`storage.schemas` only if `tracker.service` can't be
imported (e.g. in an isolated test), so this module keeps working either
way.
"""
from collections import defaultdict
from datetime import datetime
from typing import Literal, Optional

from storage import json_store

try:
    from tracker.service import list_applications as _tracker_list_applications
except ImportError:  # tracker/service.py not importable -- fall back below
    _tracker_list_applications = None

# ---------------------------------------------------------------------------
# Timestamp choice (documented, so other workstreams/UI can match semantics):
#
# `Application` has `created_at` (when the record was first created) and
# `updated_at` (bumped on every field change, including status changes --
# see `storage/schemas.py`). Application does NOT keep a status-change log,
# only the current `status_id`. So the best available proxy for "when did
# this application enter the status it's currently in" is `updated_at`:
#   - a brand-new application has created_at == updated_at, so it buckets on
#     its creation date under whatever its initial status is.
#   - a later status change (e.g. "Applied" -> "Rejected") bumps updated_at,
#     so the count moves to the new bucket on the date of that change, which
#     is exactly the "crossed with status label" semantic the design doc
#     describes.
# We fall back to created_at only if updated_at is somehow missing.
#
# Known limitation this implies: bucketing here is still CURRENT-status-only
# (by date of last change), so an application that was "Interviewed" and
# later became "Rejected" shows up only under "Rejected" going forward --
# that transient "Interviewed" day never gets its own bucket. `Application`
# now also carries an append-only `status_history` (added after this module
# was first written, to support `compute_summary`'s `ever_interviewed_count`
# below), which COULD be used to bucket every historical transition instead
# of just the current one -- that's a reasonable future improvement to
# `compute_status_counts`, but out of scope for the fix that added
# `status_history` support here, so it's left as current-status-only for
# now. `compute_summary`'s `ever_interviewed_count`/`true_interview_rate` are
# the first consumers of the new field.
# ---------------------------------------------------------------------------


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parses an ISO-8601 timestamp string (as produced by
    `datetime.now(timezone.utc).isoformat()` elsewhere in this codebase, e.g.
    `app/auth.py`). Returns None if `value` is falsy or unparseable."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _bucket_period(timestamp: datetime, granularity: Literal["daily", "monthly"]) -> str:
    if granularity == "monthly":
        return timestamp.strftime("%Y-%m")
    return timestamp.strftime("%Y-%m-%d")


def _joined_applications(user_id: str) -> list[dict]:
    """Application + TrackerStatus + JobPosting, joined view. Returns one
    flat dict per application with the fields `compute_status_counts`/
    `compute_summary` and `stats/skill_gap.py` need: application_id, job_id,
    status_id, status_label, status_history, date_applied, referred_by,
    comments, created_at, updated_at, company, title, location, url,
    description.

    Prefers `tracker.service.list_applications(user_id)` (the real joined
    view, which already includes `status_history`); falls back to a manual
    join directly against `storage.json_store`/`storage.schemas` only if
    `tracker.service` isn't importable."""
    if _tracker_list_applications is not None:
        joined = _tracker_list_applications(user_id)
        # tracker.service's joined dicts don't guarantee a status_history
        # key on every record (e.g. pre-history-field data) -- normalize so
        # downstream code always finds the key present (possibly empty).
        for app in joined:
            app.setdefault("status_history", [])
        return joined

    applications = json_store.load_all(user_id, "applications")
    statuses = json_store.load_all(user_id, "tracker_statuses")
    jobs = json_store.load_all(user_id, "jobs")

    status_by_id = {s.get("status_id"): s for s in statuses}
    job_by_id = {j.get("job_id"): j for j in jobs}

    joined = []
    for app in applications:
        status = status_by_id.get(app.get("status_id"))
        job = job_by_id.get(app.get("job_id"))
        joined.append({
            "application_id": app.get("application_id"),
            "job_id": app.get("job_id"),
            "status_id": app.get("status_id"),
            "status_label": status.get("label") if status else None,
            "status_history": app.get("status_history") or [],
            "date_applied": app.get("date_applied"),
            "referred_by": app.get("referred_by"),
            "comments": app.get("comments"),
            "created_at": app.get("created_at"),
            "updated_at": app.get("updated_at"),
            "company": job.get("company") if job else None,
            "title": job.get("title") if job else None,
            "location": job.get("location") if job else None,
            "url": job.get("url") if job else None,
            "description": job.get("description") if job else None,
        })
    return joined


def _status_label_map(user_id: str) -> dict[str, str]:
    """Maps every `status_id` the user currently has defined to its
    `label`, for resolving the raw `status_id`s stored in each
    application's `status_history` entries. Uses current labels (if a
    status was renamed, history entries resolve to the new name, same as
    everywhere else in this module that only ever looks at current
    labels, never labels-at-the-time)."""
    statuses = json_store.load_all(user_id, "tracker_statuses")
    return {s.get("status_id"): s.get("label") for s in statuses}


def _ever_in_category(app: dict, category: str, status_label_map: dict[str, str]) -> bool:
    """True if ANY entry in `app`'s `status_history` resolves to `category`
    (per `_category_for_label`), regardless of the application's current
    status. This is what makes `ever_interviewed_count` (see
    `compute_summary`) accurate even for an application that later moved on
    to "Rejected"/"Closed"/etc.

    Defensive fallback: if `status_history` is missing/empty (malformed or
    pre-history-field data), treats the application's current `status_id`
    as a one-entry history rather than erroring or silently returning
    False -- same defensive posture as the rest of this module.
    """
    history = app.get("status_history") or [{
        "status_id": app.get("status_id"),
        "changed_at": app.get("updated_at") or app.get("created_at"),
    }]
    for entry in history:
        label = status_label_map.get(entry.get("status_id"))
        if label is None and entry.get("status_id") == app.get("status_id"):
            # status_id map lookup can miss if the status was since deleted;
            # the app's own resolved status_label is still a good fallback
            # for the entry that matches the current status_id.
            label = app.get("status_label")
        if _category_for_label(label) == category:
            return True
    return False


def compute_status_counts(user_id: str, granularity: Literal["daily", "monthly"] = "daily") -> list[dict]:
    """Buckets the user's applications by date (see timestamp note above --
    `updated_at`, falling back to `created_at`) crossed with current status
    label.

    Returns e.g.:
        [{"period": "2026-09-28", "status": "Applied", "count": 3}, ...]
    sorted by period then status, ascending.
    """
    apps = _joined_applications(user_id)
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for app in apps:
        ts = _parse_timestamp(app.get("updated_at")) or _parse_timestamp(app.get("created_at"))
        if ts is None:
            continue
        label = app.get("status_label") or "Unknown"
        period = _bucket_period(ts, granularity)
        buckets[period][label] += 1

    result = []
    for period in sorted(buckets.keys()):
        for label in sorted(buckets[period].keys()):
            result.append({"period": period, "status": label, "count": buckets[period][label]})
    return result


# ---------------------------------------------------------------------------
# Outcome categorization used by compute_summary (and reused by
# stats/skill_gap.py for its threshold check). Status labels are matched
# case-insensitively against storage.default_statuses.DEFAULT_STATUSES'
# labels; any custom/renamed status the user has added that doesn't match
# one of these buckets falls into "other" and is excluded from the rate
# denominators below (it's still counted in total_applications and in
# status_breakdown).
#
# Rationale for each bucket:
#   - not_yet_applied: statuses that mean the application hasn't actually
#     been submitted yet ("Need to Apply", "Email to be sent",
#     "Need Referral" -- all pre-submission/action-pending states).
#   - applied: submitted, no further-defined outcome yet (plain "Applied",
#     or "Unsolicited Application" which was submitted without a specific
#     posting prompting it).
#   - interviewing: some interview engagement happened, per CURRENT status
#     (see the Application-has-no-history limitation noted above).
#   - no_response: submitted, silence.
#   - offer: "Accepted".
#   - rejected: explicit rejection, or the job closed after applying
#     ("Applied but closed" is functionally a rejection -- the application
#     will never progress -- so it's grouped with "Rejected" here, matching
#     section 8's "Rejected"/"Applied but closed" pairing).
#   - closed_other: generic "Closed" -- ambiguous (could be user-withdrawn,
#     accepted elsewhere, etc.), so it's tracked separately and NOT folded
#     into rejected/offer so it doesn't skew those rates either way.
# ---------------------------------------------------------------------------

_NOT_YET_APPLIED = {"need to apply", "email to be sent", "need referral"}
_APPLIED = {"applied", "unsolicited application"}
_INTERVIEWING = {"first round scheduled", "second round scheduled", "interviewed", "lost track of round"}
_NO_RESPONSE = {"no reply"}
_OFFER = {"accepted"}
_REJECTED = {"rejected", "applied but closed"}
_CLOSED_OTHER = {"closed"}

# Terminal = the application will not progress further either way. Used by
# stats/skill_gap.py's "rejection rate > 50% of applications with a terminal
# status" threshold check.
_TERMINAL = _OFFER | _REJECTED | _CLOSED_OTHER


def _category_for_label(label: Optional[str]) -> str:
    key = (label or "").strip().lower()
    if key in _NOT_YET_APPLIED:
        return "not_yet_applied"
    if key in _APPLIED:
        return "applied"
    if key in _INTERVIEWING:
        return "interviewing"
    if key in _NO_RESPONSE:
        return "no_response"
    if key in _OFFER:
        return "offer"
    if key in _REJECTED:
        return "rejected"
    if key in _CLOSED_OTHER:
        return "closed_other"
    return "other"


def compute_summary(user_id: str) -> dict:
    """Totals + rates across the user's applications.

    IMPORTANT distinction between the two interview metrics returned here --
    do not confuse them:

      - `interviewing_count` / `interview_rate`: CURRENT-status-only, i.e.
        "how many applications are *right now* sitting in an interviewing
        status (First/Second Round scheduled, Interviewed, Lost track of
        round)". An application that was interviewed and later moved to
        "Rejected" is NOT counted here -- its current status is "Rejected",
        full stop. This is the original metric from this module, kept
        as-is for anyone already reading "currently interviewing" off it.

      - `ever_interviewed_count` / `true_interview_rate`: HISTORY-aware --
        scans each application's append-only `Application.status_history`
        (added to the schema specifically to fix this undercount) for ANY
        entry that ever resolved to the "interviewing" category, regardless
        of where the application ended up afterward. An application that
        went Applied -> Interviewed -> Rejected counts here even though its
        current status is "Rejected". This is the accurate "did I ever get
        an interview for this application" answer; `interviewing_count`
        structurally cannot answer that question since it only looks at one
        point in time (now).

      Use `ever_interviewed_count`/`true_interview_rate` for "how many
      interviews have I actually gotten" type questions; use
      `interviewing_count`/`interview_rate` for "how many interviews are
      currently in flight" type questions.

    Defensive handling: if an `Application` has no `status_history` (old
    data from before this field existed, or malformed records), it's
    treated as a one-entry history containing just its current status --
    see `_ever_in_category`. This never raises.

    Rate denominators are `applied_count` (every application that has
    actually been submitted at least once, i.e. every status except the
    "not yet applied" bucket) unless noted otherwise.

    Returns:
        {
            "total_applications": int,          # every Application record, any status
            "not_yet_applied_count": int,
            "applied_count": int,                # denominator for the rates below
            "interviewing_count": int,           # CURRENT status only -- see docstring above
            "ever_interviewed_count": int,       # HISTORY-aware -- see docstring above
            "no_response_count": int,
            "offer_count": int,
            "rejected_count": int,               # "Rejected" + "Applied but closed"
            "closed_other_count": int,
            "other_count": int,                  # custom statuses not in any known bucket
            "terminal_count": int,                # offer + rejected + closed_other
            "interview_rate": float,             # interviewing_count / applied_count (current-status-only)
            "true_interview_rate": float,        # ever_interviewed_count / applied_count (history-aware)
            "rejection_rate": float,             # rejected_count / applied_count
            "offer_rate": float,                 # offer_count / applied_count
            "no_response_rate": float,           # no_response_count / applied_count
            "status_breakdown": {label: count, ...},  # raw counts per actual status label
        }
    All rates are 0.0 (not an error) when applied_count is 0.
    """
    apps = _joined_applications(user_id)
    status_label_map = _status_label_map(user_id)

    counts = {
        "not_yet_applied": 0, "applied": 0, "interviewing": 0, "no_response": 0,
        "offer": 0, "rejected": 0, "closed_other": 0, "other": 0,
    }
    status_breakdown: dict[str, int] = defaultdict(int)
    ever_interviewed_count = 0

    for app in apps:
        label = app.get("status_label") or "Unknown"
        status_breakdown[label] += 1
        counts[_category_for_label(app.get("status_label"))] += 1
        if _ever_in_category(app, "interviewing", status_label_map):
            ever_interviewed_count += 1

    applied_count = (
        counts["applied"] + counts["interviewing"] + counts["no_response"]
        + counts["offer"] + counts["rejected"] + counts["closed_other"] + counts["other"]
    )
    terminal_count = counts["offer"] + counts["rejected"] + counts["closed_other"]

    def rate(numerator: int) -> float:
        return round(numerator / applied_count, 4) if applied_count else 0.0

    return {
        "total_applications": len(apps),
        "not_yet_applied_count": counts["not_yet_applied"],
        "applied_count": applied_count,
        "interviewing_count": counts["interviewing"],
        "ever_interviewed_count": ever_interviewed_count,
        "no_response_count": counts["no_response"],
        "offer_count": counts["offer"],
        "rejected_count": counts["rejected"],
        "closed_other_count": counts["closed_other"],
        "other_count": counts["other"],
        "terminal_count": terminal_count,
        "interview_rate": rate(counts["interviewing"]),
        "true_interview_rate": rate(ever_interviewed_count),
        "rejection_rate": rate(counts["rejected"]),
        "offer_rate": rate(counts["offer"]),
        "no_response_rate": rate(counts["no_response"]),
        "status_breakdown": dict(status_breakdown),
    }
