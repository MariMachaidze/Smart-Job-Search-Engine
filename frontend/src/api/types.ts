/**
 * TypeScript mirrors of storage/schemas.py plus the request/response shapes
 * documented in the plan (section 13: app/main.py route contract) and
 * confirmed against the real, already-built modules where they exist
 * (app/auth.py, tracker/routes.py, stats/aggregator.py, stats/skill_gap.py).
 *
 * Where a route hasn't landed yet (jobs, companies, profile, documents,
 * chat), the shape below is this workstream's best-effort reading of the
 * plan contract -- kept in one place so a later integration pass only has
 * to adjust types here + src/api/mock/fixtures.ts, not call sites.
 */

// ---------------------------------------------------------------------------
// storage/schemas.py mirrors
// ---------------------------------------------------------------------------

export interface User {
  user_id: string
  email: string
  created_at: string
  notify_email: string | null
  digest_enabled: boolean
  totp_enabled: boolean
  // password_hash / totp_secret are stripped server-side before a user
  // record reaches the client (see app/auth.py:_public_user).
}

export interface UserPreferences {
  user_id: string
  home_location: string | null
  home_lat: number | null
  home_lng: number | null
  max_commute_km: number | null
  remote_preference: 'remote_only' | 'hybrid_ok' | 'onsite_ok' | 'no_preference'
  willing_to_relocate: boolean
  updated_at: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  /**
   * Not in storage/schemas.py's ChatMessage -- an additive, frontend-only
   * field this workstream needs per the brief: "structure your
   * message-rendering component so a message can carry either plain text
   * or a list of job-card payloads." Populated when a chat tool call
   * (e.g. list_jobs) returns job-shaped results; the SSE contract this is
   * read from is documented in src/api/client.ts.
   */
  jobs?: JobCardPayload[]
}

export interface ChatSession {
  session_id: string
  user_id: string
  title: string
  messages: ChatMessage[]
  created_at: string
  updated_at: string
}

/** Lightweight shape for the sidebar list (GET /chat/sessions) -- avoids
 * shipping every session's full message history just to render titles. */
export interface ChatSessionSummary {
  session_id: string
  title: string
  created_at: string
  updated_at: string
}

export interface CompanySource {
  company_id: string
  user_id: string
  company: string
  careers_url: string
  added_at: string
}

export interface JobPosting {
  job_id: string
  company: string
  title: string
  location: string
  url: string
  description: string
  source: 'greenhouse' | 'lever' | 'workday' | 'scraper'
  ats_job_id: string | null
  department: string | null
  posted_at: string | null
  discovered_at: string
  last_seen_at: string
  status: 'new' | 'seen' | 'closed'
  location_lat: number | null
  location_lng: number | null
  is_remote: boolean | null
}

/** GET /jobs response row: JobPosting joined with its MatchScore, which is
 * what the Job Search feed and inline chat job-cards both render (plan
 * section 11 + 14). */
export interface JobWithScore extends JobPosting {
  match_id: string | null
  score: number | null
  rationale: string | null
  matched_skills: string[]
  missing_skills: string[]
  user_feedback: 'relevant' | 'not_relevant' | null
  feedback_reason: string | null
}

/** Minimal payload for an inline chat job-card (title/company/score, per
 * plan section 11's "one-tap rate-or-tailor" note). */
export interface JobCardPayload {
  job_id: string
  title: string
  company: string
  score: number | null
  location?: string
}

export interface ExperienceEntry {
  company: string
  title: string
  start_date: string | null
  end_date: string | null
  location: string | null
  bullets: string[]
}

export interface EducationEntry {
  institution: string
  degree: string | null
  field: string | null
  start_date: string | null
  end_date: string | null
}

export interface CandidateProfile {
  profile_id: string
  source_file_s3_key: string
  full_name: string
  email: string | null
  phone: string | null
  location: string | null
  summary: string
  skills: string[]
  experience: ExperienceEntry[]
  education: EducationEntry[]
  certifications: string[]
  links: string[]
  raw_text: string
  extracted_at: string
}

export interface MatchScore {
  match_id: string
  job_id: string
  profile_id: string
  score: number
  rationale: string
  matched_skills: string[]
  missing_skills: string[]
  scored_at: string
  user_feedback: 'relevant' | 'not_relevant' | null
  feedback_reason: string | null
}

export interface GeneratedDocument {
  document_id: string
  job_id: string
  profile_id: string
  doc_type: 'resume' | 'cover_letter'
  s3_key: string
  display_name: string
  format: 'docx'
  generated_at: string
  model_notes: string | null
}

export interface TrackerStatus {
  status_id: string
  user_id: string
  label: string
  color: string
  order: number
}

export interface StatusHistoryEntry {
  status_id: string
  changed_at: string
}

/** The joined view tracker/service.py:list_applications returns: Application
 * fields plus company/title/location/url/description pulled from the
 * linked JobPosting, and status_label resolved from status_id. */
export interface ApplicationJoined {
  application_id: string
  job_id: string
  status_id: string
  status_label: string | null
  status_history: StatusHistoryEntry[]
  date_applied: string | null
  referred_by: string | null
  comments: string
  created_at: string
  updated_at: string
  company: string | null
  title: string | null
  location: string | null
  url: string | null
  description: string | null
}

export interface MemoryEntry {
  memory_id: string
  user_id: string
  category: 'preference' | 'feedback' | 'fact'
  content: string
  created_at: string
  source: string | null
}

// ---------------------------------------------------------------------------
// Auth request/response shapes (verbatim from app/auth.py, already built)
// ---------------------------------------------------------------------------

export interface SignupRequest {
  email: string
  password: string
}

export interface LoginRequest {
  email: string
  password: string
  totp_code?: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: User
}

/** POST /auth/login response. requires_2fa=true + no token means the
 * password was correct but a totp_code is needed -- resubmit the same
 * call with totp_code set (see app/auth.py module docstring). */
export interface LoginResponse {
  requires_2fa: boolean
  access_token?: string | null
  token_type: string
  user?: User | null
}

// ---------------------------------------------------------------------------
// Tracker request/response shapes (verbatim from tracker/routes.py, already built)
// ---------------------------------------------------------------------------

export interface CreateStatusRequest {
  label: string
  color: string
}

export interface UpdateStatusRequest {
  label?: string
  color?: string
  order?: number
}

export interface CreateApplicationRequest {
  job_id: string
  status_label: string
  date_applied?: string | null
  referred_by?: string
  comments?: string
}

export interface UpdateApplicationStatusRequest {
  status_label: string
}

// ---------------------------------------------------------------------------
// Statistics shapes (verbatim from stats/aggregator.py + stats/skill_gap.py)
// ---------------------------------------------------------------------------

export interface StatusCountBucket {
  period: string
  status: string
  count: number
}

export interface StatisticsSummary {
  total_applications: number
  not_yet_applied_count: number
  applied_count: number
  interviewing_count: number
  ever_interviewed_count: number
  no_response_count: number
  offer_count: number
  rejected_count: number
  closed_other_count: number
  other_count: number
  terminal_count: number
  interview_rate: number
  true_interview_rate: number
  rejection_rate: number
  offer_rate: number
  no_response_rate: number
  status_breakdown: Record<string, number>
}

export interface SkillGapResult {
  missing_skills: string[]
  recommendation: string
  based_on_count: number
  threshold_met: boolean
}

// ---------------------------------------------------------------------------
// Companies / preferences / documents / feedback request shapes
// (documented contract, section 13 -- no routes.py landed for these yet)
// ---------------------------------------------------------------------------

export interface CreateCompanyRequest {
  company: string
  careers_url: string
}

export interface JobFeedbackRequest {
  feedback: 'relevant' | 'not_relevant'
  reason?: string
}

export interface TailorResponse {
  resume: GeneratedDocument
  cover_letter: GeneratedDocument
}

export interface DownloadLinkResponse {
  download_url: string
}

// ---------------------------------------------------------------------------
// Chat (H's contract, plan section 12 + the "chat routes" note in the brief)
// ---------------------------------------------------------------------------

export interface SendMessageRequest {
  content: string
}

/**
 * Assumed SSE event payload shape for POST /chat/sessions/{id}/message.
 * Each SSE `data:` line is JSON matching one of these. Documented here
 * (not yet confirmed against H's code) so the streaming client and the
 * mock layer agree on one shape:
 *   - {type: "token", content}          -- incremental assistant text
 *   - {type: "jobs", jobs}              -- a tool call (e.g. list_jobs)
 *                                          resolved to job-shaped results
 *   - {type: "done", message}           -- final persisted ChatMessage
 *   - {type: "error", message}          -- stream-level failure
 */
export type ChatStreamEvent =
  | { type: 'token'; content: string }
  | { type: 'jobs'; jobs: JobCardPayload[] }
  | { type: 'done'; message: ChatMessage }
  | { type: 'error'; message: string }
