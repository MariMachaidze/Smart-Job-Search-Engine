import { useEffect, useState, type FormEvent } from 'react'
import { companiesApi } from '../../api/endpoints'
import { ApiError } from '../../api/client'
import type { CompanySource } from '../../api/types'

export function CompaniesTab() {
  const [companies, setCompanies] = useState<CompanySource[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [careersUrl, setCareersUrl] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    void load()
  }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      setCompanies(await companiesApi.list())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load companies.')
    } finally {
      setLoading(false)
    }
  }

  async function handleAdd(e: FormEvent) {
    e.preventDefault()
    if (!name.trim() || !careersUrl.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      const created = await companiesApi.create({ company: name.trim(), careers_url: careersUrl.trim() })
      setCompanies((prev) => [...prev, created])
      setName('')
      setCareersUrl('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to add company.')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleRemove(companyId: string) {
    try {
      await companiesApi.remove(companyId)
      setCompanies((prev) => prev.filter((c) => c.company_id !== companyId))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to remove company.')
    }
  }

  return (
    <div>
      <form className="card" onSubmit={handleAdd} style={{ marginBottom: '1.5rem' }}>
        <div className="spaced-row" style={{ marginBottom: 0 }}>
          <div className="form-field" style={{ flex: 1, marginBottom: 0 }}>
            <label htmlFor="company-name">Company name</label>
            <input id="company-name" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="form-field" style={{ flex: 2, marginBottom: 0 }}>
            <label htmlFor="company-url">Careers URL</label>
            <input
              id="company-url"
              type="url"
              value={careersUrl}
              onChange={(e) => setCareersUrl(e.target.value)}
              required
            />
          </div>
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            Add company
          </button>
        </div>
      </form>

      {error && <p className="error-text">{error}</p>}

      {loading ? (
        <p className="empty-state">Loading companies…</p>
      ) : companies.length === 0 ? (
        <p className="empty-state">No companies added yet.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Company</th>
                <th>Careers URL</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {companies.map((c) => (
                <tr key={c.company_id}>
                  <td>{c.company}</td>
                  <td>
                    <a href={c.careers_url} target="_blank" rel="noreferrer">
                      {c.careers_url}
                    </a>
                  </td>
                  <td>
                    <button type="button" className="btn btn-small btn-danger" onClick={() => handleRemove(c.company_id)}>
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
