import { describe, expect, it, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { JobSearchPage } from './JobSearchPage'
import { setToken } from '../api/client'
import { mockRequestLog } from '../api/mock/data'

describe('JobSearchPage', () => {
  beforeEach(() => {
    // user-demo-1 is the seeded demo user in src/api/mock/data.ts.
    setToken('mock-token-user-demo-1')
    mockRequestLog.length = 0
  })

  it('renders the ranked job feed with title/company/location/score', async () => {
    render(<JobSearchPage />)

    expect(await screen.findByText('Research Engineer, Interpretability')).toBeInTheDocument()
    const topCard = screen.getByTestId('job-card-job-4')
    expect(within(topCard).getByText(/Anthropic.*San Francisco/)).toBeInTheDocument()
    expect(within(topCard).getByText('91')).toBeInTheDocument()
  })

  it('rates a job as relevant and sends the expected payload', async () => {
    const user = userEvent.setup()
    render(<JobSearchPage />)

    await screen.findByText('Research Engineer, Interpretability')
    const card = screen.getByTestId('job-card-job-4')
    await user.click(within(card).getByRole('button', { name: /^relevant$/i }))

    await waitFor(() => {
      const req = mockRequestLog.find((r) => r.path === '/jobs/job-4/feedback')
      expect(req?.body).toMatchObject({ feedback: 'relevant' })
    })
  })

  it('rates a job as not relevant with an optional reason', async () => {
    const user = userEvent.setup()
    render(<JobSearchPage />)

    await screen.findByText('Research Engineer, Interpretability')
    const card = screen.getByTestId('job-card-job-4')
    await user.click(within(card).getByRole('button', { name: /not relevant/i }))

    const reasonInput = within(card).getByPlaceholderText(/too much travel/i)
    await user.type(reasonInput, 'too much travel')
    await user.click(within(card).getByRole('button', { name: /^submit$/i }))

    await waitFor(() => {
      const req = mockRequestLog.find((r) => r.path === '/jobs/job-4/feedback')
      expect(req?.body).toMatchObject({ feedback: 'not_relevant', reason: 'too much travel' })
    })
  })

  it('tailors a resume for a job', async () => {
    const user = userEvent.setup()
    render(<JobSearchPage />)

    await screen.findByText('Research Engineer, Interpretability')
    const card = screen.getByTestId('job-card-job-4')
    await user.click(within(card).getByRole('button', { name: /tailor resume/i }))

    await waitFor(() => {
      const req = mockRequestLog.find((r) => r.path === '/jobs/job-4/tailor')
      expect(req).toBeDefined()
    })
    expect(await screen.findByText(/Generated ".*"/)).toBeInTheDocument()
  })
})
