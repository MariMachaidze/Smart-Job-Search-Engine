import type { JobCardPayload } from '../api/types'

interface MiniJobCardProps {
  job: JobCardPayload
  onRate: (feedback: 'relevant' | 'not_relevant') => void
  onTailor: () => void
}

/** Compact inline job card rendered inside a chat message (plan section 11:
 * "list_jobs() results can be rendered as structured job cards inline in
 * the chat UI (title/company/score/one-tap rate-or-tailor)"). */
export function MiniJobCard({ job, onRate, onTailor }: MiniJobCardProps) {
  return (
    <div className="job-card-mini" data-testid={`mini-job-card-${job.job_id}`}>
      <div>
        <strong>{job.title}</strong>
        <div className="hint-text">
          {job.company}
          {job.location ? ` · ${job.location}` : ''}
          {job.score !== null ? ` · score ${job.score}` : ''}
        </div>
      </div>
      <div className="job-card-actions">
        <button type="button" className="btn btn-small" onClick={() => onRate('relevant')}>
          Rate
        </button>
        <button type="button" className="btn btn-small btn-primary" onClick={onTailor}>
          Tailor
        </button>
      </div>
    </div>
  )
}
