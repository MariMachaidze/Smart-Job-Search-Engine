import { useState } from 'react'
import type { JobWithScore } from '../api/types'

interface JobCardProps {
  job: JobWithScore
  onRate: (feedback: 'relevant' | 'not_relevant', reason?: string) => void
  onTailor: () => void
  tailoring?: boolean
}

/** Full job card used on the Job Search page: title/company/location/score
 * plus a relevant/not-relevant control (not-relevant prompts for an
 * optional reason, per plan section 5) and a "tailor resume" action. */
export function JobCard({ job, onRate, onTailor, tailoring }: JobCardProps) {
  const [showReasonInput, setShowReasonInput] = useState(false)
  const [reason, setReason] = useState('')

  function handleNotRelevantClick() {
    setShowReasonInput(true)
  }

  function submitNotRelevant() {
    onRate('not_relevant', reason.trim() || undefined)
    setShowReasonInput(false)
    setReason('')
  }

  return (
    <div className="card job-card" data-testid={`job-card-${job.job_id}`}>
      <div className="job-card-header">
        <div>
          <div className="job-card-title">{job.title}</div>
          <div className="job-card-company">
            {job.company} · {job.location}
            {job.is_remote ? ' · Remote' : ''}
          </div>
        </div>
        {job.score !== null && <div className="job-card-score">{job.score}</div>}
      </div>

      {job.rationale && <p className="hint-text">{job.rationale}</p>}

      <div className="job-card-actions">
        <a className="btn btn-small" href={job.url} target="_blank" rel="noreferrer">
          View posting
        </a>
        <button
          type="button"
          className={`btn btn-small ${job.user_feedback === 'relevant' ? 'btn-primary' : ''}`}
          onClick={() => onRate('relevant')}
        >
          {job.user_feedback === 'relevant' ? 'Marked relevant' : 'Relevant'}
        </button>
        <button
          type="button"
          className={`btn btn-small ${job.user_feedback === 'not_relevant' ? 'btn-danger' : ''}`}
          onClick={handleNotRelevantClick}
        >
          {job.user_feedback === 'not_relevant' ? 'Marked not relevant' : 'Not relevant'}
        </button>
        <button type="button" className="btn btn-small btn-primary" onClick={onTailor} disabled={tailoring}>
          {tailoring ? 'Tailoring…' : 'Tailor resume'}
        </button>
      </div>

      {showReasonInput && (
        <div className="form-field" style={{ marginTop: '0.25rem', marginBottom: 0 }}>
          <label htmlFor={`reason-${job.job_id}`}>Why not relevant? (optional)</label>
          <div className="inline-flex">
            <input
              id={`reason-${job.job_id}`}
              type="text"
              placeholder="e.g. too much travel, wrong stack"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <button type="button" className="btn btn-small btn-primary" onClick={submitNotRelevant}>
              Submit
            </button>
          </div>
        </div>
      )}

      {job.feedback_reason && <p className="hint-text">Reason noted: {job.feedback_reason}</p>}
    </div>
  )
}
