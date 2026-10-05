"""
Thin httpx-based wrapper around Resend's transactional email API.

Resend was picked over SendGrid for this workstream: a single
`POST https://api.resend.com/emails` call with a Bearer API key and a flat
JSON payload satisfies the plan's "Resend or SendGrid" choice (section 10)
with the least incidental surface area -- no SDK, no separate sender-
verification flow to stub around, just plain HTTP via `httpx`.

Env vars (loaded via python-dotenv, matching the pattern in `app/llm.py`):
  RESEND_API_KEY    -- Resend API key (https://resend.com/api-keys)
  DIGEST_FROM_EMAIL -- the verified "from" address to send as

NOTE: the API key/from-address are only read inside `send_email`, not at
module import time -- same pattern `storage/s3_client.py` uses for AWS
credentials -- so this module stays importable with zero env vars set.
`send_email` only raises once it's actually invoked without them.

There is no real Resend account configured in this dev environment, so
`send_email` has not been exercised against the live API. It was verified
with a mocked `httpx.post` (asserting URL, auth header, and payload shape)
-- see the workstream summary for what was mocked vs genuinely run.
"""
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

RESEND_API_URL = "https://api.resend.com/emails"


def send_email(to: str, subject: str, html_body: str) -> None:
    """Sends one HTML email via Resend's API.

    Raises RuntimeError if RESEND_API_KEY or DIGEST_FROM_EMAIL isn't set, or
    httpx.HTTPStatusError if Resend rejects the request -- both only at call
    time, never at import time, so modules that merely import this one
    (e.g. notifications.digest, orchestrator.scheduled_jobs) stay importable
    with no email credentials configured.
    """
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError(
            "RESEND_API_KEY environment variable is not set -- cannot send email."
        )
    from_email = os.getenv("DIGEST_FROM_EMAIL")
    if not from_email:
        raise RuntimeError(
            "DIGEST_FROM_EMAIL environment variable is not set -- cannot send email."
        )

    response = httpx.post(
        RESEND_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": from_email,
            "to": [to],
            "subject": subject,
            "html": html_body,
        },
        timeout=10.0,
    )
    response.raise_for_status()
