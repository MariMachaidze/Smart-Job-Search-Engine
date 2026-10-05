"""
Stub — the user is designing and implementing this module's internals themselves
(see plan section 6a: structure-aware chunking of experience/skill/resume/cover_letter
content, embedding, flat vector store, pure semantic search, no knowledge graph).

This file only exists so other workstreams (Document Generation, Qualifications
Updater) can import a stable contract and keep working without blocking. Replace
the bodies below with the real implementation — do not change the signatures
without updating the plan and the callers.
"""
from typing import Any


def _experience_entry_to_chunk(entry: dict) -> str:
    """
    One chunk per whole experience/project entry, not per bullet. Bullets
    within one job are kept together — order doesn't matter, they're joined
    as a single blob — because an experience is naturally one coherent unit
    (a role has a title, dates, and a handful of bullets that only make full
    sense together), and splitting it apart was adding a decision (bullet
    ordering, prefix-per-bullet) that didn't earn its complexity once
    attribution lives in the text itself either way.

    Company/title/dates lead the chunk so retrieval and any downstream LLM
    read always sees them — same attribution reasoning as before, just
    applied once per entry instead of once per bullet.
    """
    dates = f"{entry.get('start_date', '')} - {entry.get('end_date') or 'Present'}"
    header = f"{entry.get('title', '')} at {entry.get('company', '')} ({dates})"
    bullets = " ".join(b.strip() for b in entry.get("bullets", []) if b.strip())
    return f"{header}: {bullets}" if bullets else header


def _skill_to_chunk(skill: str) -> str:
    """
    A skill needs no transformation -- "Python" is already the whole unit of
    meaning, with no company/dates/narrative to attach. This function exists
    anyway (instead of just using profile["skills"] directly) for one
    reason: it's the single place to add context later if you ever want it
    (e.g. "Python (5 years)" once proficiency/duration gets tracked) without
    having to go find every call site that reads skills.
    """
    return skill.strip()


def index_profile(user_id: str, profile: dict) -> None:
    """No-op until implemented. Should chunk profile experience/skill entries,
    embed them, and persist as DocumentChunk records for this user."""
    return None


def index_generated_document(user_id: str, document: dict, doc_text: str) -> None:
    """No-op until implemented. Should chunk the generated resume/cover-letter
    text, embed it, and persist as DocumentChunk records for this user."""
    return None
