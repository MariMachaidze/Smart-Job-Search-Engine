import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../api/client'

type Mode = 'login' | 'signup'

export function LoginPage() {
  const { login, signup } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [needsTwoFactor, setNeedsTwoFactor] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const redirectTo = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname ?? '/profile'

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      if (mode === 'signup') {
        await signup(email, password)
        navigate(redirectTo, { replace: true })
        return
      }
      const result = await login(email, password, needsTwoFactor ? totpCode : undefined)
      if (result.requiresTwoFactor) {
        setNeedsTwoFactor(true)
      } else {
        navigate(redirectTo, { replace: true })
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  function switchMode(next: Mode) {
    setMode(next)
    setError(null)
    setNeedsTwoFactor(false)
    setTotpCode('')
  }

  return (
    <div className="page page-narrow">
      <h1 className="page-title">{mode === 'login' ? 'Log in' : 'Create an account'}</h1>
      <p className="page-subtitle">
        {mode === 'login' ? "Don't have an account?" : 'Already have an account?'}{' '}
        <button
          type="button"
          className="btn btn-small"
          onClick={() => switchMode(mode === 'login' ? 'signup' : 'login')}
        >
          {mode === 'login' ? 'Sign up instead' : 'Log in instead'}
        </button>
      </p>

      <form className="card" onSubmit={handleSubmit}>
        <div className="form-field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            disabled={needsTwoFactor}
          />
        </div>
        <div className="form-field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            disabled={needsTwoFactor}
          />
        </div>

        {needsTwoFactor && (
          <div className="form-field">
            <label htmlFor="totp">Two-factor code</label>
            <input
              id="totp"
              type="text"
              inputMode="numeric"
              placeholder="6-digit code"
              value={totpCode}
              onChange={(e) => setTotpCode(e.target.value)}
              required
              autoFocus
            />
            <span className="hint-text">Enter the 6-digit code from your authenticator app.</span>
          </div>
        )}

        {error && <p className="error-text">{error}</p>}

        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting
            ? 'Please wait…'
            : needsTwoFactor
              ? 'Verify code'
              : mode === 'login'
                ? 'Log in'
                : 'Sign up'}
        </button>
      </form>
    </div>
  )
}
