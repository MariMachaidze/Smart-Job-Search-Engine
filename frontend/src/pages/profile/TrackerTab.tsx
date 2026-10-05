import { useEffect, useState } from 'react'
import { trackerApi } from '../../api/endpoints'
import { ApiError } from '../../api/client'
import type { ApplicationJoined, TrackerStatus } from '../../api/types'

export function TrackerTab() {
  const [applications, setApplications] = useState<ApplicationJoined[]>([])
  const [statuses, setStatuses] = useState<TrackerStatus[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void load()
  }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const [apps, statusList] = await Promise.all([trackerApi.listApplications(), trackerApi.listStatuses()])
      setApplications(apps)
      setStatuses([...statusList].sort((a, b) => a.order - b.order))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load tracker.')
    } finally {
      setLoading(false)
    }
  }

  async function handleStatusChange(applicationId: string, statusLabel: string) {
    try {
      const updated = await trackerApi.updateApplicationStatus(applicationId, { status_label: statusLabel })
      setApplications((prev) => prev.map((a) => (a.application_id === applicationId ? updated : a)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to update status.')
    }
  }

  function colorFor(label: string | null): string {
    return statuses.find((s) => s.label === label)?.color ?? '#e0e0e0'
  }

  if (loading) return <p className="empty-state">Loading tracker…</p>

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      {applications.length === 0 ? (
        <p className="empty-state">No applications tracked yet.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Company</th>
                <th>Title</th>
                <th>Status</th>
                <th>Link</th>
                <th>Description</th>
                <th>Location</th>
                <th>Date Applied</th>
                <th>Referred By</th>
                <th>Comments</th>
              </tr>
            </thead>
            <tbody>
              {applications.map((app) => (
                <tr key={app.application_id} data-testid={`tracker-row-${app.application_id}`}>
                  <td>{app.company}</td>
                  <td>{app.title}</td>
                  <td>
                    <select
                      value={app.status_label ?? ''}
                      onChange={(e) => handleStatusChange(app.application_id, e.target.value)}
                      aria-label={`Status for ${app.title}`}
                      style={{ background: colorFor(app.status_label), borderRadius: 6, border: 'none', padding: '0.3rem 0.5rem' }}
                    >
                      {statuses.map((s) => (
                        <option key={s.status_id} value={s.label}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    {app.url ? (
                      <a href={app.url} target="_blank" rel="noreferrer">
                        link
                      </a>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="wrap">{app.description ?? '—'}</td>
                  <td>{app.location ?? '—'}</td>
                  <td>{app.date_applied ?? '—'}</td>
                  <td>{app.referred_by || '—'}</td>
                  <td className="wrap">{app.comments || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
