import { useEffect, useState } from 'react'
import { statisticsApi } from '../../api/endpoints'
import { ApiError } from '../../api/client'
import type { SkillGapResult, StatisticsSummary, StatusCountBucket } from '../../api/types'
import { StatTile } from '../../components/StatTile'

export function StatisticsTab() {
  const [summary, setSummary] = useState<StatisticsSummary | null>(null)
  const [buckets, setBuckets] = useState<StatusCountBucket[]>([])
  const [skillGap, setSkillGap] = useState<SkillGapResult | null>(null)
  const [granularity, setGranularity] = useState<'daily' | 'monthly'>('daily')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void load()
  }, [granularity])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const [summaryData, timeseriesData, skillGapData] = await Promise.all([
        statisticsApi.summary(),
        statisticsApi.timeseries(granularity),
        statisticsApi.skillGap(),
      ])
      setSummary(summaryData)
      setBuckets(timeseriesData)
      setSkillGap(skillGapData)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load statistics.')
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <p className="empty-state">Loading statistics…</p>

  return (
    <div>
      {error && <p className="error-text">{error}</p>}

      {summary && (
        <div className="stat-grid">
          <StatTile label="Total applications" value={summary.total_applications} />
          <StatTile label="Applied" value={summary.applied_count} />
          <StatTile label="Ever interviewed" value={summary.ever_interviewed_count} />
          <StatTile label="Offers" value={summary.offer_count} />
          <StatTile label="Rejected" value={summary.rejected_count} />
          <StatTile label="Rejection rate" value={`${Math.round(summary.rejection_rate * 100)}%`} />
          <StatTile label="True interview rate" value={`${Math.round(summary.true_interview_rate * 100)}%`} />
          <StatTile label="No response" value={summary.no_response_count} />
        </div>
      )}

      <div className="spaced-row">
        <h3 style={{ margin: 0 }}>Counts over time</h3>
        <div className="tabs" style={{ border: 'none', margin: 0 }} role="tablist">
          <button
            type="button"
            className={`tab-button ${granularity === 'daily' ? 'active' : ''}`}
            onClick={() => setGranularity('daily')}
          >
            Daily
          </button>
          <button
            type="button"
            className={`tab-button ${granularity === 'monthly' ? 'active' : ''}`}
            onClick={() => setGranularity('monthly')}
          >
            Monthly
          </button>
        </div>
      </div>

      {buckets.length === 0 ? (
        <p className="empty-state">No application history yet.</p>
      ) : (
        <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
          <table>
            <thead>
              <tr>
                <th>Period</th>
                <th>Status</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              {buckets.map((b, i) => (
                <tr key={i}>
                  <td>{b.period}</td>
                  <td>{b.status}</td>
                  <td>{b.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3>Skill gap recommendations</h3>
      {skillGap && (
        <div className="card">
          {!skillGap.threshold_met ? (
            <p className="hint-text">{skillGap.recommendation}</p>
          ) : (
            <>
              <p>{skillGap.recommendation}</p>
              <div>
                {skillGap.missing_skills.map((skill) => (
                  <span
                    key={skill}
                    className="status-pill"
                    style={{ background: '#fdecea', color: '#b71c1c', marginRight: '0.4rem', display: 'inline-block' }}
                  >
                    {skill}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
