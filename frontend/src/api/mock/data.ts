/**
 * In-memory mock "backend" state, matching the TypedDicts in
 * storage/schemas.py field-for-field. Mutated by src/api/mock/handlers.ts
 * so interactions (rate a job, add a company, change a tracker status...)
 * actually persist for the lifetime of a dev session or a test file,
 * instead of handlers returning the same static blob on every call.
 *
 * `mockRequestLog` records every handled request's {method, path, body} so
 * component tests can assert "submitting this form actually POSTed this
 * payload" without reaching into MSW internals.
 */
import type {
  ApplicationJoined,
  CandidateProfile,
  ChatSession,
  CompanySource,
  GeneratedDocument,
  JobWithScore,
  TrackerStatus,
  User,
} from '../types'

export interface MockUserRecord extends User {
  password: string // plaintext, mock-only -- never how the real backend works
  totp_code?: string // fixed "valid code" for the mock 2FA demo account
}

export const MOCK_DEMO_EMAIL = 'demo@example.com'
export const MOCK_DEMO_PASSWORD = 'password123'
export const MOCK_2FA_EMAIL = '2fa@example.com'
export const MOCK_2FA_PASSWORD = 'password123'
export const MOCK_2FA_CODE = '123456'

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

function buildDefaultStatuses(userId: string): TrackerStatus[] {
  return DEFAULT_STATUS_SEED.map((s, i) => ({
    status_id: `status-${i}`,
    user_id: userId,
    label: s.label,
    color: s.color,
    order: i,
  }))
}

export interface MockState {
  users: MockUserRecord[]
  currentUserId: string
  companies: CompanySource[]
  jobs: JobWithScore[]
  profile: CandidateProfile | null
  documents: GeneratedDocument[]
  statuses: TrackerStatus[]
  applications: ApplicationJoined[]
  chatSessions: ChatSession[]
  nextId: number
}

function freshState(): MockState {
  const demoUserId = 'user-demo-1'
  const statuses = buildDefaultStatuses(demoUserId)
  const byLabel = (label: string) => statuses.find((s) => s.label === label)!.status_id

  const jobs: JobWithScore[] = [
    {
      job_id: 'job-1',
      company: 'Anthropic',
      title: 'ML Engineer, Alignment',
      location: 'San Francisco, CA',
      url: 'https://www.anthropic.com/careers/jobs/ml-engineer-alignment',
      description:
        'Work on alignment research and productionizing safety techniques. Python, PyTorch, distributed training experience wanted.',
      source: 'greenhouse',
      ats_job_id: 'gh-1001',
      department: 'Research',
      posted_at: '2026-09-28T09:00:00+00:00',
      discovered_at: '2026-09-29T06:00:00+00:00',
      last_seen_at: '2026-10-03T06:00:00+00:00',
      status: 'new',
      location_lat: 37.7749,
      location_lng: -122.4194,
      is_remote: false,
      match_id: 'match-1',
      score: 88,
      rationale: 'Strong overlap on PyTorch, distributed systems, and research background.',
      matched_skills: ['Python', 'PyTorch', 'Distributed Systems'],
      missing_skills: ['JAX'],
      user_feedback: null,
      feedback_reason: null,
    },
    {
      job_id: 'job-2',
      company: 'OpenAI',
      title: 'Backend Engineer, Platform',
      location: 'Remote',
      url: 'https://openai.com/careers/backend-engineer-platform',
      description: 'Build and scale backend services powering the API platform. Go, Kubernetes, PostgreSQL.',
      source: 'lever',
      ats_job_id: 'lever-2002',
      department: 'Engineering',
      posted_at: '2026-09-30T09:00:00+00:00',
      discovered_at: '2026-10-01T06:00:00+00:00',
      last_seen_at: '2026-10-03T06:00:00+00:00',
      status: 'seen',
      location_lat: null,
      location_lng: null,
      is_remote: true,
      match_id: 'match-2',
      score: 72,
      rationale: 'Good backend overlap; limited direct Kubernetes experience on file.',
      matched_skills: ['PostgreSQL', 'Backend Systems'],
      missing_skills: ['Kubernetes', 'Go'],
      user_feedback: 'relevant',
      feedback_reason: null,
    },
    {
      job_id: 'job-3',
      company: 'Stripe',
      title: 'Software Engineer, Risk',
      location: 'Dublin, Ireland',
      url: 'https://stripe.com/jobs/software-engineer-risk',
      description: 'Build fraud detection systems at scale. Java or Scala preferred, ML pipeline experience a plus.',
      source: 'greenhouse',
      ats_job_id: 'gh-3003',
      department: 'Risk Engineering',
      posted_at: '2026-09-25T09:00:00+00:00',
      discovered_at: '2026-09-26T06:00:00+00:00',
      last_seen_at: '2026-10-02T06:00:00+00:00',
      status: 'seen',
      location_lat: 53.3498,
      location_lng: -6.2603,
      is_remote: false,
      match_id: 'match-3',
      score: 54,
      rationale: 'Some ML overlap, but stack (Java/Scala) differs from candidate experience.',
      matched_skills: ['ML Pipelines'],
      missing_skills: ['Java', 'Scala'],
      user_feedback: 'not_relevant',
      feedback_reason: 'wrong stack',
    },
    {
      job_id: 'job-4',
      company: 'Anthropic',
      title: 'Research Engineer, Interpretability',
      location: 'San Francisco, CA',
      url: 'https://www.anthropic.com/careers/jobs/research-engineer-interpretability',
      description: 'Investigate interpretability techniques for large language models. Strong research + engineering hybrid role.',
      source: 'greenhouse',
      ats_job_id: 'gh-1002',
      department: 'Research',
      posted_at: '2026-10-02T09:00:00+00:00',
      discovered_at: '2026-10-03T06:00:00+00:00',
      last_seen_at: '2026-10-03T06:00:00+00:00',
      status: 'new',
      location_lat: 37.7749,
      location_lng: -122.4194,
      is_remote: false,
      match_id: 'match-4',
      score: 91,
      rationale: 'Excellent fit: interpretability research background and PyTorch fluency.',
      matched_skills: ['PyTorch', 'Research', 'LLMs'],
      missing_skills: [],
      user_feedback: null,
      feedback_reason: null,
    },
  ]

  const profile: CandidateProfile = {
    profile_id: 'profile-1',
    source_file_s3_key: 'users/user-demo-1/resumes/profile-1.pdf',
    full_name: 'Mariam Machaidze',
    email: MOCK_DEMO_EMAIL,
    phone: '+1 555-010-2020',
    location: 'San Francisco, CA',
    summary: 'Machine learning engineer with 5 years of experience building and deploying production ML systems.',
    skills: ['Python', 'PyTorch', 'Distributed Systems', 'PostgreSQL', 'Backend Systems', 'ML Pipelines', 'React'],
    experience: [
      {
        company: 'Example AI Labs',
        title: 'Senior ML Engineer',
        start_date: '2023-01',
        end_date: null,
        location: 'San Francisco, CA',
        bullets: [
          'Led a team building a distributed training pipeline reducing training time by 40%.',
          'Shipped a production ranking model serving 2M daily requests.',
        ],
      },
      {
        company: 'Prior Startup Inc.',
        title: 'ML Engineer',
        start_date: '2020-06',
        end_date: '2022-12',
        location: 'Remote',
        bullets: ['Built the first version of the recommendation engine from scratch.'],
      },
    ],
    education: [
      {
        institution: 'State University',
        degree: 'M.S.',
        field: 'Computer Science',
        start_date: '2018-09',
        end_date: '2020-05',
      },
    ],
    certifications: [],
    links: ['https://github.com/example', 'https://linkedin.com/in/example'],
    raw_text: '(full extracted resume text would appear here)',
    extracted_at: '2026-09-15T12:00:00+00:00',
  }

  const documents: GeneratedDocument[] = [
    {
      document_id: 'doc-1',
      job_id: 'job-2',
      profile_id: 'profile-1',
      doc_type: 'resume',
      s3_key: 'users/user-demo-1/generated/doc-1.docx',
      display_name: 'Resume — OpenAI Backend Engineer.docx',
      format: 'docx',
      generated_at: '2026-10-01T10:00:00+00:00',
      model_notes: null,
    },
    {
      document_id: 'doc-2',
      job_id: 'job-2',
      profile_id: 'profile-1',
      doc_type: 'cover_letter',
      s3_key: 'users/user-demo-1/generated/doc-2.docx',
      display_name: 'Cover Letter — OpenAI Backend Engineer.docx',
      format: 'docx',
      generated_at: '2026-10-01T10:00:05+00:00',
      model_notes: null,
    },
  ]

  const applications: ApplicationJoined[] = [
    {
      application_id: 'app-1',
      job_id: 'job-2',
      status_id: byLabel('Applied'),
      status_label: 'Applied',
      status_history: [{ status_id: byLabel('Applied'), changed_at: '2026-10-01T10:05:00+00:00' }],
      date_applied: '2026-10-01',
      referred_by: '',
      comments: 'Applied via referral link from a friend.',
      created_at: '2026-10-01T10:05:00+00:00',
      updated_at: '2026-10-01T10:05:00+00:00',
      company: 'OpenAI',
      title: 'Backend Engineer, Platform',
      location: 'Remote',
      url: 'https://openai.com/careers/backend-engineer-platform',
      description: 'Build and scale backend services powering the API platform.',
    },
    {
      application_id: 'app-2',
      job_id: 'job-3',
      status_id: byLabel('Rejected'),
      status_label: 'Rejected',
      status_history: [
        { status_id: byLabel('Applied'), changed_at: '2026-09-27T10:00:00+00:00' },
        { status_id: byLabel('Rejected'), changed_at: '2026-10-02T09:00:00+00:00' },
      ],
      date_applied: '2026-09-27',
      referred_by: '',
      comments: 'Rejected after screen -- stack mismatch cited.',
      created_at: '2026-09-27T10:00:00+00:00',
      updated_at: '2026-10-02T09:00:00+00:00',
      company: 'Stripe',
      title: 'Software Engineer, Risk',
      location: 'Dublin, Ireland',
      url: 'https://stripe.com/jobs/software-engineer-risk',
      description: 'Build fraud detection systems at scale.',
    },
    {
      application_id: 'app-3',
      job_id: 'job-1',
      status_id: byLabel('Need to Apply'),
      status_label: 'Need to Apply',
      status_history: [{ status_id: byLabel('Need to Apply'), changed_at: '2026-09-29T06:00:00+00:00' }],
      date_applied: null,
      referred_by: '',
      comments: '',
      created_at: '2026-09-29T06:00:00+00:00',
      updated_at: '2026-09-29T06:00:00+00:00',
      company: 'Anthropic',
      title: 'ML Engineer, Alignment',
      location: 'San Francisco, CA',
      url: 'https://www.anthropic.com/careers/jobs/ml-engineer-alignment',
      description: 'Work on alignment research and productionizing safety techniques.',
    },
  ]

  const chatSessions: ChatSession[] = [
    {
      session_id: 'session-1',
      user_id: demoUserId,
      title: 'New Anthropic roles today',
      created_at: '2026-10-03T08:00:00+00:00',
      updated_at: '2026-10-03T08:02:00+00:00',
      messages: [
        { role: 'user', content: 'find me new jobs', timestamp: '2026-10-03T08:00:00+00:00' },
        {
          role: 'assistant',
          content: 'Found 2 new postings today, both from Anthropic. The interpretability role scores 91 -- want me to tailor your resume for it?',
          timestamp: '2026-10-03T08:00:05+00:00',
          jobs: [
            { job_id: 'job-1', title: 'ML Engineer, Alignment', company: 'Anthropic', score: 88, location: 'San Francisco, CA' },
            { job_id: 'job-4', title: 'Research Engineer, Interpretability', company: 'Anthropic', score: 91, location: 'San Francisco, CA' },
          ],
        },
      ],
    },
    {
      session_id: 'session-2',
      user_id: demoUserId,
      title: 'Why am I getting rejected?',
      created_at: '2026-10-02T14:00:00+00:00',
      updated_at: '2026-10-02T14:01:30+00:00',
      messages: [
        { role: 'user', content: 'why do I keep getting rejected?', timestamp: '2026-10-02T14:00:00+00:00' },
        {
          role: 'assistant',
          content: 'Looking at your rejections so far, Kubernetes and Go come up most often as missing skills. Want a study plan?',
          timestamp: '2026-10-02T14:01:30+00:00',
        },
      ],
    },
  ]

  return {
    users: [
      {
        user_id: demoUserId,
        email: MOCK_DEMO_EMAIL,
        password: MOCK_DEMO_PASSWORD,
        created_at: '2026-08-01T00:00:00+00:00',
        notify_email: MOCK_DEMO_EMAIL,
        digest_enabled: true,
        totp_enabled: false,
      },
      {
        user_id: 'user-demo-2fa',
        email: MOCK_2FA_EMAIL,
        password: MOCK_2FA_PASSWORD,
        created_at: '2026-08-01T00:00:00+00:00',
        notify_email: MOCK_2FA_EMAIL,
        digest_enabled: true,
        totp_enabled: true,
        totp_code: MOCK_2FA_CODE,
      },
    ],
    currentUserId: demoUserId,
    companies: [
      {
        company_id: 'company-1',
        user_id: demoUserId,
        company: 'Anthropic',
        careers_url: 'https://www.anthropic.com/careers/jobs',
        added_at: '2026-08-02T00:00:00+00:00',
      },
      {
        company_id: 'company-2',
        user_id: demoUserId,
        company: 'OpenAI',
        careers_url: 'https://openai.com/careers',
        added_at: '2026-08-02T00:00:00+00:00',
      },
    ],
    jobs,
    profile,
    documents,
    statuses,
    applications,
    chatSessions,
    nextId: 100,
  }
}

export let mockState: MockState = freshState()

export function resetMockStore(): void {
  mockState = freshState()
  mockRequestLog.length = 0
}

export function nextMockId(prefix: string): string {
  mockState.nextId += 1
  return `${prefix}-${mockState.nextId}`
}

// ---------------------------------------------------------------------------
// Request log, for component/integration tests to assert on payloads.
// ---------------------------------------------------------------------------

export interface LoggedRequest {
  method: string
  path: string
  body: unknown
}

export const mockRequestLog: LoggedRequest[] = []

export function logMockRequest(method: string, path: string, body: unknown): void {
  mockRequestLog.push({ method, path, body })
}
