import { describe, expect, it, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProfilePage } from './ProfilePage'
import { setToken } from '../../api/client'
import { mockRequestLog } from '../../api/mock/data'

describe('ProfilePage', () => {
  beforeEach(() => {
    setToken('mock-token-user-demo-1')
    mockRequestLog.length = 0
  })

  it('shows the Skills tab by default with parsed profile fields', async () => {
    render(<ProfilePage />)
    expect(await screen.findByText('Mariam Machaidze')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /re-upload resume/i })).toBeInTheDocument()
  })

  it('switches to the Companies tab and adds a company', async () => {
    const user = userEvent.setup()
    render(<ProfilePage />)

    await screen.findByText('Mariam Machaidze')
    await user.click(screen.getByRole('tab', { name: /companies/i }))

    await screen.findByText('Anthropic')
    await user.type(screen.getByLabelText(/company name/i), 'Netflix')
    await user.type(screen.getByLabelText(/careers url/i), 'https://jobs.netflix.com')
    await user.click(screen.getByRole('button', { name: /add company/i }))

    await waitFor(() => {
      const req = mockRequestLog.find((r) => r.path === '/companies')
      expect(req?.body).toMatchObject({ company: 'Netflix', careers_url: 'https://jobs.netflix.com' })
    })
    expect(await screen.findByText('Netflix')).toBeInTheDocument()
  })

  it('switches to the Tracker tab and changes an application status via the dropdown', async () => {
    const user = userEvent.setup()
    render(<ProfilePage />)

    await screen.findByText('Mariam Machaidze')
    await user.click(screen.getByRole('tab', { name: /tracker/i }))

    const select = await screen.findByLabelText(/status for backend engineer, platform/i)
    await user.selectOptions(select, 'Interviewed')

    await waitFor(() => {
      const req = mockRequestLog.find((r) => r.path === '/tracker/applications/app-1')
      expect(req?.body).toMatchObject({ status_label: 'Interviewed' })
    })
  })

  it('switches to the Statistics tab and shows stat tiles', async () => {
    const user = userEvent.setup()
    render(<ProfilePage />)

    await screen.findByText('Mariam Machaidze')
    await user.click(screen.getByRole('tab', { name: /statistics/i }))

    expect(await screen.findByText('Total applications')).toBeInTheDocument()
    expect(screen.getByText(/skill gap recommendations/i)).toBeInTheDocument()
  })

  it('switches to the Resumes & Cover Letters tab and lists documents', async () => {
    const user = userEvent.setup()
    render(<ProfilePage />)

    await screen.findByText('Mariam Machaidze')
    await user.click(screen.getByRole('tab', { name: /resumes & cover letters/i }))

    expect(await screen.findByText(/Resume — OpenAI Backend Engineer\.docx/)).toBeInTheDocument()
  })
})
