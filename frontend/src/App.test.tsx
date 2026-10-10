import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { RequireAuth } from './auth/RequireAuth'
import { WelcomePage } from './pages/WelcomePage'

describe('WelcomePage', () => {
  it('renders the explainer with links into Chat and Job Search', () => {
    render(
      <MemoryRouter>
        <AuthProvider>
          <WelcomePage />
        </AuthProvider>
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: /open chat/i })).toHaveAttribute('href', '/chat')
    expect(screen.getByRole('link', { name: /browse job search/i })).toHaveAttribute('href', '/jobs')
  })
})

describe('RequireAuth', () => {
  it('redirects to /login when not authenticated', () => {
    // RequireAuth's <Navigate> needs a real <Routes> tree to resolve
    // against -- same shape App.tsx actually uses it in (a guarded route
    // alongside a real "/login" route), not just a bare child of
    // MemoryRouter. Without a matching Routes/Route structure, React
    // Router has nothing to redirect *to*, which hangs rather than
    // failing cleanly in this React Router 7 + React 19 combination.
    render(
      <MemoryRouter initialEntries={['/profile']}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<div>login page</div>} />
            <Route
              path="/profile"
              element={
                <RequireAuth>
                  <div>secret profile content</div>
                </RequireAuth>
              }
            />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )
    expect(screen.queryByText('secret profile content')).not.toBeInTheDocument()
    expect(screen.getByText('login page')).toBeInTheDocument()
  })
})
