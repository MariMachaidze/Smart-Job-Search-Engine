import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
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
    render(
      <MemoryRouter initialEntries={['/profile']}>
        <AuthProvider>
          <RequireAuth>
            <div>secret profile content</div>
          </RequireAuth>
        </AuthProvider>
      </MemoryRouter>,
    )
    expect(screen.queryByText('secret profile content')).not.toBeInTheDocument()
  })
})
