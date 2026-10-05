import { useEffect, useState } from 'react'
import { documentsApi } from '../../api/endpoints'
import { ApiError } from '../../api/client'
import type { GeneratedDocument } from '../../api/types'

export function DocumentsTab() {
  const [documents, setDocuments] = useState<GeneratedDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void load()
  }, [])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      setDocuments(await documentsApi.list())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load documents.')
    } finally {
      setLoading(false)
    }
  }

  async function handleDownload(documentId: string) {
    try {
      const { download_url } = await documentsApi.downloadUrl(documentId)
      window.open(download_url, '_blank', 'noopener')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to get download link.')
    }
  }

  if (loading) return <p className="empty-state">Loading documents…</p>

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      {documents.length === 0 ? (
        <p className="empty-state">No generated resumes or cover letters yet. Tailor one from the Job Search page.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Document</th>
                <th>Type</th>
                <th>Generated</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.document_id}>
                  <td>{doc.display_name}</td>
                  <td>{doc.doc_type === 'resume' ? 'Resume' : 'Cover Letter'}</td>
                  <td>{new Date(doc.generated_at).toLocaleString()}</td>
                  <td>
                    <button type="button" className="btn btn-small" onClick={() => handleDownload(doc.document_id)}>
                      Download
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
