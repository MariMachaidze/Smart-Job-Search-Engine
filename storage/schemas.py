"""
Every data contract used across the system. This module has no behavior --
it's the single source of truth for field names/types that every other
workstream imports and codes against. Keep field names exactly as specified
in the design plan; other agents' code depends on these names matching
verbatim.
"""
from typing import Literal, Optional, TypedDict


class User(TypedDict):
    user_id: str
    email: str
    password_hash: str
    created_at: str
    notify_email: Optional[str]
    digest_enabled: bool
    totp_secret: Optional[str]   # set once 2FA setup begins; None if 2FA was never configured
    totp_enabled: bool           # True only after the user confirms a valid code during setup


class UserPreferences(TypedDict):
    user_id: str
    home_location: Optional[str]
    home_lat: Optional[float]
    home_lng: Optional[float]
    max_commute_km: Optional[float]  # None = no hard limit
    remote_preference: Literal["remote_only", "hybrid_ok", "onsite_ok", "no_preference"]
    willing_to_relocate: bool
    updated_at: str


class ChatMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str
    timestamp: str


class ChatSession(TypedDict):
    session_id: str
    user_id: str
    title: str
    messages: list[ChatMessage]
    created_at: str
    updated_at: str
    summary: Optional[str]  # rolling summary of turns older than the recent-message window
    # (plan section 12, "short-term memory (within one session)"); added by
    # workstream H since no other workstream had a field for this yet --
    # additive/optional, doesn't break any existing ChatSession consumer.


class CompanySource(TypedDict):
    company_id: str
    user_id: str
    company: str
    careers_url: str
    added_at: str


class JobPosting(TypedDict):
    job_id: str
    company: str
    title: str
    location: str
    url: str
    description: str
    source: Literal["greenhouse", "lever", "workday", "scraper"]
    ats_job_id: Optional[str]
    department: Optional[str]
    posted_at: Optional[str]
    discovered_at: str
    last_seen_at: str
    status: Literal["new", "seen", "closed"]
    raw: Optional[dict]
    location_lat: Optional[float]  # geocoded once at persist time
    location_lng: Optional[float]  # geocoded once at persist time
    is_remote: Optional[bool]  # inferred from location text / ATS metadata


class ExperienceEntry(TypedDict):
    company: str
    title: str
    start_date: Optional[str]
    end_date: Optional[str]
    location: Optional[str]
    bullets: list[str]


class EducationEntry(TypedDict):
    institution: str
    degree: Optional[str]
    field: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]


class CandidateProfile(TypedDict):
    profile_id: str
    source_file_s3_key: str
    full_name: str
    email: Optional[str]
    phone: Optional[str]
    location: Optional[str]
    summary: str
    skills: list[str]
    experience: list[ExperienceEntry]
    education: list[EducationEntry]
    certifications: list[str]
    links: list[str]
    raw_text: str
    extracted_at: str


class MatchScore(TypedDict):
    match_id: str
    job_id: str
    profile_id: str
    score: float
    rationale: str
    matched_skills: list[str]
    missing_skills: list[str]
    scored_at: str
    user_feedback: Optional[Literal["relevant", "not_relevant"]]
    feedback_reason: Optional[str]  # free text: "too much travel", "salary too low", "wrong stack", ...


class GeneratedDocument(TypedDict):
    document_id: str
    job_id: str
    profile_id: str
    doc_type: Literal["resume", "cover_letter"]
    s3_key: str
    display_name: str  # e.g. "Resume — Anthropic ML Engineer.docx"
    format: Literal["docx"]
    generated_at: str
    model_notes: Optional[str]


class TrackerStatus(TypedDict):
    status_id: str
    user_id: str
    label: str
    color: str
    order: int


class StatusHistoryEntry(TypedDict):
    status_id: str
    changed_at: str


class Application(TypedDict):
    application_id: str
    user_id: str
    job_id: str
    status_id: str
    status_history: list[StatusHistoryEntry]   # append-only log; status_id always reflects history[-1]
    date_applied: Optional[str]
    referred_by: Optional[str]
    comments: str
    created_at: str
    updated_at: str


class MemoryEntry(TypedDict):
    memory_id: str
    user_id: str
    category: Literal["preference", "feedback", "fact"]
    content: str
    created_at: str
    source: Optional[str]  # session_id, or "auto:rejection_pattern" etc.


class DocumentChunk(TypedDict):
    chunk_id: str
    user_id: str
    source_type: Literal["experience", "skill", "resume", "cover_letter"]
    source_id: str  # profile_id or document_id it was chunked from
    text: str  # plain-text form of one experience entry / skill / resume bullet / cover-letter paragraph
    embedding: list[float]
    created_at: str


class QualificationsProfile(TypedDict):
    qualifications_id: str
    user_id: str
    version: int
    prompt_text: str  # synthesized natural-language qualifications summary
    based_on: dict  # {profile_id, applications_considered, rejections_considered, memory_entries_considered}
    generated_at: str
