/**
 * Dev-only MSW worker. Started conditionally from src/main.tsx, controlled
 * by VITE_USE_MOCKS (defaults to "true" when VITE_API_BASE_URL is unset,
 * since there's nothing real to talk to otherwise). Flip VITE_USE_MOCKS=false
 * once the real backend (M's app/main.py) is reachable and point
 * VITE_API_BASE_URL at it -- no other file changes.
 */
import { setupWorker } from 'msw/browser'
import { handlers } from './handlers'

export const worker = setupWorker(...handlers)
