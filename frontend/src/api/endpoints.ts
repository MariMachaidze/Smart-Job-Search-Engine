/**
 * Typed wrappers, one group per router, over the documented route contract
 * (plan section 13, plus H's chat routes per section 12). Components import
 * from here, never from client.ts directly -- that keeps every call site
 * typed and keeps client.ts the only file that knows about fetch/localStorage.
 */
import { apiFetch, apiUpload, streamChatMessage as streamChatMessageRaw } from './client'
import type {
  ApplicationJoined,
  CandidateProfile,
  ChatSession,
  ChatSessionSummary,
  ChatStreamEvent,
  CompanySource,
  CreateApplicationRequest,
  CreateCompanyRequest,
  CreateStatusRequest,
  DownloadLinkResponse,
  GeneratedDocument,
  JobFeedbackRequest,
  JobWithScore,
  LoginRequest,
  LoginResponse,
  SignupRequest,
  SkillGapResult,
  StatisticsSummary,
  StatusCountBucket,
  TailorResponse,
  TokenResponse,
  TrackerStatus,
  UpdateApplicationStatusRequest,
  UpdateStatusRequest,
  User,
  UserPreferences,
} from './types'

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export const authApi = {
  signup: (body: SignupRequest) => apiFetch<TokenResponse>('/auth/signup', { method: 'POST', body }),
  login: (body: LoginRequest) => apiFetch<LoginResponse>('/auth/login', { method: 'POST', body }),
  me: () => apiFetch<User>('/auth/me'),
}

// ---------------------------------------------------------------------------
// Profile
// ---------------------------------------------------------------------------

export const profileApi = {
  get: () => apiFetch<CandidateProfile>('/profile'),
  upload: (file: File) => apiUpload<CandidateProfile>('/profile/upload', file),
}

export const preferencesApi = {
  get: () => apiFetch<UserPreferences>('/preferences'),
  update: (fields: Partial<UserPreferences>) =>
    apiFetch<UserPreferences>('/preferences', { method: 'PATCH', body: fields }),
}

// ---------------------------------------------------------------------------
// Companies
// ---------------------------------------------------------------------------

export const companiesApi = {
  list: () => apiFetch<CompanySource[]>('/companies'),
  create: (body: CreateCompanyRequest) => apiFetch<CompanySource>('/companies', { method: 'POST', body }),
  remove: (companyId: string) =>
    apiFetch<{ deleted: string }>(`/companies/${companyId}`, { method: 'DELETE' }),
}

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

export const jobsApi = {
  list: () => apiFetch<JobWithScore[]>('/jobs'),
  rate: (jobId: string, body: JobFeedbackRequest) =>
    apiFetch<JobWithScore>(`/jobs/${jobId}/feedback`, { method: 'POST', body }),
  tailor: (jobId: string) => apiFetch<TailorResponse>(`/jobs/${jobId}/tailor`, { method: 'POST' }),
  runDiscovery: () => apiFetch<{ status: string }>('/discovery/run', { method: 'POST' }),
}

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

export const documentsApi = {
  list: () => apiFetch<GeneratedDocument[]>('/documents'),
  downloadUrl: (documentId: string) =>
    apiFetch<DownloadLinkResponse>(`/documents/${documentId}/download`),
}

// ---------------------------------------------------------------------------
// Tracker
// ---------------------------------------------------------------------------

export const trackerApi = {
  listStatuses: () => apiFetch<TrackerStatus[]>('/tracker/statuses'),
  createStatus: (body: CreateStatusRequest) =>
    apiFetch<TrackerStatus>('/tracker/statuses', { method: 'POST', body }),
  updateStatus: (statusId: string, body: UpdateStatusRequest) =>
    apiFetch<TrackerStatus>(`/tracker/statuses/${statusId}`, { method: 'PATCH', body }),
  deleteStatus: (statusId: string) =>
    apiFetch<{ deleted: string }>(`/tracker/statuses/${statusId}`, { method: 'DELETE' }),

  listApplications: () => apiFetch<ApplicationJoined[]>('/tracker/applications'),
  createApplication: (body: CreateApplicationRequest) =>
    apiFetch<ApplicationJoined>('/tracker/applications', { method: 'POST', body }),
  updateApplicationStatus: (applicationId: string, body: UpdateApplicationStatusRequest) =>
    apiFetch<ApplicationJoined>(`/tracker/applications/${applicationId}`, { method: 'PATCH', body }),
}

// ---------------------------------------------------------------------------
// Statistics
// ---------------------------------------------------------------------------

export const statisticsApi = {
  summary: () => apiFetch<StatisticsSummary>('/statistics/summary'),
  timeseries: (granularity: 'daily' | 'monthly' = 'daily') =>
    apiFetch<StatusCountBucket[]>(`/statistics/timeseries?granularity=${granularity}`),
  skillGap: () => apiFetch<SkillGapResult>('/statistics/skill-gap'),
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

export const chatApi = {
  listSessions: () => apiFetch<ChatSessionSummary[]>('/chat/sessions'),
  createSession: () => apiFetch<ChatSession>('/chat/sessions', { method: 'POST' }),
  getSession: (sessionId: string) => apiFetch<ChatSession>(`/chat/sessions/${sessionId}`),
  deleteSession: (sessionId: string) =>
    apiFetch<{ deleted: string }>(`/chat/sessions/${sessionId}`, { method: 'DELETE' }),
  streamMessage: (
    sessionId: string,
    content: string,
    onEvent: (event: ChatStreamEvent) => void,
    signal?: AbortSignal,
  ) => streamChatMessageRaw(sessionId, content, onEvent, signal),
}
