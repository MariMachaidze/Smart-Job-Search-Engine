import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { profileApi } from '../../api/endpoints'
import { ApiError } from '../../api/client'
import type { CandidateProfile } from '../../api/types'

export function SkillsTab() {
  const [profile, setProfile] = useState<CandidateProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    void loadProfile()
  }, [])

  async function loadProfile() {
    setLoading(true)
    setError(null)
    try {
      setProfile(await profileApi.get())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load profile.')
    } finally {
      setLoading(false)
    }
  }

  async function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      const updated = await profileApi.upload(file)
      setProfile(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to parse resume.')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  if (loading) return <p className="empty-state">Loading profile…</p>

  return (
    <div>
      <div className="spaced-row">
        <div />
        <div>
          <input
            ref={fileInputRef}
            id="resume-upload"
            type="file"
            accept="application/pdf"
            onChange={handleFileChange}
            style={{ display: 'none' }}
          />
          <button
            type="button"
            className="btn btn-primary"
            disabled={uploading}
            onClick={() => fileInputRef.current?.click()}
          >
            {uploading ? 'Uploading…' : profile ? 'Re-upload resume' : 'Upload resume'}
          </button>
        </div>
      </div>

      {error && <p className="error-text">{error}</p>}

      {!profile ? (
        <p className="empty-state">No resume on file yet. Upload a PDF to get started.</p>
      ) : (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>{profile.full_name}</h3>
          <p className="hint-text">
            {profile.email} {profile.phone ? `· ${profile.phone}` : ''} {profile.location ? `· ${profile.location}` : ''}
          </p>
          <p>{profile.summary}</p>

          <h4>Skills</h4>
          <div>
            {profile.skills.map((skill) => (
              <span key={skill} className="status-pill" style={{ background: '#eef1fc', marginRight: '0.4rem', marginBottom: '0.4rem', display: 'inline-block' }}>
                {skill}
              </span>
            ))}
          </div>

          <h4>Experience</h4>
          {profile.experience.map((exp, i) => (
            <div key={i} style={{ marginBottom: '0.75rem' }}>
              <strong>
                {exp.title} · {exp.company}
              </strong>
              <div className="hint-text">
                {exp.start_date ?? '?'} – {exp.end_date ?? 'present'} {exp.location ? `· ${exp.location}` : ''}
              </div>
              <ul>
                {exp.bullets.map((bullet, bi) => (
                  <li key={bi}>{bullet}</li>
                ))}
              </ul>
            </div>
          ))}

          <h4>Education</h4>
          {profile.education.map((edu, i) => (
            <div key={i} style={{ marginBottom: '0.5rem' }}>
              {edu.degree} {edu.field ? `in ${edu.field}` : ''}, {edu.institution} ({edu.start_date ?? '?'} – {edu.end_date ?? '?'})
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
