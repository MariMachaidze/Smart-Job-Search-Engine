"""
Thin boto3 wrapper for S3-backed file storage. Uploaded resume PDFs and
generated .docx files are binary blobs, not structured records, so they live
in S3 rather than in a JSON file -- the JSON metadata (e.g.
`CandidateProfile.source_file_s3_key`, `GeneratedDocument.s3_key`) just
points at the object key.

Keys are namespaced per user, e.g.:
  users/{user_id}/resumes/{profile_id}.pdf
  users/{user_id}/generated/{document_id}.docx

Env vars (loaded via python-dotenv, matching the pattern in `app/llm.py`):
  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, S3_BUCKET_NAME

NOTE: the boto3 client is constructed lazily (inside `_get_client()`, not at
module import time) so this module stays importable even when no AWS
credentials are configured in the environment -- e.g. for other workstreams
that only need these function signatures to exist before S3 is wired up.

Live testing against a real S3 bucket is deferred: there is no bucket
provisioned in this development environment yet, so these functions are
written to the documented boto3 API but have not been exercised against a
live AWS account.
"""
import os
import tempfile

import boto3
from dotenv import load_dotenv

load_dotenv()

_client = None


def _get_client():
    """Lazily constructs (and caches) the boto3 S3 client on first use."""
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION"),
        )
    return _client


def _bucket_name() -> str:
    bucket = os.getenv("S3_BUCKET_NAME")
    if not bucket:
        raise RuntimeError("S3_BUCKET_NAME environment variable is not set")
    return bucket


def upload_file(local_path: str, key: str) -> str:
    """Uploads the local file at `local_path` to S3 under `key`.
    Returns `key` (the s3_key to store on the JSON record)."""
    _get_client().upload_file(local_path, _bucket_name(), key)
    return key


def upload_bytes(data: bytes, key: str, content_type: str) -> str:
    """Uploads an in-memory `bytes` blob to S3 under `key`.
    Returns `key` (the s3_key to store on the JSON record)."""
    _get_client().put_object(
        Bucket=_bucket_name(), Key=key, Body=data, ContentType=content_type
    )
    return key


def get_presigned_url(key: str, expires_in: int = 3600) -> str:
    """Returns a presigned, time-limited GET URL for `key`, for frontend
    download links (e.g. the Documents page's download button)."""
    return _get_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket_name(), "Key": key},
        ExpiresIn=expires_in,
    )


def download_to_tmp(key: str) -> str:
    """Downloads the object at `key` to a local temp file and returns its
    local path -- for code that needs a local filesystem path (e.g.
    `pdfplumber` reading an uploaded resume back out of S3)."""
    suffix = os.path.splitext(key)[1]
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    _get_client().download_file(_bucket_name(), key, tmp_path)
    return tmp_path
