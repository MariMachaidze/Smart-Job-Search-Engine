import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { RequireAuth } from './auth/RequireAuth'
import { Navbar } from './components/Navbar'
import { WelcomePage } from './pages/WelcomePage'
import { LoginPage } from './pages/LoginPage'
import { JobSearchPage } from './pages/JobSearchPage'
import { ChatPage } from './pages/ChatPage'
import { ProfilePage } from './pages/profile/ProfilePage'

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <div className="app-shell">
          <Navbar />
          <Routes>
            <Route path="/" element={<WelcomePage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/jobs"
              element={
                <RequireAuth>
                  <JobSearchPage />
                </RequireAuth>
              }
            />
            <Route
              path="/chat"
              element={
                <RequireAuth>
                  <ChatPage />
                </RequireAuth>
              }
            />
            <Route
              path="/profile"
              element={
                <RequireAuth>
                  <ProfilePage />
                </RequireAuth>
              }
            />
          </Routes>
        </div>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
