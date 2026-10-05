import { useEffect, useState } from 'react'
import { jobsApi } from '../api/endpoints'
import { ApiError } from '../api/client'
import type { JobWithScore } from '../api/types'
import { JobCard } from '../components/JobCard'

export function JobSearchPage() {
  const [jobs, setJobs] = useState<JobWithScore[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [runningDiscovery, setRunningDiscovery] = useState(false)
  const [tailoringJobId, setTailoringJobId] = useState<string | null>(null)
  const [tailorMessage, setTailorMessage] = useState<string | null>(null)

  useEffect(() => {
    void loadJobs()
  }, [])

  async function loadJobs() {
    setLoading(true)
    setError(null)
    try {
      const data = await jobsApi.list()
      setJobs([...data].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load jobs.')
    } finally {
      setLoading(false)
    }
  }

  async function handleRunDiscovery() {
    setRunningDiscovery(true)
    try {
      await jobsApi.runDiscovery()
      await loadJobs()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to start discovery.')
    } finally {
      setRunningDiscovery(false)
    }
  }

  async function handleRate(jobId: string, feedback: 'relevant' | 'not_relevant', reason?: string) {
    try {
      const updated = await jobsApi.rate(jobId, { feedback, reason })
      setJobs((prev) => prev.map((j) => (j.job_id === jobId ? updated : j)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save feedback.')
    }
  }

  async function handleTailor(jobId: string) {
    setTailoringJobId(jobId)
    setTailorMessage(null)
    try {
      const result = await jobsApi.tailor(jobId)
      setTailorMessage(`Generated "${result.resume.display_name}" and "${result.cover_letter.display_name}".`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to tailor resume.')
    } finally {
      setTailoringJobId(null)
    }
  }

  return (
    <div className="page">
      <div className="spaced-row">
        <div>
          <h1 className="page-title">Job Search</h1>
          <p className="page-subtitle" style={{ marginBottom: 0 }}>
            Ranked, auto-discovered postings from your companies list.
          </p>
        </div>
        <button type="button" className="btn btn-primary" onClick={handleRunDiscovery} disabled={runningDiscovery}>
          {runningDiscovery ? 'Running discovery…' : 'Search now'}
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}
      {tailorMessage && <p className="hint-text">{tailorMessage}</p>}

      {loading ? (
        <p className="empty-state">Loading jobs…</p>
      ) : jobs.length === 0 ? (
        <p className="empty-state">No jobs discovered yet. Add some companies on your Profile page and run discovery.</p>
      ) : (
        jobs.map((job) => (
          <JobCard
            key={job.job_id}
            job={job}
            tailoring={tailoringJobId === job.job_id}
            onRate={(feedback, reason) => handleRate(job.job_id, feedback, reason)}
            onTailor={() => handleTailor(job.job_id)}
          />
        ))
      )}
    </div>
  )
}
