"""
Centralizes resolution of the `data/` directory so that `json_store.py` (and
any other storage module) doesn't hardcode paths inline.

The data directory defaults to `data/` relative to the repository root, but
can be overridden via the `DATA_DIR` environment variable -- e.g. for tests,
which can point it at a temp directory instead of the real `data/` tree.

Nothing here is cached at import time: every call re-reads `DATA_DIR` from
the environment, so tests can monkeypatch/set the env var per-test without
needing to reload this module.
"""
import os

# Repository root = one level up from this file (storage/paths.py -> repo root)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_data_dir() -> str:
    """Returns the absolute path to the data directory, honoring the
    `DATA_DIR` env var override; defaults to `<repo_root>/data`."""
    override = os.environ.get("DATA_DIR")
    if override:
        return os.path.abspath(override)
    return os.path.join(_REPO_ROOT, "data")


def users_file_path() -> str:
    """Path to the global account list: data/users.json"""
    return os.path.join(get_data_dir(), "users.json")


def user_dir_path(user_id: str) -> str:
    """Path to a user's per-user data directory: data/users/{user_id}/

    This directory does not exist until the user signs up -- callers that
    write into it are responsible for creating it lazily (see
    `json_store._write_json_atomic`, which does this automatically).
    """
    return os.path.join(get_data_dir(), "users", user_id)


def user_entity_path(user_id: str, entity: str) -> str:
    """Path to a user-scoped entity file: data/users/{user_id}/{entity}.json

    `entity` is e.g. "jobs", "scores", "documents", "companies",
    "chat_sessions", "tracker_statuses", "applications", "profile",
    "preferences", "memory", "qualifications".
    """
    return os.path.join(user_dir_path(user_id), f"{entity}.json")
