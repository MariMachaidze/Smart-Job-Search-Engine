/**
 * MSW request handlers for every route in the documented contract (plan
 * section 13 + H's chat routes, section 12). Backed by the mutable
 * src/api/mock/data.ts store so interactions persist for a session/test.
 *
 * This is the layer a later integration pass deletes (or stops
 * registering in src/main.tsx) once the real backend is reachable --
 * nothing in src/api/endpoints.ts or any component needs to change.
 */
import { http, HttpResponse } from 'msw'
import {
  logMockRequest,
  mockState,
  MOCK_2FA_CODE,
  nextMockId,
} from './data'
import type {
  ApplicationJoined,
  CandidateProfile,
  ChatMessage,
  ChatSession,
  ChatSessionSummary,
  ChatStreamEvent,
  CompanySource,
  CreateApplicationRequest,
  CreateCompanyRequest,
  CreateStatusRequest,
  GeneratedDocument,
  JobFeedbackRequest,
  LoginRequest,
  LoginResponse,
  SignupRequest,
  SkillGapResult,
  StatisticsSummary,
  StatusCountBucket,
  TokenResponse,
  TrackerStatus,
  UpdateApplicationStatusRequest,
  UpdateStatusRequest,
  User,
} from '../types'

const DEFAULT_STATUS_SEED: Array<{ label: string; color: string }> = [
  { label: 'Need to Apply', color: '#E0E0E0' },
  { label: 'Applied', color: '#C8E6C9' },
  { label: 'Unsolicited Application', color: '#7E57C2' },
  { label: 'Email to be sent', color: '#2196F3' },
  { label: 'Need Referral', color: '#E53935' },
  { label: 'First Round scheduled', color: '#FFAB91' },
  { label: 'Second Round scheduled', color: '#CFD8DC' },
  { label: 'Interviewed', color: '#B3E5FC' },
  { label: 'Lost track of round', color: '#E1BEE7' },
  { label: 'No Reply', color: '#795548' },
  { label: 'Accepted', color: '#2E7D32' },
  { label: 'Rejected', color: '#B71C1C' },
  { label: 'Applied but closed', color: '#8D2E2E' },
  { label: 'Closed', color: '#D32F2F' },
]

function publicUser(u: User & { password?: string; totp_code?: string }): User {
  return {
    user_id: u.user_id,
    email: u.email,
    created_at: u.created_at,
    notify_email: u.notify_email,
    digest_enabled: u.digest_enabled,
    totp_enabled: u.totp_enabled,
  }
}

function tokenFor(userId: string): string {
  return `mock-token-${userId}`
}

function requireAuth(request: Request): User | null {
  const auth = request.headers.get('Authorization') ?? ''
  const match = auth.match(/^Bearer (.+)$/)
  if (!match) return null
  const token = match[1]
  const prefix = 'mock-token-'
  if (!token.startsWith(prefix)) return null
  const userId = token.slice(prefix.length)
  const user = mockState.users.find((u) => u.user_id === userId)
  return user ? publicUser(user) : null
}

function unauthorized() {
  return HttpResponse.json({ detail: 'Not authenticated' }, { status: 401 })
}

export const handlers = [
  // -------------------------------------------------------------------
  // Auth
  // -------------------------------------------------------------------
  http.post('*/auth/signup', async ({ request }) => {
    const body = (await request.json()) as SignupRequest
    logMockRequest('POST', '/auth/signup', body)
    const email = body.email.trim().toLowerCase()
    if (mockState.users.some((u) => u.email === email)) {
      return HttpResponse.json({ detail: 'An account with this email already exists' }, { status: 400 })
    }
    const userId = nextMockId('user')
    const user = {
      user_id: userId,
      email,
      password: body.password,
      created_at: new Date().toISOString(),
      notify_email: email,
      digest_enabled: true,
      totp_enabled: false,
    }
    mockState.users.push(user)
    mockState.currentUserId = userId
    mockState.statuses = DEFAULT_STATUS_SEED.map((s, i) => ({
      status_id: `status-${userId}-${i}`,
      user_id: userId,
      label: s.label,
      color: s.color,
      order: i,
    }))
    const res: TokenResponse = {
      access_token: tokenFor(userId),
      token_type: 'bearer',
      user: publicUser(user),
    }
    return HttpResponse.json(res)
  }),

  http.post('*/auth/login', async ({ request }) => {
    const body = (await request.json()) as LoginRequest
    logMockRequest('POST', '/auth/login', body)
    const email = body.email.trim().toLowerCase()
    const user = mockState.users.find((u) => u.email === email)
    if (!user || user.password !== body.password) {
      return HttpResponse.json({ detail: 'Incorrect email or password' }, { status: 401 })
    }
    if (user.totp_enabled) {
      if (!body.totp_code) {
        const res: LoginResponse = { requires_2fa: true, token_type: 'bearer' }
        return HttpResponse.json(res)
      }
      if (body.totp_code !== (user.totp_code ?? MOCK_2FA_CODE)) {
        return HttpResponse.json({ detail: 'Invalid or expired two-factor code' }, { status: 401 })
      }
    }
    mockState.currentUserId = user.user_id
    const res: LoginResponse = {
      requires_2fa: false,
      access_token: tokenFor(user.user_id),
      token_type: 'bearer',
      user: publicUser(user),
    }
    return HttpResponse.json(res)
  }),

  http.get('*/auth/me', ({ request }) => {
    const user = requireAuth(request)
    if (!user) return unauthorized()
    return HttpResponse.json(user)
  }),

  // -------------------------------------------------------------------
  // Profile
  // -------------------------------------------------------------------
  http.get('*/profile', ({ request }) => {
    if (!requireAuth(request)) return unauthorized()
    if (!mockState.profile) return HttpResponse.json({ detail: 'No profile on file' }, { status: 404 })
    return HttpResponse.json(mockState.profile)
  }),

  http.post('*/profile/upload', async ({ request }) => {
    if (!requireAuth(request)) return unauthorized()
    logMockRequest('POST', '/profile/upload', '(multipart file upload)')
    // Mock: re-use the existing seeded profile, just bump extracted_at, as
    // if re-parsing had happened.
    const updated: CandidateProfile = {
      ...(mockState.profile as CandidateProfile),
      extracted_at: new Date().toISOString(),
    }
    mockState.profile = updated
    return HttpResponse.json(updated)
  }),

  // -------------------------------------------------------------------
  // Companies
  // -------------------------------------------------------------------
  http.get('*/companies', ({ request }) => {
    if (!requireAuth(request)) return unauthorized()
    return HttpResponse.json(mockState.companies)
  }),

  http.post('*/companies', async ({ request }) => {
    if (!requireAuth(request)) return unauthorized()
    const body = (await request.json()) as CreateCompanyRequest
    logMockRequest('POST', '/companies', body)
    const company: CompanySource = {
      company_id: nextMockId('company'),
      user_id: mockState.currentUserId,
      company: body.company,
      careers_url: body.careers_url,
      added_at: new Date().toISOString(),
    }
    mockState.companies.push(company)
    return HttpResponse.json(company, { status: 201 })
  }),

  http.delete('*/companies/:id', ({ request, params }) => {
    if (!requireAuth(request)) return unauthorized()
    const id = params.id as string
    logMockRequest('DELETE', `/companies/${id}`, null)
    mockState.companies = mockState.companies.filter((c) => c.company_id !== id)
    return HttpResponse.json({ deleted: id })
  }),

  // -------------------------------------------------------------------
  // Jobs
  // -------------------------------------------------------------------
  http.get('*/jobs', ({ request }) => {
    if (!requireAuth(request)) return unauthorized()
    return HttpResponse.json(mockState.jobs)
  }),

  http.post('*/jobs/:id/feedback', async ({ request, params }) => {
    if (!requireAuth(request)) return unauthorized()
    const id = params.id as string
    const body = (await request.json()) as JobFeedbackRequest
    logMockRequest('POST', `/jobs/${id}/feedback`, body)
    const job = mockState.jobs.find((j) => j.job_id === id)
    if (!job) return HttpResponse.json({ detail: 'Job not found' }, { status: 404 })
    job.user_feedback = body.feedback
    job.feedback_reason = body.reason ?? null
    return HttpResponse.json(job)
  }),

  http.post('*/jobs/:id/tailor', ({ request, params }) => {
    if (!requireAuth(request)) return unauthorized()
    const id = params.id as string
    logMockRequest('POST', `/jobs/${id}/tailor`, null)
    const job = mockState.jobs.find((j) => j.job_id === id)
    const jobTitle = job ? `${job.title} (${job.company})` : id
    const now = new Date().toISOString()
    const resume: GeneratedDocument = {
      document_id: nextMockId('doc'),
      job_id: id,
      profile_id: mockState.profile?.profile_id ?? 'profile-1',
      doc_type: 'resume',
      s3_key: `users/${mockState.currentUserId}/generated/${nextMockId('doc')}.docx`,
      display_name: `Resume — ${jobTitle}.docx`,
      format: 'docx',
      generated_at: now,
      model_notes: null,
    }
    const coverLetter: GeneratedDocument = {
      document_id: nextMockId('doc'),
      job_id: id,
      profile_id: mockState.profile?.profile_id ?? 'profile-1',
      doc_type: 'cover_letter',
      s3_key: `users/${mockState.currentUserId}/generated/${nextMockId('doc')}.docx`,
      display_name: `Cover Letter — ${jobTitle}.docx`,
      format: 'docx',
      generated_at: now,
      model_notes: null,
    }
    mockState.documents.push(resume, coverLetter)
    return HttpResponse.json({ resume, cover_letter: coverLetter })
  }),

  http.post('*/discovery/run', ({ request }) => {
    if (!requireAuth(request)) return unauthorized()
    logMockRequest('POST', '/discovery/run', null)
    return HttpResponse.json({ status: 'started' })
  }),

  // -------------------------------------------------------------------
  // Documents
  // -------------------------------------------------------------------
  http.get('*/documents', ({ request }) => {
    if (!requireAuth(request)) return unauthorized()
    return HttpResponse.json(mockState.documents)
  }),

  http.get('*/documents/:id/download', ({ request, params }) => {
    if (!requireAuth(request)) return unauthorized()
    const id = params.id as string
    return HttpResponse.json({ download_url: `https://mock-s3.example.com/${id}?presigned=1` })
  }),

  // -------------------------------------------------------------------
  // Tracker
  // -------------------------------------------------------------------
  http.get('*/tracker/statuses', ({ request }) => {
    if (!requireAuth(request)) return unauthorized()
    return HttpResponse.json(mockState.statuses)
  }),

  http.post('*/tracker/statuses', async ({ request }) => {
    if (!requireAuth(request)) return unauthorized()
    const body = (await request.json()) as CreateStatusRequest
    logMockRequest('POST', '/tracker/statuses', body)
    const status: TrackerStatus = {
      status_id: nextMockId('status'),
      user_id: mockState.currentUserId,
      label: body.label,
      color: body.color,
      order: mockState.statuses.length,
    }
    mockState.statuses.push(status)
    return HttpResponse.json(status, { status: 201 })
  }),

  http.patch('*/tracker/statuses/:id', async ({ request, params }) => {
    if (!requireAuth(request)) return unauthorized()
    const id = params.id as string
    const body = (await request.json()) as UpdateStatusRequest
    logMockRequest('PATCH', `/tracker/statuses/${id}`, body)
    const status = mockState.statuses.find((s) => s.status_id === id)
    if (!status) return HttpResponse.json({ detail: 'Status not found' }, { status: 404 })
    Object.assign(status, body)
    return HttpResponse.json(status)
  }),

  http.delete('*/tracker/statuses/:id', ({ request, params }) => {
    if (!requireAuth(request)) return unauthorized()
    const id = params.id as string
    logMockRequest('DELETE', `/tracker/statuses/${id}`, null)
    if (mockState.applications.some((a) => a.status_id === id)) {
      return HttpResponse.json({ detail: 'Status is in use by at least one application' }, { status: 409 })
    }
    mockState.statuses = mockState.statuses.filter((s) => s.status_id !== id)
    return HttpResponse.json({ deleted: id })
  }),

  http.get('*/tracker/applications', ({ request }) => {
    if (!requireAuth(request)) return unauthorized()
    return HttpResponse.json(mockState.applications)
  }),

  http.post('*/tracker/applications', async ({ request }) => {
    if (!requireAuth(request)) return unauthorized()
    const body = (await request.json()) as CreateApplicationRequest
    logMockRequest('POST', '/tracker/applications', body)
    const status = mockState.statuses.find((s) => s.label === body.status_label)
    if (!status) return HttpResponse.json({ detail: `Unknown status label: ${body.status_label}` }, { status: 400 })
    const job = mockState.jobs.find((j) => j.job_id === body.job_id)
    const now = new Date().toISOString()
    const application: ApplicationJoined = {
      application_id: nextMockId('app'),
      job_id: body.job_id,
      status_id: status.status_id,
      status_label: status.label,
      status_history: [{ status_id: status.status_id, changed_at: now }],
      date_applied: body.date_applied ?? null,
      referred_by: body.referred_by ?? '',
      comments: body.comments ?? '',
      created_at: now,
      updated_at: now,
      company: job?.company ?? null,
      title: job?.title ?? null,
      location: job?.location ?? null,
      url: job?.url ?? null,
      description: job?.description ?? null,
    }
    mockState.applications.push(application)
    return HttpResponse.json(application, { status: 201 })
  }),

  http.patch('*/tracker/applications/:id', async ({ request, params }) => {
    if (!requireAuth(request)) return unauthorized()
    const id = params.id as string
    const body = (await request.json()) as UpdateApplicationStatusRequest
    logMockRequest('PATCH', `/tracker/applications/${id}`, body)
    const application = mockState.applications.find((a) => a.application_id === id)
    if (!application) return HttpResponse.json({ detail: 'Application not found' }, { status: 404 })
    const status = mockState.statuses.find((s) => s.label === body.status_label)
    if (!status) return HttpResponse.json({ detail: `Unknown status label: ${body.status_label}` }, { status: 400 })
    const now = new Date().toISOString()
    application.status_id = status.status_id
    application.status_label = status.label
    application.status_history.push({ status_id: status.status_id, changed_at: now })
    application.updated_at = now
    return HttpResponse.json(application)
  }),

  // -------------------------------------------------------------------
  // Statistics
  // -------------------------------------------------------------------
  http.get('*/statistics/summary', ({ request }) => {
    if (!requireAuth(request)) return unauthorized()
    const summary: StatisticsSummary = {
      total_applications: mockState.applications.length,
      not_yet_applied_count: 1,
      applied_count: 2,
      interviewing_count: 0,
      ever_interviewed_count: 0,
      no_response_count: 0,
      offer_count: 0,
      rejected_count: 1,
      closed_other_count: 0,
      other_count: 0,
      terminal_count: 1,
      interview_rate: 0,
      true_interview_rate: 0,
      rejection_rate: 0.5,
      offer_rate: 0,
      no_response_rate: 0,
      status_breakdown: { Applied: 1, Rejected: 1, 'Need to Apply': 1 },
    }
    return HttpResponse.json(summary)
  }),

  http.get('*/statistics/timeseries', ({ request }) => {
    if (!requireAuth(request)) return unauthorized()
    const buckets: StatusCountBucket[] = [
      { period: '2026-09-27', status: 'Applied', count: 1 },
      { period: '2026-09-29', status: 'Need to Apply', count: 1 },
      { period: '2026-10-02', status: 'Rejected', count: 1 },
    ]
    return HttpResponse.json(buckets)
  }),

  http.get('*/statistics/skill-gap', ({ request }) => {
    if (!requireAuth(request)) return unauthorized()
    const result: SkillGapResult = {
      missing_skills: ['Kubernetes', 'Go', 'Scala'],
      recommendation:
        'Kubernetes and Go appeared in most of your recent rejections -- worth a focused study pass on both before your next round of backend applications.',
      based_on_count: 1,
      threshold_met: false,
    }
    return HttpResponse.json(result)
  }),

  // -------------------------------------------------------------------
  // Chat
  // -------------------------------------------------------------------
  http.get('*/chat/sessions', ({ request }) => {
    if (!requireAuth(request)) return unauthorized()
    const summaries: ChatSessionSummary[] = mockState.chatSessions
      .map((s) => ({ session_id: s.session_id, title: s.title, created_at: s.created_at, updated_at: s.updated_at }))
      .sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))
    return HttpResponse.json(summaries)
  }),

  http.post('*/chat/sessions', ({ request }) => {
    if (!requireAuth(request)) return unauthorized()
    logMockRequest('POST', '/chat/sessions', null)
    const now = new Date().toISOString()
    const session: ChatSession = {
      session_id: nextMockId('session'),
      user_id: mockState.currentUserId,
      title: 'New conversation',
      messages: [],
      created_at: now,
      updated_at: now,
    }
    mockState.chatSessions.unshift(session)
    return HttpResponse.json(session, { status: 201 })
  }),

  http.get('*/chat/sessions/:id', ({ request, params }) => {
    if (!requireAuth(request)) return unauthorized()
    const id = params.id as string
    const session = mockState.chatSessions.find((s) => s.session_id === id)
    if (!session) return HttpResponse.json({ detail: 'Session not found' }, { status: 404 })
    return HttpResponse.json(session)
  }),

  http.delete('*/chat/sessions/:id', ({ request, params }) => {
    if (!requireAuth(request)) return unauthorized()
    const id = params.id as string
    logMockRequest('DELETE', `/chat/sessions/${id}`, null)
    mockState.chatSessions = mockState.chatSessions.filter((s) => s.session_id !== id)
    return HttpResponse.json({ deleted: id })
  }),

  http.post('*/chat/sessions/:id/message', async ({ request, params }) => {
    if (!requireAuth(request)) return unauthorized()
    const id = params.id as string
    const body = (await request.json()) as { content: string }
    logMockRequest('POST', `/chat/sessions/${id}/message`, body)
    const session = mockState.chatSessions.find((s) => s.session_id === id)

    const userMessage: ChatMessage = { role: 'user', content: body.content, timestamp: new Date().toISOString() }
    const mentionsJobs = /\bjobs?\b|\bsearch\b|\bdiscover/i.test(body.content)

    const replyText = mentionsJobs
      ? 'Here are a couple of matches from your current feed -- want me to tailor a resume for either?'
      : `(mock reply) You said: "${body.content}"`

    const jobCards = mentionsJobs
      ? mockState.jobs.slice(0, 2).map((j) => ({ job_id: j.job_id, title: j.title, company: j.company, score: j.score, location: j.location }))
      : undefined

    const assistantMessage: ChatMessage = {
      role: 'assistant',
      content: replyText,
      timestamp: new Date().toISOString(),
      ...(jobCards ? { jobs: jobCards } : {}),
    }

    if (session) {
      session.messages.push(userMessage, assistantMessage)
      session.updated_at = new Date().toISOString()
      if (session.messages.length === 2 && session.title === 'New conversation') {
        session.title = body.content.slice(0, 40)
      }
    }

    const encoder = new TextEncoder()
    const words = replyText.split(' ')

    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        const send = (event: ChatStreamEvent) => {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
        }
        for (const word of words) {
          send({ type: 'token', content: word + ' ' })
          // eslint-disable-next-line no-await-in-loop
          await new Promise((r) => setTimeout(r, 15))
        }
        if (jobCards) {
          send({ type: 'jobs', jobs: jobCards })
        }
        send({ type: 'done', message: assistantMessage })
        controller.close()
      },
    })

    return new HttpResponse(stream, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
      },
    })
  }),
]
