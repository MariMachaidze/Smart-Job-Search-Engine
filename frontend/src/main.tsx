import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

/**
 * Mock-to-real API swap point (see src/api/client.ts for the full
 * explanation): when VITE_USE_MOCKS is unset, mocking defaults to on
 * whenever no real VITE_API_BASE_URL is configured, since there's nothing
 * else to talk to. Once the real backend is reachable, set
 * VITE_API_BASE_URL to its URL and VITE_USE_MOCKS=false (or just remove
 * this block) -- no other file in the app needs to change.
 */
async function enableMockingIfNeeded() {
  const explicit = import.meta.env.VITE_USE_MOCKS
  const useMocks = explicit !== undefined ? explicit === 'true' : !import.meta.env.VITE_API_BASE_URL
  if (!useMocks) return
  const { worker } = await import('./api/mock/browser')
  await worker.start({ onUnhandledRequest: 'bypass' })
}

enableMockingIfNeeded().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
