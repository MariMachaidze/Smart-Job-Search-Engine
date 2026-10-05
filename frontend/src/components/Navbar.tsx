import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export function Navbar() {
  const { isAuthenticated, user, logout } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/')
  }

  return (
    <header className="navbar">
      <NavLink to="/" className="navbar-brand">
        Smart Job Search
      </NavLink>
      <nav className="navbar-links">
        <NavLink to="/jobs" className={({ isActive }) => (isActive ? 'active' : '')}>
          Job Search
        </NavLink>
        <NavLink to="/chat" className={({ isActive }) => (isActive ? 'active' : '')}>
          Chat
        </NavLink>
        <NavLink to="/profile" className={({ isActive }) => (isActive ? 'active' : '')}>
          Profile
        </NavLink>
        {isAuthenticated ? (
          <>
            <span className="hint-text">{user?.email}</span>
            <button type="button" className="btn btn-small" onClick={handleLogout}>
              Log out
            </button>
          </>
        ) : (
          <NavLink to="/login" className={({ isActive }) => (isActive ? 'active' : '')}>
            Log in
          </NavLink>
        )}
      </nav>
    </header>
  )
}
