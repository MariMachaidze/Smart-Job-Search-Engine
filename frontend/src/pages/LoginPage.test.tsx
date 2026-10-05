import { describe, expect, it, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { LoginPage } from './LoginPage'
import { AuthProvider } from '../auth/AuthContext'
import { mockRequestLog } from '../api/mock/data'
import { getToken } from '../api/client'

function renderLogin() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('LoginPage', () => {
  beforeEach(() => {
    mockRequestLog.length = 0
  })

  it('renders email/password fields and a login button by default', () => {
    renderLogin()
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /log in/i })).toBeInTheDocument()
  })

  it('submits POST /auth/login with the entered credentials and stores the token', async () => {
    const user = userEvent.setup()
    renderLogin()

    await user.type(screen.getByLabelText(/email/i), 'demo@example.com')
    await user.type(screen.getByLabelText(/^password$/i), 'password123')
    await user.click(screen.getByRole('button', { name: /log in/i }))

    await waitFor(() => expect(getToken()).toBeTruthy())

    const loginRequest = mockRequestLog.find((r) => r.path === '/auth/login')
    expect(loginRequest).toBeDefined()
    expect(loginRequest?.body).toMatchObject({ email: 'demo@example.com', password: 'password123' })
  })

  it('shows a 2FA step when the account requires it, then verifies the code', async () => {
    const user = userEvent.setup()
    renderLogin()

    await user.type(screen.getByLabelText(/email/i), '2fa@example.com')
    await user.type(screen.getByLabelText(/^password$/i), 'password123')
    await user.click(screen.getByRole('button', { name: /log in/i }))

    expect(await screen.findByLabelText(/two-factor code/i)).toBeInTheDocument()

    await user.type(screen.getByLabelText(/two-factor code/i), '123456')
    await user.click(screen.getByRole('button', { name: /verify code/i }))

    await waitFor(() => expect(getToken()).toBeTruthy())

    const secondLoginRequest = [...mockRequestLog].reverse().find((r) => r.path === '/auth/login')
    expect(secondLoginRequest?.body).toMatchObject({ totp_code: '123456' })
  })

  it('switches to signup mode and submits POST /auth/signup', async () => {
    const user = userEvent.setup()
    renderLogin()

    await user.click(screen.getByRole('button', { name: /sign up instead/i }))
    await user.type(screen.getByLabelText(/email/i), 'newperson@example.com')
    await user.type(screen.getByLabelText(/^password$/i), 'brandnewpassword')
    await user.click(screen.getByRole('button', { name: /^sign up$/i }))

    await waitFor(() => expect(getToken()).toBeTruthy())
    const signupRequest = mockRequestLog.find((r) => r.path === '/auth/signup')
    expect(signupRequest?.body).toMatchObject({ email: 'newperson@example.com', password: 'brandnewpassword' })
  })
})
