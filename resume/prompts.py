"""
resume/prompts.py — shared prompt-building helper for resume/tailor.py and
resume/cover_letter.py (plan section 6).

Both generation functions call `rag.retriever.retrieve_relevant_chunks`
before building their prompt and fold whatever comes back into a "past
phrasing" section via `format_past_phrasing_section` below. The retriever is
a deliberate no-op stub today (always returns []) until workstream Q lands
the real RAG implementation, so this produces an explicit "none available"
note rather than breaking or silently omitting the section.
"""


def format_past_phrasing_section(chunks: list[dict]) -> str:
    """Formats retrieved DocumentChunk-shaped dicts (or [] if RAG retrieval
    hasn't returned anything, which is always true today) into a prompt
    section. Chunks are framed strictly as phrasing/style reference, never
    as a source of new facts -- the caller's own prompt rules re-assert that
    every output fact must independently trace back to the candidate
    profile, regardless of what shows up here."""
    if not chunks:
        return (
            "(No past resume/cover-letter chunks were retrieved for this query -- "
            "RAG retrieval is not yet populated for this user. Proceed using only "
            "the candidate profile above.)"
        )
    lines = [
        "The following snippets are PHRASING/STYLE references only, drawn from the "
        "candidate's own past resumes/cover letters. You may reuse phrasing or tone from "
        "them, but every fact you output must still independently be present in the "
        "candidate profile above -- ignore any fact-like content here that doesn't also "
        "appear in the profile.",
    ]
    for chunk in chunks:
        text = chunk.get("text") if isinstance(chunk, dict) else None
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines)
