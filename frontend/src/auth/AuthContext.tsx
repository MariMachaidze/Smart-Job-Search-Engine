import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { authApi } from '../api/endpoints'
import { clearToken, setToken as persistToken, getToken } from '../api/client'
import type { User } from '../api/types'

interface AuthContextValue {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  /** Resolves normally on success. If the account needs a 2FA code, resolves
   * with {requiresTwoFactor: true} instead of throwing -- the Login page
   * uses this to show the second "enter your code" step. */
  login: (email: string, password: string, totpCode?: string) => Promise<{ requiresTwoFactor: boolean }>
  signup: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken())
  const [user, setUser] = useState<User | null>(null)

  // On reload, a token may already be in localStorage with no `user` yet
  // (the User object isn't persisted, only the JWT) -- resolve it via
  // GET /auth/me. If the token's stale/invalid, log out quietly.
  useEffect(() => {
    if (!token || user) return
    authApi
      .me()
      .then(setUser)
      .catch(() => {
        clearToken()
        setTokenState(null)
      })
  }, [token, user])

  const login = useCallback(async (email: string, password: string, totpCode?: string) => {
    const res = await authApi.login({ email, password, totp_code: totpCode })
    if (res.requires_2fa) {
      return { requiresTwoFactor: true }
    }
    if (res.access_token && res.user) {
      persistToken(res.access_token)
      setTokenState(res.access_token)
      setUser(res.user)
    }
    return { requiresTwoFactor: false }
  }, [])

  const signup = useCallback(async (email: string, password: string) => {
    const res = await authApi.signup({ email, password })
    persistToken(res.access_token)
    setTokenState(res.access_token)
    setUser(res.user)
  }, [])

  const logout = useCallback(() => {
    clearToken()
    setTokenState(null)
    setUser(null)
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({ user, token, isAuthenticated: Boolean(token), login, signup, logout }),
    [user, token, login, signup, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
