"""
Stub — the user is designing and implementing this module's internals themselves
(see plan section 6a). Returns an empty list until implemented, so callers
(resume/tailor.py, resume/cover_letter.py, qualifications/updater.py) degrade
gracefully to "no retrieved context" rather than failing.
"""
from typing import Optional


def retrieve_relevant_chunks(
    user_id: str,
    query: str,
    top_k: int = 8,
    source_types: Optional[list[str]] = None,
) -> list[dict]:
    """Returns [] until implemented. Should rank DocumentChunk records for this
    user by semantic similarity to `query` and return the top_k."""
    return []
