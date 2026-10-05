import { describe, expect, it, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatPage } from './ChatPage'
import { setToken } from '../api/client'
import { mockRequestLog } from '../api/mock/data'

describe('ChatPage', () => {
  beforeEach(() => {
    setToken('mock-token-user-demo-1')
    mockRequestLog.length = 0
  })

  it('renders the saved-sessions sidebar, newest first, and loads the first session thread', async () => {
    render(<ChatPage />)
    expect(await screen.findByText('New Anthropic roles today')).toBeInTheDocument()
    expect(screen.getByText('Why am I getting rejected?')).toBeInTheDocument()
    // The first (most-recently-updated) session's messages load automatically.
    expect(await screen.findByText(/find me new jobs/)).toBeInTheDocument()
  })

  it('sends a message, streams the reply, and renders inline job cards for job-shaped tool results', async () => {
    const user = userEvent.setup()
    render(<ChatPage />)

    await screen.findByText('New Anthropic roles today')
    const input = screen.getByLabelText(/chat message/i)
    await user.type(input, 'find me new jobs please')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => {
      const req = mockRequestLog.find((r) => typeof r.path === 'string' && r.path.includes('/message'))
      expect(req?.body).toMatchObject({ content: 'find me new jobs please' })
    })

    // Streamed assistant text eventually lands in the thread.
    await waitFor(() => {
      expect(screen.getByText(/want me to tailor a resume/i)).toBeInTheDocument()
    })

    // Job-shaped tool results render as structured mini job cards, not just text.
    const jobCard = await screen.findByTestId('mini-job-card-job-1')
    expect(jobCard).toBeInTheDocument()

    await user.click(within(jobCard).getByRole('button', { name: /tailor/i }))
    await waitFor(() => {
      expect(mockRequestLog.some((r) => r.path === '/jobs/job-1/tailor')).toBe(true)
    })
  })

  it('starts a new conversation', async () => {
    const user = userEvent.setup()
    render(<ChatPage />)

    await screen.findByText('New Anthropic roles today')
    await user.click(screen.getByRole('button', { name: /new chat/i }))

    await waitFor(() => {
      expect(mockRequestLog.some((r) => r.path === '/chat/sessions')).toBe(true)
    })
    expect(await screen.findByText(/say hello/i)).toBeInTheDocument()
  })
})
