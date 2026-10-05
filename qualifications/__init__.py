"""Qualifications-prompt-updater package (workstream R).

See plan section 8a ("Qualifications prompt updater - the self-improving
matching prompt") for the design this package implements. It periodically
synthesizes a natural-language QualificationsProfile.prompt_text from the
candidate's base profile plus everything learned since (long-term memory,
explicit "not relevant" feedback reasons, RAG-retrieved past
resume/cover-letter context, rejection-driven skill-gap analysis, and recent
application outcomes) -- that synthesized prompt, not the raw CandidateProfile,
is what matching/scorer.py scores jobs against once it exists.
"""
