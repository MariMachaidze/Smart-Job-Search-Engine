"""
Daily "jobs you liked but haven't applied to yet" digest (plan section 10).

`build_and_send_daily_digest(user_id)`:
  1. finds every MatchScore with user_feedback == "relevant" whose job_id
     has no corresponding Application record yet (cross-referencing
     storage.json_store.load_all(user_id, "scores") against
     load_all(user_id, "applications") by job_id);
  2. if the user has digest_enabled (default True) and at least one such
     job exists, builds one HTML digest email (title/company/link/score per
     job) and sends it via notifications.email.send_email to
     user["notify_email"], falling back to user["email"];
  3. if there's nothing to report, sends nothing -- an empty digest is
     worse than no digest.
"""
from html import escape
from typing import Optional

from notifications.email import send_email
from storage import json_store


def _get_user(user_id: str) -> Optional[dict]:
    """Looks up a User record by user_id from the global account list.
    (storage.json_store only exposes lookup-by-email directly; this does
    the equivalent scan by user_id.)"""
    for user in json_store.load_users():
        if user.get("user_id") == user_id:
            return user
    return None


def find_relevant_unapplied_jobs(user_id: str) -> list[dict]:
    """Returns [{"score": MatchScore, "job": JobPosting}, ...] for every
    MatchScore marked 'relevant' that has no Application yet for its
    job_id. `job` is {} if the job record itself can't be found (e.g. it
    was later removed), so display code should use .get() defensively."""
    scores = json_store.load_all(user_id, "scores")
    applications = json_store.load_all(user_id, "applications")
    applied_job_ids = {app.get("job_id") for app in applications}

    relevant_unapplied = [
        score
        for score in scores
        if score.get("user_feedback") == "relevant"
        and score.get("job_id") not in applied_job_ids
    ]
    if not relevant_unapplied:
        return []

    jobs_by_id = {job.get("job_id"): job for job in json_store.load_all(user_id, "jobs")}
    return [
        {"score": score, "job": jobs_by_id.get(score.get("job_id"), {})}
        for score in relevant_unapplied
    ]


def _build_digest_html(joined_rows: list[dict]) -> str:
    items = []
    for row in joined_rows:
        job = row["job"]
        score = row["score"]
        title = escape(job.get("title") or "Untitled role")
        company = escape(job.get("company") or "Unknown company")
        url = escape(job.get("url") or "#")
        score_value = score.get("score")
        score_text = f"{score_value:.0f}" if isinstance(score_value, (int, float)) else "N/A"
        items.append(
            f"<li><strong>{title}</strong> at {company} "
            f"(match score: {score_text}) &mdash; "
            f'<a href="{url}">view posting</a></li>'
        )

    return (
        "<p>You marked these jobs as relevant but haven't applied to them yet:</p>"
        f"<ul>{''.join(items)}</ul>"
        "<p>They may close soon -- consider applying while you still can.</p>"
    )


def build_and_send_daily_digest(user_id: str) -> None:
    """Builds and sends the daily digest email for `user_id`, if there's
    anything to report and the user hasn't opted out. No-op (no email sent,
    no error raised) when the user can't be found, digest_enabled is False,
    there's no usable recipient address, or there's nothing to report."""
    user = _get_user(user_id)
    if user is None:
        return

    if not user.get("digest_enabled", True):
        return

    joined_rows = find_relevant_unapplied_jobs(user_id)
    if not joined_rows:
        return

    recipient = user.get("notify_email") or user.get("email")
    if not recipient:
        return

    count = len(joined_rows)
    subject = f"{count} job{'s' if count != 1 else ''} you liked, still unapplied"
    html_body = _build_digest_html(joined_rows)
    send_email(to=recipient, subject=subject, html_body=html_body)
