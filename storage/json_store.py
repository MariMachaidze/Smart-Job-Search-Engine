"""
Generic, user-scoped JSON persistence API. This is the ONLY module that
touches `data/*.json` directly -- every other package reads/writes through
these functions rather than opening files itself. This is also what makes a
later SQLite swap cheap: only this module's internals would need to change.

Concurrency safety
-------------------
Every read-modify-write cycle (`upsert`, `save_user`) and every single write
(`save_all`, `save_profile`) is serialized with a per-file lock (`filelock`),
scoped to the exact `data/users/{user_id}/{entity}.json` path being touched
(lock file: `<path>.lock`), held for the full duration of that operation.
`filelock.FileLock` is documented as both thread-safe and process-safe, so
this holds whether concurrent callers are threads in one process (e.g. a
FastAPI app handling two requests) or separate processes (e.g. the API
process and a scheduler process).

This fixes two distinct bugs that existed in an earlier unlocked version:
1. Two concurrent writers both targeting a single hardcoded `<path>.tmp`
   file could race on that shared tmp path, causing `os.replace()` to raise
   `FileNotFoundError` (one writer's replace consumes the tmp file the other
   was still writing to) or produce corrupted/interleaved content. Fixed by
   giving every write call its own uniquely-named tmp file
   (`<path>.<uuid4>.tmp`) -- concurrent writers never share a tmp path.
2. `upsert`'s load -> modify -> save cycle had no locking, so two concurrent
   upserts to the same entity file could interleave: both read the same
   starting state, both compute their own updated list, and whichever saves
   last silently overwrites the other's change -- no exception, both callers
   see success, one record just vanishes. Fixed by holding the per-file lock
   across the *entire* read-modify-write cycle, so concurrent upserts to the
   same file are fully serialized rather than racing.

See `storage/test_json_store_concurrency.py` for a live test that
reproduces the original bug and proves the fix across many repeated runs
with real concurrent threads.

Writes are also atomic in the usual sense: each write goes to its (now
unique) tmp file first, then `os.replace()` swaps it into place, so a crash
mid-write never leaves a corrupt/partial JSON file on disk.

Per-user directories (`data/users/{user_id}/`) are created lazily on first
write for that user -- they don't exist until a user signs up.
"""
import json
import os
import uuid
from typing import Optional

from filelock import FileLock

from storage.paths import get_data_dir, user_dir_path, user_entity_path, users_file_path


def _lock_path(path: str) -> str:
    return path + ".lock"


def _get_lock(path: str) -> FileLock:
    """Returns a FileLock scoped to `path`, ensuring `path`'s parent
    directory exists first (the lock file itself needs the directory to be
    present, and per-user directories may not exist yet on first write)."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return FileLock(_lock_path(path))


def _read_json_nolock(path: str, default):
    """Reads JSON from `path`, returning `default` if the file doesn't
    exist. Caller is responsible for holding the appropriate lock, if any
    (see `_read_json_locked` for the standalone, locked version)."""
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json_atomic_nolock(path: str, data) -> None:
    """Writes `data` as JSON to `path` atomically: writes to a uniquely
    named tmp file, then `os.replace()`s it into place. The unique name
    (per-call uuid4) means concurrent writers never collide on the same tmp
    path. Caller is responsible for holding the appropriate lock, if any."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp_path = f"{path}.{uuid.uuid4().hex}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def _read_json_locked(path: str, default):
    """Locked standalone read: acquires `path`'s lock for just this read."""
    with _get_lock(path):
        return _read_json_nolock(path, default)


def _write_json_atomic_locked(path: str, data) -> None:
    """Locked standalone write: acquires `path`'s lock for just this write."""
    with _get_lock(path):
        _write_json_atomic_nolock(path, data)


# ---------------------------------------------------------------------------
# Generic user-scoped entity collections (jobs, scores, documents, companies,
# chat_sessions, tracker_statuses, applications, memory, qualifications, ...)
# ---------------------------------------------------------------------------

def load_all(user_id: str, entity: str) -> list[dict]:
    """Loads the full list of records for `entity` belonging to `user_id`.
    Returns [] if the entity file doesn't exist yet."""
    path = user_entity_path(user_id, entity)
    return _read_json_locked(path, [])


def save_all(user_id: str, entity: str, records: list[dict]) -> None:
    """Overwrites the full list of records for `entity` belonging to `user_id`.

    Locked for the duration of the write so this can't collide with a
    concurrent `upsert`/`save_all` targeting the same entity file."""
    path = user_entity_path(user_id, entity)
    _write_json_atomic_locked(path, records)


def upsert(user_id: str, entity: str, record: dict, key_field: str) -> None:
    """Inserts `record`, or replaces the existing record whose `key_field`
    value matches, within `entity`'s collection for `user_id`.

    The read, modify, and write are performed as one atomic critical
    section under a single lock acquisition (NOT by calling the public
    `load_all`/`save_all`, which would each acquire-and-release the lock
    separately and reopen the lost-update race between them). This is what
    makes concurrent upserts to the same entity file fully serialize rather
    than interleave."""
    path = user_entity_path(user_id, entity)
    with _get_lock(path):
        records = _read_json_nolock(path, [])
        key_value = record.get(key_field)
        for i, existing in enumerate(records):
            if existing.get(key_field) == key_value:
                records[i] = record
                break
        else:
            records.append(record)
        _write_json_atomic_nolock(path, records)


def get_by_id(user_id: str, entity: str, id_field: str, id_value: str) -> Optional[dict]:
    """Returns the first record in `entity`'s collection for `user_id` whose
    `id_field` equals `id_value`, or None if not found."""
    records = load_all(user_id, entity)
    for record in records:
        if record.get(id_field) == id_value:
            return record
    return None


# ---------------------------------------------------------------------------
# Profile (single record per user, not a list)
# ---------------------------------------------------------------------------

def load_profile(user_id: str) -> Optional[dict]:
    """Loads the user's CandidateProfile dict, or None if not yet uploaded."""
    path = user_entity_path(user_id, "profile")
    return _read_json_locked(path, None)


def save_profile(user_id: str, profile: dict) -> None:
    """Overwrites the user's CandidateProfile dict."""
    path = user_entity_path(user_id, "profile")
    _write_json_atomic_locked(path, profile)


# ---------------------------------------------------------------------------
# Global user account list (data/users.json)
# ---------------------------------------------------------------------------

def load_users() -> list[dict]:
    """Loads the full global list of User records."""
    return _read_json_locked(users_file_path(), [])


def get_user_by_email(email: str) -> Optional[dict]:
    """Returns the User record matching `email`, or None if not found."""
    for user in load_users():
        if user.get("email") == email:
            return user
    return None


def save_user(user: dict) -> None:
    """Inserts `user`, or replaces the existing User record with the same
    `user_id`, in the global account list. Also ensures that user's
    per-user data directory exists.

    Same locked read-modify-write pattern as `upsert`: the whole cycle runs
    under one lock acquisition on `data/users.json`, so two concurrent
    signups can't lose one of each other's records."""
    path = users_file_path()
    with _get_lock(path):
        users = _read_json_nolock(path, [])
        user_id = user.get("user_id")
        for i, existing in enumerate(users):
            if existing.get("user_id") == user_id:
                users[i] = user
                break
        else:
            users.append(user)
        _write_json_atomic_nolock(path, users)
    os.makedirs(user_dir_path(user_id), exist_ok=True)
