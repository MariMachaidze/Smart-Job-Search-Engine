import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export function WelcomePage() {
  const { isAuthenticated } = useAuth()

  return (
    <div className="page">
      <div className="welcome-hero">
        <h1>Your job hunt, run by an agent.</h1>
        <p>
          Smart Job Search Engine discovers new postings every day, scores them against your resume, drafts a
          tailored resume and cover letter on request, and tracks every application through to an offer --
          all from one chat window or a ranked job feed.
        </p>
        <div className="welcome-actions">
          <Link to="/chat" className="btn btn-primary">
            Open Chat
          </Link>
          <Link to="/jobs" className="btn">
            Browse Job Search
          </Link>
          {!isAuthenticated && (
            <Link to="/login" className="btn">
              Log in / Sign up
            </Link>
          )}
        </div>
      </div>

      <div className="stat-grid">
        <div className="card">
          <strong>Daily discovery</strong>
          <p className="hint-text">
            Companies you add are checked automatically every day via their ATS, scored against your profile.
          </p>
        </div>
        <div className="card">
          <strong>Tailored documents</strong>
          <p className="hint-text">
            Generate a resume and cover letter tuned to a specific posting in one click -- never fabricated,
            only reorganized from what's actually in your profile.
          </p>
        </div>
        <div className="card">
          <strong>Full tracker</strong>
          <p className="hint-text">
            A customizable status pipeline keeps every application's history, with statistics and skill-gap
            recommendations derived straight from your outcomes.
          </p>
        </div>
      </div>
    </div>
  )
}
